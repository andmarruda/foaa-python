from __future__ import annotations

import fnmatch
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from foaa.edd.events import EventEnvelope
from foaa.edd.listeners import Listener

logger = logging.getLogger("foaa.edd")


@runtime_checkable
class EventBus(Protocol):
    """Transport port for events.

    The default is :class:`InMemoryEventBus`. Distributed brokers (Redis, Kafka, NATS...) plug
    in by implementing this protocol, with no change to flower code.
    """

    async def publish(self, event: EventEnvelope) -> None: ...

    def subscribe(self, pattern: str, listener: Listener) -> None: ...


@dataclass(frozen=True, slots=True)
class ListenerFailure:
    """A listener raised while handling an event. Kept visible instead of swallowed."""

    event: EventEnvelope
    pattern: str
    error: BaseException


class InMemoryEventBus:
    """Single-process event bus.

    * ``pattern`` uses shell-style wildcards: ``"petal.*"``, ``"*"``.
    * Delivery is de-duplicated by ``event_id`` (at-most-once per bus instance).
    * A failing listener never breaks the publisher: the failure is logged and recorded in
      :attr:`failures`.
    * Every published event is kept in :attr:`history` (bounded by ``history_limit``), which
      makes the bus a simple source of light for tests and local debugging.
    """

    def __init__(self, *, history_limit: int | None = 10_000) -> None:
        self._subscriptions: list[tuple[str, Listener]] = []
        self._seen: set[str] = set()
        self._history: list[EventEnvelope] = []
        self._history_limit = history_limit
        self.failures: list[ListenerFailure] = []

    def subscribe(self, pattern: str, listener: Listener) -> None:
        self._subscriptions.append((pattern, listener))

    async def publish(self, event: EventEnvelope) -> None:
        if event.event_id in self._seen:
            return
        self._seen.add(event.event_id)
        self._history.append(event)
        if self._history_limit is not None and len(self._history) > self._history_limit:
            del self._history[0]

        for pattern, listener in list(self._subscriptions):
            if not fnmatch.fnmatchcase(event.event_type, pattern):
                continue
            try:
                await listener(event)
            except Exception as error:
                logger.exception("listener failed for %s", event.event_type)
                self.failures.append(ListenerFailure(event, pattern, error))

    @property
    def history(self) -> Sequence[EventEnvelope]:
        return tuple(self._history)

    def events(
        self, pattern: str = "*", *, correlation_id: str | None = None
    ) -> list[EventEnvelope]:
        """Return recorded events matching a type pattern and, optionally, a goal."""
        return [
            event
            for event in self._history
            if fnmatch.fnmatchcase(event.event_type, pattern)
            and (correlation_id is None or event.correlation_id == correlation_id)
        ]


class NullEventBus:
    """A bus that drops everything. Useful only where observability is provided elsewhere."""

    async def publish(self, event: EventEnvelope) -> None:
        return None

    def subscribe(self, pattern: str, listener: Listener) -> None:
        return None
