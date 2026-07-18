"""Runtime configuration. Demo mode is the default: if no RABBITMQ_URL is set,
the app runs against the in-process demo broker so it works with zero setup."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_AUDIT_DB = str(Path(__file__).resolve().parents[2] / "data" / "audit.db")


@dataclass
class Settings:
    rabbitmq_url: str = field(default_factory=lambda: os.getenv("RABBITMQ_URL", ""))
    rabbitmq_mgmt_url: str = field(default_factory=lambda: os.getenv("RABBITMQ_MGMT_URL", "http://localhost:15672"))
    rabbitmq_user: str = field(default_factory=lambda: os.getenv("RABBITMQ_USER", "guest"))
    rabbitmq_password: str = field(default_factory=lambda: os.getenv("RABBITMQ_PASSWORD", "guest"))
    # Which queues count as DLQs (regex against the queue name).
    dlq_pattern: str = field(default_factory=lambda: os.getenv("DLQ_PATTERN", r"(\.dlq$|\.dlx$|dead)"))
    audit_db_path: str = field(default_factory=lambda: os.getenv("AUDIT_DB", _DEFAULT_AUDIT_DB))

    @property
    def mode(self) -> str:
        return "rabbitmq" if self.rabbitmq_url else "demo"
