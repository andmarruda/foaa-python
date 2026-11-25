from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class RiskLevel(StrEnum):
    """How much attention a result, action, or event deserves."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        return _WEIGHTS[self]

    @classmethod
    def parse(cls, value: object, default: RiskLevel | None = None) -> RiskLevel:
        """Parse loose model output (``"High"``, ``" medium "``) into a level."""
        if isinstance(value, RiskLevel):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                pass
        return default if default is not None else cls.MEDIUM


_WEIGHTS = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


def highest_risk(levels: Iterable[RiskLevel]) -> RiskLevel:
    """Return the most severe level, or ``NONE`` when there is nothing to compare."""
    return max(levels, key=lambda level: level.weight, default=RiskLevel.NONE)
