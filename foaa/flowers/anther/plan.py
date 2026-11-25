"""Plan validation and execution order (pure functions, easy to test and to evolve)."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from foaa.common import InvalidPlanError
from foaa.flowers.common import Assignment


def validate_plan(
    assignments: Sequence[Assignment],
    petals: Collection[str],
    *,
    known_results: Collection[str] = (),
) -> list[Assignment]:
    """Reject plans that cannot run: empty, unknown petal, duplicate id, missing dependency,
    or a dependency cycle. Dependencies may point to results of earlier rounds."""
    if not assignments:
        raise InvalidPlanError("the plan has no assignments")

    ids = [assignment.id for assignment in assignments]
    if len(set(ids)) != len(ids):
        raise InvalidPlanError("the plan repeats assignment ids")

    for assignment in assignments:
        if assignment.petal not in petals:
            raise InvalidPlanError(
                f"assignment {assignment.id} targets unknown petal {assignment.petal!r}; "
                f"known petals: {sorted(petals)}"
            )
        if not assignment.instruction.strip():
            raise InvalidPlanError(f"assignment {assignment.id} has an empty instruction")
        for dependency in assignment.depends_on:
            if dependency not in ids and dependency not in known_results:
                raise InvalidPlanError(
                    f"assignment {assignment.id} depends on unknown id {dependency!r}"
                )

    execution_waves(assignments, satisfied=known_results)  # raises on cycles
    return list(assignments)


def execution_waves(
    assignments: Sequence[Assignment],
    *,
    satisfied: Collection[str] = (),
) -> list[list[Assignment]]:
    """Group assignments into waves; everything in one wave can run in parallel."""
    done = set(satisfied)
    pending = list(assignments)
    waves: list[list[Assignment]] = []
    while pending:
        wave = [a for a in pending if all(dep in done for dep in a.depends_on)]
        if not wave:
            raise InvalidPlanError(
                "the plan has a dependency cycle between: "
                + ", ".join(sorted(a.id for a in pending))
            )
        waves.append(wave)
        done.update(a.id for a in wave)
        pending = [a for a in pending if a.id not in done]
    return waves
