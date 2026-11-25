from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any

from foaa.common import RiskLevel, new_id, utc_now

#: Version of the envelope layout itself (not of an individual event type).
ENVELOPE_SCHEMA_VERSION = 1


def _freeze(data: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(data or {}))


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """The contract every FOAA event travels in (Constitution, Principle V).

    ``event_type`` describes a meaningful outcome (``"petal.task.completed"``), not an internal
    step. ``event_version`` is the version of that event type's payload and MUST be bumped
    when the payload changes in a way that breaks consumers.

    ``attributes`` carries OpenTelemetry-style origin tags (``"agent.role"``, ``"agent.name"``),
    so observers can slice signals by flower, role, goal, and so on.
    """

    event_type: str
    flower_id: str
    correlation_id: str
    event_version: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, str] = field(default_factory=dict)
    causation_id: str | None = None
    risk_level: RiskLevel = RiskLevel.NONE
    requires_review: bool = False
    event_id: str = field(default_factory=lambda: new_id("evt"))
    occurred_at: datetime = field(default_factory=utc_now)
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_type or "." not in self.event_type:
            raise ValueError(
                f"event_type must be a dotted, meaningful name, got {self.event_type!r}"
            )
        if self.event_version < 1:
            raise ValueError("event_version must be >= 1")
        if not self.flower_id:
            raise ValueError("flower_id is required: every signal must keep its origin")
        if not self.correlation_id:
            raise ValueError("correlation_id is required: every signal must belong to a goal")
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "attributes", _freeze(self.attributes))

    def caused(self, event_type: str, **changes: Any) -> EventEnvelope:
        """Build a follow-up event in the same goal, caused by this one."""
        return replace(
            self,
            event_type=event_type,
            causation_id=self.event_id,
            event_id=new_id("evt"),
            occurred_at=utc_now(),
            **changes,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain JSON-compatible data (for brokers, logs, exporters)."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at.isoformat(),
            "flower_id": self.flower_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "risk_level": self.risk_level.value,
            "requires_review": self.requires_review,
            "attributes": dict(self.attributes),
            "payload": dict(self.payload),
        }
