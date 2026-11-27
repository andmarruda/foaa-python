"""Test doubles for external harnesses and commands: simulate orchestrations with no runtime."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from foaa.common import RiskLevel
from foaa.flowers.common import Evidence, Risk
from foaa.flowers.petals import CommandOutcome, HarnessAction, HarnessOutcome, HarnessTask

Scripted = HarnessOutcome | BaseException | Callable[[HarnessTask], HarnessOutcome | Awaitable[Any]]


def outcome(
    conclusion: str,
    *,
    succeeded: bool = True,
    confidence: float | None = None,
    evidence: Iterable[tuple[str, str | None]] = (),
    risks: Iterable[tuple[str, RiskLevel]] = (),
    actions: Iterable[str | HarnessAction] = (),
    uncertainty: str | None = None,
) -> HarnessOutcome:
    """Build a :class:`HarnessOutcome` tersely. Plain strings in ``actions`` are tool targets."""
    return HarnessOutcome(
        conclusion=conclusion,
        succeeded=succeeded,
        confidence=confidence,
        evidence=tuple(Evidence(claim, source) for claim, source in evidence),
        risks=tuple(Risk(text, level) for text, level in risks),
        actions=tuple(a if isinstance(a, HarnessAction) else HarnessAction(a) for a in actions),
        uncertainty=uncertainty,
    )


class FakeHarness:
    """A :class:`~foaa.flowers.petals.HarnessPort` that answers from a script.

    Each script item is an outcome, an exception to raise, or a (sync or async) callable that
    receives the task. Every task received is recorded in :attr:`tasks`.
    """

    def __init__(self, *script: Scripted) -> None:
        self._script = list(script)
        self.tasks: list[HarnessTask] = []

    async def execute(self, task: HarnessTask) -> HarnessOutcome:
        self.tasks.append(task)
        if not self._script:
            raise AssertionError(f"FakeHarness for {task.petal!r} ran out of scripted outcomes")
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            produced = item(task)
            if inspect.isawaitable(produced):
                produced = await produced
            if not isinstance(produced, HarnessOutcome):
                raise AssertionError("scripted callable must produce a HarnessOutcome")
            return produced
        return item


def command_result(exit_code: int = 0, output: str = "") -> CommandOutcome:
    return CommandOutcome(exit_code=exit_code, output=output)


class FakeCommandRunner:
    """A :class:`~foaa.flowers.petals.CommandRunner` that replays scripted results."""

    def __init__(self, *results: CommandOutcome) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, ...]] = []

    async def run(self, command: Sequence[str]) -> CommandOutcome:
        self.calls.append(tuple(command))
        if not self._results:
            raise AssertionError(f"FakeCommandRunner ran out of results for {command!r}")
        return self._results.pop(0)
