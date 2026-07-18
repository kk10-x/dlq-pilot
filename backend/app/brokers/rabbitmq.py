"""Real RabbitMQ adapter.

Queue discovery uses the management HTTP API; message operations use AMQP (aio-pika).
Peek is implemented as basic.get + requeue, which is the only way to inspect a queue
over AMQP without consuming it — see the caveat on peek().
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import aio_pika
import httpx

from ..config import Settings
from ..fingerprint import fingerprint
from ..schemas import DeadMessage, QueueInfo


class RabbitMQAdapter:
    mode = "rabbitmq"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: aio_pika.abc.AbstractRobustConnection | None = None
        self._dlq_pattern = re.compile(settings.dlq_pattern)
        self._peeked: dict[str, list[DeadMessage]] = {}

    async def _connection(self) -> aio_pika.abc.AbstractRobustConnection:
        if self._conn is None or self._conn.is_closed:
            self._conn = await aio_pika.connect_robust(self._settings.rabbitmq_url)
        return self._conn

    async def list_dlqs(self) -> list[QueueInfo]:
        s = self._settings
        async with httpx.AsyncClient(auth=(s.rabbitmq_user, s.rabbitmq_password)) as client:
            resp = await client.get(f"{s.rabbitmq_mgmt_url}/api/queues", timeout=10)
            resp.raise_for_status()
        out = []
        for q in resp.json():
            if self._dlq_pattern.search(q["name"]):
                out.append(QueueInfo(name=q["name"], message_count=q.get("messages", 0)))
        return sorted(out, key=lambda q: q.name)

    @staticmethod
    def _from_amqp(queue: str, msg: aio_pika.abc.AbstractIncomingMessage) -> DeadMessage:
        headers = dict(msg.headers or {})
        deaths = headers.get("x-death") or []
        first = deaths[0] if deaths else {}
        reason = str(first.get("reason", "unknown"))
        origin = str(first.get("queue", "unknown"))
        exchange = str(first.get("exchange", "")) or msg.exchange or ""
        rks = first.get("routing-keys") or [msg.routing_key]
        payload = msg.body.decode("utf-8", errors="replace")
        fp, label = fingerprint(reason, origin, payload, headers)
        ts = first.get("time")
        first_death = (
            datetime.fromtimestamp(ts.timestamp() if hasattr(ts, "timestamp") else float(ts), tz=timezone.utc)
            if ts else None
        )
        return DeadMessage(
            id=msg.message_id or f"{queue}:{msg.delivery_tag}",
            queue=queue, payload=payload,
            headers=json.loads(json.dumps(headers, default=str)),
            exchange=exchange, routing_key=str(rks[0]) if rks else "",
            reason=reason, origin_queue=origin,
            death_count=int(first.get("count", 1)),
            first_death_at=first_death, fingerprint=fp, fingerprint_label=label,
        )

    async def peek(self, queue: str, limit: int = 500) -> list[DeadMessage]:
        """Read up to `limit` messages, then nack+requeue them all.

        Caveat: between get and requeue the messages are invisible to other
        consumers, and requeueing resets delivery order. Fine for a triage
        dashboard; not a zero-impact operation on a hot queue.
        """
        conn = await self._connection()
        out: list[DeadMessage] = []
        async with conn.channel() as channel:
            q = await channel.get_queue(queue, ensure=False)
            pending = []
            for _ in range(limit):
                msg = await q.get(fail=False, timeout=2)
                if msg is None:
                    break
                pending.append(msg)
                out.append(self._from_amqp(queue, msg))
            for msg in pending:
                await msg.nack(requeue=True)
        self._peeked[queue] = out
        return out

    async def replay(self, message: DeadMessage) -> bool:
        """Republish to the origin exchange/routing key, then ack (remove) from the DLQ.

        Finds the message in the DLQ by message id (or payload match as fallback).
        Returns True when the republish was confirmed by the broker; whether the
        consumer then succeeds is observable on the next refresh (at-least-once).
        """
        conn = await self._connection()
        async with conn.channel(publisher_confirms=True) as channel:
            q = await channel.get_queue(message.queue, ensure=False)
            scanned = 0
            while scanned < 2000:
                msg = await q.get(fail=False, timeout=2)
                if msg is None:
                    return False
                scanned += 1
                candidate_id = msg.message_id or f"{message.queue}:{msg.delivery_tag}"
                if candidate_id == message.id or msg.body.decode("utf-8", errors="replace") == message.payload:
                    exchange = (
                        await channel.get_exchange(message.exchange, ensure=False)
                        if message.exchange else channel.default_exchange
                    )
                    routing_key = message.routing_key or message.origin_queue
                    headers = {k: v for k, v in (msg.headers or {}).items() if k != "x-death"}
                    headers["x-dlq-pilot-replayed"] = True
                    await exchange.publish(
                        aio_pika.Message(body=msg.body, headers=headers, message_id=msg.message_id),
                        routing_key=routing_key,
                    )
                    await msg.ack()
                    return True
                await msg.nack(requeue=True)
            return False

    async def close(self) -> None:
        if self._conn and not self._conn.is_closed:
            await self._conn.close()
