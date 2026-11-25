"""Shared primitives with no dependency on any other FOAA layer.

This is the lowest layer of the package. Everything else may import from it; it imports
nothing from FOAA (enforced by ``tests/architecture/test_layering.py``).
"""

from foaa.common.clock import utc_now
from foaa.common.errors import (
    FoaaError,
    InvalidPlanError,
    ModelOutputError,
)
from foaa.common.ids import new_id
from foaa.common.risk import RiskLevel, highest_risk

__all__ = [
    "FoaaError",
    "InvalidPlanError",
    "ModelOutputError",
    "RiskLevel",
    "highest_risk",
    "new_id",
    "utc_now",
]
