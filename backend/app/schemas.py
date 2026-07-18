"""Pydantic schemas shared by the API layer and broker adapters."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class QueueInfo(BaseModel):
    name: str
    message_count: int
    origin_queue: str | None = None  # queue that dead-letters into this DLQ, if known


class DeadMessage(BaseModel):
    id: str
    queue: str
    payload: str
    headers: dict
    exchange: str
    routing_key: str
    reason: str  # rejected | expired | maxlen | delivery_limit | unknown
    origin_queue: str
    death_count: int = 1
    first_death_at: datetime | None = None
    fingerprint: str = ""
    fingerprint_label: str = ""


class FingerprintGroup(BaseModel):
    fingerprint: str
    label: str
    reason: str
    origin_queue: str
    count: int
    sample_payload: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class ReplayRequest(BaseModel):
    queue: str
    fingerprint: str | None = None  # None = whole queue
    max_messages: int = 50
    rate_per_sec: float = 25.0
    dry_run: bool = True


class ReplayResult(BaseModel):
    queue: str
    fingerprint: str | None
    matched: int
    replayed: int
    returned_to_dlq: int
    dry_run: bool
    duration_ms: int


class AuditEntry(BaseModel):
    ts: datetime
    action: str
    queue: str
    fingerprint: str | None
    matched: int
    replayed: int
    dry_run: bool
