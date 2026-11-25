from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from foaa.common import RiskLevel
from foaa.edd import EventBus, EventEnvelope, InMemoryEventBus
from foaa.governance import DenyAllReviewGate, ReviewGate


@dataclass(frozen=True)
class RunContext:
    """Everything a run needs to stay traceable and governed.

    The flower (center) creates one per objective and passes it down to its petals, so every
    event from every petal shares the same ``flower_id`` and ``correlation_id``.
    """

    flower_id: str
    correlation_id: str
    bus: EventBus = field(default_factory=InMemoryEventBus)
    review_gate: ReviewGate = field(default_factory=DenyAllReviewGate)
    causation_id: str | None = None

    def with_cause(self, causation_id: str | None) -> RunContext:
        return RunContext(
            flower_id=self.flower_id,
            correlation_id=self.correlation_id,
            bus=self.bus,
            review_gate=self.review_gate,
            causation_id=causation_id,
        )

    async def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        attributes: Mapping[str, str],
        risk_level: RiskLevel = RiskLevel.NONE,
        requires_review: bool = False,
        event_version: int = 1,
    ) -> EventEnvelope:
        event = EventEnvelope(
            event_type=event_type,
            event_version=event_version,
            flower_id=self.flower_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            payload=payload,
            attributes={"flower.id": self.flower_id, **attributes},
            risk_level=risk_level,
            requires_review=requires_review,
        )
        await self.bus.publish(event)
        return event
