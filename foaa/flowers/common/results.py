"""The data that flows inside a flower: objectives, assignments, petal results, decisions.

Every structure carries a ``schema_version`` so it can evolve without silently breaking
consumers (evolutionary architecture: versioned contracts).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from foaa.common import RiskLevel, highest_risk, new_id

RESULTS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Objective:
    """A goal handed to a flower, by a person, a bee, or another system."""

    description: str
    constraints: tuple[str, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("goal"))
    correlation_id: str | None = None
    causation_id: str | None = None

    @property
    def trace_id(self) -> str:
        """The id that ties every event of this objective together."""
        return self.correlation_id or self.id


@dataclass(frozen=True, slots=True)
class Assignment:
    """One piece of work the center delegates to one petal."""

    petal: str
    instruction: str
    depends_on: tuple[str, ...] = ()
    feedback: str | None = None
    id: str = field(default_factory=lambda: new_id("task"))


@dataclass(frozen=True, slots=True)
class Evidence:
    claim: str
    source: str | None = None


@dataclass(frozen=True, slots=True)
class Risk:
    description: str
    level: RiskLevel = RiskLevel.MEDIUM


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PetalResult:
    """What a petal returns: more than an answer (Constitution, Principle II).

    The conclusion comes with the evidence behind it, the sources consulted, the risks found,
    and an honest statement of uncertainty.
    """

    task_id: str
    petal: str
    status: TaskStatus
    conclusion: str
    evidence: tuple[Evidence, ...] = ()
    context_sources: tuple[str, ...] = ()
    risks: tuple[Risk, ...] = ()
    uncertainty: str | None = None
    confidence: float | None = None
    actions: tuple[str, ...] = ()
    schema_version: int = RESULTS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    @property
    def risk_level(self) -> RiskLevel:
        return highest_risk(risk.level for risk in self.risks)

    @property
    def succeeded(self) -> bool:
        return self.status is TaskStatus.COMPLETED


class DecisionStatus(StrEnum):
    COMPLETED = "completed"
    ESCALATED = "escalated"


@dataclass(frozen=True, slots=True)
class FlowerDecision:
    """The single, governed outcome that leaves the flower."""

    objective_id: str
    flower_id: str
    status: DecisionStatus
    summary: str
    results: tuple[PetalResult, ...] = ()
    risks: tuple[Risk, ...] = ()
    confidence: float | None = None
    rounds: int = 0
    escalation_reason: str | None = None
    schema_version: int = RESULTS_SCHEMA_VERSION

    @property
    def risk_level(self) -> RiskLevel:
        return highest_risk(
            [risk.level for risk in self.risks] + [result.risk_level for result in self.results]
        )

    @property
    def requires_review(self) -> bool:
        return self.status is DecisionStatus.ESCALATED or self.risk_level.weight >= 3
