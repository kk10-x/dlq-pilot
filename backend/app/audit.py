"""SQLite audit log: every replay (including dry runs) leaves a record."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from .schemas import AuditEntry, ReplayResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    queue TEXT NOT NULL,
    fingerprint TEXT,
    matched INTEGER NOT NULL,
    replayed INTEGER NOT NULL,
    dry_run INTEGER NOT NULL
);
"""


class AuditLog:
    def __init__(self, path: str) -> None:
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def record(self, result: ReplayResult) -> None:
        self._conn.execute(
            "INSERT INTO audit (ts, action, queue, fingerprint, matched, replayed, dry_run) VALUES (?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "replay",
                result.queue,
                result.fingerprint,
                result.matched,
                result.replayed,
                int(result.dry_run),
            ),
        )
        self._conn.commit()

    def recent(self, limit: int = 100) -> list[AuditEntry]:
        rows = self._conn.execute(
            "SELECT ts, action, queue, fingerprint, matched, replayed, dry_run FROM audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            AuditEntry(
                ts=datetime.fromisoformat(r[0]), action=r[1], queue=r[2],
                fingerprint=r[3], matched=r[4], replayed=r[5], dry_run=bool(r[6]),
            )
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
