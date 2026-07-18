"""Demo adapter: an in-process 'broker' pre-seeded with realistic dead letters.

Lets anyone run the full dashboard with zero infrastructure (no RabbitMQ, no Docker).
Replay is simulated honestly: most replayed messages succeed, but a deterministic
fraction dead-letters again — mirroring real at-least-once behavior where replaying
into a still-broken consumer sends messages straight back.
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone

from ..fingerprint import fingerprint
from ..schemas import DeadMessage, QueueInfo

_SEED = 1502  # deterministic demo data run-to-run

# (dlq, origin queue, exchange, routing key, reason, error template, payload builder)
_SCENARIOS = [
    (
        "orders.dlq", "orders", "commerce", "order.created", "rejected",
        "ValidationError: order {oid} missing required field 'amount'",
        lambda oid: {"order_id": oid, "customer": f"cust-{oid % 97}", "currency": "INR"},
        34,
    ),
    (
        "orders.dlq", "orders", "commerce", "order.created", "rejected",
        "KeyError: 'sku' while enriching order {oid}",
        lambda oid: {"order_id": oid, "customer": f"cust-{oid % 97}", "items": []},
        21,
    ),
    (
        "payments.dlq", "payments", "commerce", "payment.capture", "rejected",
        "GatewayTimeout: upstream PSP returned 504 for txn {oid}",
        lambda oid: {"txn_id": f"txn_{oid}", "amount_paise": oid * 100 + 49, "method": "upi"},
        41,
    ),
    (
        "payments.dlq", "payments", "commerce", "payment.capture", "delivery_limit",
        "GatewayTimeout: upstream PSP returned 504 for txn {oid}",
        lambda oid: {"txn_id": f"txn_{oid}", "amount_paise": oid * 100 + 49, "method": "card"},
        9,
    ),
    (
        "notifications.dlq", "notifications", "comms", "email.send", "expired",
        "",  # TTL expiry has no consumer error - reason alone drives the group
        lambda oid: {"email_id": str(uuid.UUID(int=oid)), "template": "order_confirmation"},
        17,
    ),
]


class DemoAdapter:
    mode = "demo"

    def __init__(self) -> None:
        self._queues: dict[str, list[DeadMessage]] = {}
        self._rng = random.Random(_SEED)
        self._origin_of: dict[str, str] = {}
        self._seed()

    def _seed(self) -> None:
        now = datetime.now(timezone.utc)
        for dlq, origin, exchange, rk, reason, err_tpl, payload_fn, count in _SCENARIOS:
            self._origin_of[dlq] = origin
            bucket = self._queues.setdefault(dlq, [])
            for i in range(count):
                oid = 8000 + self._rng.randint(0, 1999)
                body = payload_fn(oid)
                headers: dict = {
                    "x-death": [{
                        "queue": origin, "reason": reason, "count": 1,
                        "exchange": exchange, "routing-keys": [rk],
                    }]
                }
                if err_tpl:
                    headers["x-exception"] = err_tpl.format(oid=oid)
                payload = json.dumps(body)
                fp, label = fingerprint(reason, origin, payload, headers)
                bucket.append(DeadMessage(
                    id=uuid.uuid4().hex[:16],
                    queue=dlq, payload=payload, headers=headers,
                    exchange=exchange, routing_key=rk,
                    reason=reason, origin_queue=origin,
                    death_count=1 + self._rng.randint(0, 2),
                    first_death_at=now - timedelta(minutes=self._rng.randint(2, 240)),
                    fingerprint=fp, fingerprint_label=label,
                ))

    async def list_dlqs(self) -> list[QueueInfo]:
        return [
            QueueInfo(name=q, message_count=len(msgs), origin_queue=self._origin_of.get(q))
            for q, msgs in sorted(self._queues.items())
        ]

    async def peek(self, queue: str, limit: int = 500) -> list[DeadMessage]:
        return list(self._queues.get(queue, []))[:limit]

    async def replay(self, message: DeadMessage) -> bool:
        bucket = self._queues.get(message.queue, [])
        try:
            bucket.remove(message)
        except ValueError:
            return False
        # ~85% of replays succeed; the rest hit the still-broken consumer and bounce back.
        if self._rng.random() < 0.85:
            return True
        message.death_count += 1
        bucket.append(message)
        return False

    async def close(self) -> None:
        return None
