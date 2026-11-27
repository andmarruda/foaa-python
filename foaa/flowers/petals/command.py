"""CommandPetal: objective evidence from a command (tests, lint, type check, build).

In a software factory, "the agent says it works" is weak evidence; "pytest exited 0" is
strong evidence. A command petal turns a command's exit code and output into a
:class:`PetalResult` the center can reason over.

Commands are governed like tools: the target ``"command/<program>"`` must be allowed by the
petal's policy (deny-by-default), otherwise the command never runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from foaa.common import RiskLevel
from foaa.edd.events import types
from foaa.flowers.common import Assignment, Evidence, PetalResult, Risk, RunContext, TaskStatus
from foaa.governance import Policy
from foaa.governance.policy import Action, ActionKind

OUTPUT_TAIL = 2_000


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    exit_code: int
    output: str = ""


@runtime_checkable
class CommandRunner(Protocol):
    async def run(self, command: Sequence[str]) -> CommandOutcome: ...


class SubprocessRunner:
    """Runs a command locally with :mod:`asyncio` (stdout and stderr merged)."""

    def __init__(self, *, cwd: str | None = None, timeout: float | None = 600) -> None:
        self.cwd = cwd
        self.timeout = timeout

    async def run(self, command: Sequence[str]) -> CommandOutcome:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            return CommandOutcome(exit_code=-1, output=f"timed out after {self.timeout}s")
        return CommandOutcome(
            exit_code=process.returncode if process.returncode is not None else -1,
            output=stdout.decode(errors="replace"),
        )


class CommandPetal:
    """A petal that runs one command and reports its result as evidence."""

    role = "petal"

    def __init__(
        self,
        name: str,
        runner: CommandRunner,
        command: Sequence[str],
        *,
        description: str = "",
        policy: Policy | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("a petal needs a name")
        if not command:
            raise ValueError("a command petal needs a command")
        self.name = name
        self.description = description or f"runs `{' '.join(command)}`"
        self.runner = runner
        self.command = tuple(command)
        self.policy = policy or Policy.for_petal(f"{name}-default")

    def __repr__(self) -> str:
        return f"CommandPetal(name={self.name!r}, command={self.command!r})"

    @property
    def target(self) -> str:
        return f"command/{self.command[0]}"

    async def run(
        self,
        assignment: Assignment,
        ctx: RunContext,
        *,
        objective: str | None = None,
        upstream: Sequence[PetalResult] = (),
    ) -> PetalResult:
        attributes = {"agent.role": self.role, "agent.name": self.name}
        await ctx.emit(
            types.TASK_STARTED,
            {"task_id": assignment.id, "petal": self.name, "instruction": assignment.instruction},
            attributes=attributes,
        )
        shown = " ".join(self.command)
        decision = self.policy.evaluate(Action(ActionKind.TOOL, self.target))
        if not decision.allowed or decision.requires_review:
            reason = decision.reason if not decision.allowed else f"{self.target} requires review"
            await ctx.emit(
                types.ACTION_DENIED,
                {"action": f"tool:{self.target}", "reason": reason, "audit": "pre_flight"},
                attributes=attributes,
                risk_level=RiskLevel.MEDIUM,
            )
            result = _failed(assignment, self.name, f"`{shown}` was not run: {reason}")
            return await self._finish(ctx, result, attributes)

        try:
            done = await self.runner.run(self.command)
        except Exception as error:
            result = _failed(assignment, self.name, f"`{shown}` could not run: {error}")
            return await self._finish(ctx, result, attributes)

        tail = done.output[-OUTPUT_TAIL:].strip()
        evidence = (Evidence(f"`{shown}` exited {done.exit_code}", f"command:{self.name}"),)
        if done.exit_code == 0:
            result = PetalResult(
                task_id=assignment.id,
                petal=self.name,
                status=TaskStatus.COMPLETED,
                conclusion=f"`{shown}` passed" + (f"\n{tail}" if tail else ""),
                evidence=evidence,
                confidence=1.0,
                actions=(self.target,),
            )
        else:
            result = PetalResult(
                task_id=assignment.id,
                petal=self.name,
                status=TaskStatus.FAILED,
                conclusion=f"`{shown}` failed (exit {done.exit_code})"
                + (f"\n{tail}" if tail else ""),
                evidence=evidence,
                risks=(Risk(f"`{shown}` failed", RiskLevel.MEDIUM),),
                confidence=1.0,
                actions=(self.target,),
            )
        return await self._finish(ctx, result, attributes)

    async def _finish(
        self, ctx: RunContext, result: PetalResult, attributes: dict[str, str]
    ) -> PetalResult:
        await ctx.emit(
            types.TASK_COMPLETED if result.succeeded else types.TASK_FAILED,
            {
                "task_id": result.task_id,
                "petal": result.petal,
                "status": result.status.value,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence),
                "risk_count": len(result.risks),
                "actions": list(result.actions),
                "executor": "command",
            },
            attributes=attributes,
            risk_level=result.risk_level,
        )
        return result


def _failed(assignment: Assignment, petal: str, reason: str) -> PetalResult:
    return PetalResult(
        task_id=assignment.id,
        petal=petal,
        status=TaskStatus.FAILED,
        conclusion=reason,
        risks=(Risk(reason, RiskLevel.MEDIUM),),
        uncertainty=reason,
    )
