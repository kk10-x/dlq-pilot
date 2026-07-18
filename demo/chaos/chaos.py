"""Chaos harness: declares queues with DLX routing, produces realistic traffic,
and consumes it with deliberately broken handlers so the DLQs fill up."""
import asyncio
import json
import os
import random

import aio_pika

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

TOPOLOGY = [
    # (work queue, exchange, routing key)
    ("orders", "commerce", "order.created"),
    ("payments", "commerce", "payment.capture"),
    ("notifications", "comms", "email.send"),
]


async def declare(channel: aio_pika.abc.AbstractChannel) -> None:
    dlx = await channel.declare_exchange("dlx", aio_pika.ExchangeType.DIRECT, durable=True)
    for queue, exchange_name, rk in TOPOLOGY:
        exchange = await channel.declare_exchange(exchange_name, aio_pika.ExchangeType.TOPIC, durable=True)
        dlq = await channel.declare_queue(f"{queue}.dlq", durable=True)
        await dlq.bind(dlx, routing_key=queue)
        q = await channel.declare_queue(
            queue, durable=True,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": queue,
                "x-message-ttl": 60_000 if queue == "notifications" else 3_600_000,
            },
        )
        await q.bind(exchange, routing_key=rk)


async def produce(channel: aio_pika.abc.AbstractChannel) -> None:
    rng = random.Random()
    while True:
        kind = rng.choice(TOPOLOGY)
        queue, exchange_name, rk = kind
        oid = rng.randint(8000, 9999)
        if queue == "orders":
            body = {"order_id": oid, "customer": f"cust-{oid % 97}", "currency": "INR"}
            if rng.random() < 0.5:
                body.pop("currency")  # will fail validation downstream
        elif queue == "payments":
            body = {"txn_id": f"txn_{oid}", "amount_paise": oid * 100 + 49, "method": rng.choice(["upi", "card"])}
        else:
            body = {"email_id": str(oid), "template": "order_confirmation"}
        exchange = await channel.get_exchange(exchange_name)
        await exchange.publish(aio_pika.Message(json.dumps(body).encode()), routing_key=rk)
        await asyncio.sleep(0.4)


async def consume(channel: aio_pika.abc.AbstractChannel) -> None:
    """Broken on purpose: orders without currency are rejected; the payment
    'gateway' times out 60% of the time; notifications are simply never consumed,
    so their TTL expires them into the DLQ."""
    rng = random.Random()

    async def handle_order(msg: aio_pika.abc.AbstractIncomingMessage) -> None:
        body = json.loads(msg.body)
        if "currency" not in body:
            await msg.reject(requeue=False)  # -> orders.dlq (reason: rejected)
        else:
            await msg.ack()

    async def handle_payment(msg: aio_pika.abc.AbstractIncomingMessage) -> None:
        if rng.random() < 0.6:
            await msg.reject(requeue=False)  # -> payments.dlq (reason: rejected)
        else:
            await msg.ack()

    orders = await channel.get_queue("orders")
    payments = await channel.get_queue("payments")
    await orders.consume(handle_order)
    await payments.consume(handle_payment)


async def main() -> None:
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        channel = await conn.channel()
        await declare(channel)
        await consume(channel)
        await produce(channel)  # runs forever


if __name__ == "__main__":
    asyncio.run(main())
