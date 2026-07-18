"""End-to-end API tests against demo mode (no broker required)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings, "audit_db_path", str(tmp_path / "audit.db"))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.anyio
async def test_health_reports_demo_mode(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["mode"] == "demo"


@pytest.mark.anyio
async def test_queues_and_groups(client):
    queues = (await client.get("/api/queues")).json()
    names = {q["name"] for q in queues}
    assert {"orders.dlq", "payments.dlq", "notifications.dlq"} <= names

    groups = (await client.get("/api/queues/orders.dlq/groups")).json()
    assert len(groups) == 2  # two distinct failure causes seeded
    assert groups[0]["count"] >= groups[1]["count"]
    assert all(g["fingerprint"] for g in groups)


@pytest.mark.anyio
async def test_messages_filtered_by_fingerprint(client):
    groups = (await client.get("/api/queues/payments.dlq/groups")).json()
    fp = groups[0]["fingerprint"]
    msgs = (await client.get("/api/queues/payments.dlq/messages", params={"fingerprint": fp})).json()
    assert len(msgs) == groups[0]["count"]
    assert all(m["fingerprint"] == fp for m in msgs)


@pytest.mark.anyio
async def test_dry_run_replay_changes_nothing_and_audits(client):
    before = (await client.get("/api/queues/orders.dlq/groups")).json()
    r = (await client.post("/api/replay", json={
        "queue": "orders.dlq", "dry_run": True, "max_messages": 10,
    })).json()
    assert r["dry_run"] is True and r["replayed"] == 0 and r["matched"] > 0
    after = (await client.get("/api/queues/orders.dlq/groups")).json()
    assert before == after
    audit = (await client.get("/api/audit")).json()
    assert audit and audit[0]["dry_run"] is True


@pytest.mark.anyio
async def test_real_replay_drains_group(client):
    groups = (await client.get("/api/queues/payments.dlq/groups")).json()
    fp, count = groups[0]["fingerprint"], groups[0]["count"]
    r = (await client.post("/api/replay", json={
        "queue": "payments.dlq", "fingerprint": fp, "dry_run": False,
        "max_messages": 1000, "rate_per_sec": 500,
    })).json()
    assert r["matched"] == count
    assert r["replayed"] + r["returned_to_dlq"] == count
    assert r["replayed"] > 0  # most succeed

    after = (await client.get("/api/queues/payments.dlq/groups")).json()
    remaining = next((g["count"] for g in after if g["fingerprint"] == fp), 0)
    assert remaining == r["returned_to_dlq"]


@pytest.mark.anyio
async def test_replay_validation(client):
    r = await client.post("/api/replay", json={"queue": "orders.dlq", "max_messages": 0})
    assert r.status_code == 400
