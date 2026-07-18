"""dlq-pilot API: triage and replay dead-lettered messages.

Run:  uvicorn app.main:app --port 8000        (demo mode, zero setup)
      RABBITMQ_URL=amqp://... uvicorn ...     (real broker)
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .audit import AuditLog
from .brokers.demo import DemoAdapter
from .config import Settings
from .replay import run_replay
from .schemas import DeadMessage, FingerprintGroup, ReplayRequest, ReplayResult

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.mode == "rabbitmq":
        from .brokers.rabbitmq import RabbitMQAdapter  # deferred: aio_pika only needed here
        app.state.broker = RabbitMQAdapter(settings)
    else:
        app.state.broker = DemoAdapter()
    app.state.audit = AuditLog(settings.audit_db_path)
    yield
    await app.state.broker.close()
    app.state.audit.close()


app = FastAPI(title="dlq-pilot", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "mode": app.state.broker.mode}


@app.get("/api/queues")
async def queues() -> list:
    return await app.state.broker.list_dlqs()


@app.get("/api/queues/{queue}/groups")
async def groups(queue: str) -> list[FingerprintGroup]:
    messages: list[DeadMessage] = await app.state.broker.peek(queue)
    buckets: dict[str, list[DeadMessage]] = defaultdict(list)
    for m in messages:
        buckets[m.fingerprint].append(m)
    out = []
    for fp, msgs in buckets.items():
        deaths = [m.first_death_at for m in msgs if m.first_death_at]
        out.append(FingerprintGroup(
            fingerprint=fp,
            label=msgs[0].fingerprint_label,
            reason=msgs[0].reason,
            origin_queue=msgs[0].origin_queue,
            count=len(msgs),
            sample_payload=msgs[0].payload,
            first_seen=min(deaths) if deaths else None,
            last_seen=max(deaths) if deaths else None,
        ))
    return sorted(out, key=lambda g: -g.count)


@app.get("/api/queues/{queue}/messages")
async def messages(queue: str, fingerprint: str | None = None, limit: int = 100) -> list[DeadMessage]:
    msgs: list[DeadMessage] = await app.state.broker.peek(queue)
    if fingerprint:
        msgs = [m for m in msgs if m.fingerprint == fingerprint]
    return msgs[:limit]


@app.post("/api/replay")
async def replay(req: ReplayRequest) -> ReplayResult:
    if req.max_messages < 1 or req.max_messages > 1000:
        raise HTTPException(400, "max_messages must be between 1 and 1000")
    if req.rate_per_sec <= 0 or req.rate_per_sec > 500:
        raise HTTPException(400, "rate_per_sec must be between 0 and 500")
    result = await run_replay(app.state.broker, req)
    app.state.audit.record(result)
    return result


@app.get("/api/audit")
async def audit() -> list:
    return app.state.audit.recent()


# Serve the built frontend (single-port deployment). API routes above take priority.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
