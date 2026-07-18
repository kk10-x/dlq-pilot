"""Replay service: adapter-agnostic, rate-limited, dry-run-first."""
from __future__ import annotations

import asyncio
import time

from .brokers.base import BrokerAdapter
from .schemas import ReplayRequest, ReplayResult


async def run_replay(broker: BrokerAdapter, req: ReplayRequest) -> ReplayResult:
    started = time.monotonic()
    messages = await broker.peek(req.queue, limit=2000)
    if req.fingerprint:
        messages = [m for m in messages if m.fingerprint == req.fingerprint]
    matched = len(messages)
    selected = messages[: req.max_messages]

    replayed = 0
    bounced = 0
    if not req.dry_run:
        interval = 1.0 / req.rate_per_sec if req.rate_per_sec > 0 else 0.0
        for msg in selected:
            ok = await broker.replay(msg)
            if ok:
                replayed += 1
            else:
                bounced += 1
            if interval:
                await asyncio.sleep(interval)

    return ReplayResult(
        queue=req.queue,
        fingerprint=req.fingerprint,
        matched=matched,
        replayed=replayed,
        returned_to_dlq=bounced,
        dry_run=req.dry_run,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
