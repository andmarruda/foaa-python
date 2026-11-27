"""The petal port: what a center needs from any subagent (ADR 0006).

A center never cares *how* a petal executes. It may be FOAA's native model loop
(:class:`~foaa.flowers.petals.ModelPetal`), an external harness such as Claude Code or Codex
(:class:`~foaa.flowers.petals.HarnessPetal`), or a plain command such as ``pytest``
(:class:`~foaa.flowers.petals.CommandPetal`). The flower defines the role; execution belongs
to whatever runtime fits.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from foaa.flowers.common import Assignment, PetalResult, RunContext


@runtime_checkable
class PetalPort(Protocol):
    """A subagent: one bounded specialty that returns evidence, never raises for its work."""

    name: str
    description: str

    async def run(
        self,
        assignment: Assignment,
        ctx: RunContext,
        *,
        objective: str | None = None,
        upstream: Sequence[PetalResult] = (),
    ) -> PetalResult: ...
