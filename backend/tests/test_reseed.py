"""Demo re-seed: the periodic refresh that keeps the public sandbox populated."""
import pytest

from app.brokers.demo import DemoAdapter


@pytest.mark.anyio
async def test_reseed_restores_drained_queues():
    broker = DemoAdapter()
    before = {q.name: q.message_count for q in await broker.list_dlqs()}

    # Drain every message from every queue, mimicking visitors replaying the demo.
    for name in list(before):
        for msg in await broker.peek(name, limit=10_000):
            await broker.replay(msg)
    drained = {q.name: q.message_count for q in await broker.list_dlqs()}
    assert sum(drained.values()) < sum(before.values())

    broker.reseed()
    after = {q.name: q.message_count for q in await broker.list_dlqs()}
    assert after == before  # deterministic seed -> identical counts restored


@pytest.mark.anyio
async def test_reseed_is_deterministic():
    a, b = DemoAdapter(), DemoAdapter()
    b.reseed()  # a fresh adapter and a re-seeded one must be identical
    a_msgs = [m.fingerprint for m in await a.peek("orders.dlq", limit=10_000)]
    b_msgs = [m.fingerprint for m in await b.peek("orders.dlq", limit=10_000)]
    assert a_msgs == b_msgs
