"""Broker adapter protocol. The dashboard talks only to this interface, so demo mode
and a real RabbitMQ broker are interchangeable at runtime."""
from __future__ import annotations

from typing import Protocol

from ..schemas import DeadMessage, QueueInfo


class BrokerAdapter(Protocol):
    mode: str

    async def list_dlqs(self) -> list[QueueInfo]:
        """All dead-letter queues with message counts."""
        ...

    async def peek(self, queue: str, limit: int = 500) -> list[DeadMessage]:
        """Read messages without removing them from the queue."""
        ...

    async def replay(self, message: DeadMessage) -> bool:
        """Republish one message to its origin (exchange/routing key) and remove it
        from the DLQ. Returns True if the replayed message was accepted downstream,
        False if it dead-lettered again (at-least-once semantics: a replay can fail)."""
        ...

    async def close(self) -> None:
        ...
