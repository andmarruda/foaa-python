"""Run locally: OpenCode writes a React component, `npm run build` verifies it, FOAA governs.

    coder (OpenCode via `opencode run`)  ->  build (npm run build)  ->  repair loop if red

Setup (once):

    npm create vite@latest react-demo -- --template react-ts
    cd react-demo && npm install && cd ..
    uv run python examples/opencode_react_component.py ./react-demo

The center needs no model: planning and reinference are deterministic. The only AI is the
one OpenCode is configured with (`opencode auth login`, or pass --model provider/model).

Governance note: `opencode run` approves its own tool calls and does not report them back,
so FOAA cannot audit its actions post hoc. That is why the build petal exists: objective
evidence replaces trust (ADR 0006). Run it on a throwaway project or a git branch.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from foaa import (
    Anther,
    CommandPetal,
    HarnessOutcome,
    HarnessPetal,
    HarnessTask,
    InMemoryEventBus,
    Policy,
    RepairLoopReinference,
    StaticPlanning,
    Step,
    SubprocessRunner,
)

OBJECTIVE = (
    "Create src/components/Counter.tsx: a typed React component with a label prop, "
    "+ and - buttons and the current count. Render it in src/App.tsx. "
    "Keep it simple and make sure `npm run build` passes."
)


class OpenCodeHarness:
    """A HarnessPort over the OpenCode CLI (`opencode run "<prompt>"`)."""

    def __init__(self, cwd: Path, *, model: str | None = None, timeout: float = 900) -> None:
        self.cwd = cwd
        self.model = model
        self.timeout = timeout

    async def execute(self, task: HarnessTask) -> HarnessOutcome:
        command = ["opencode", "run"]
        if self.model:
            command += ["--model", self.model]
        command.append(_prompt(task))
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
            return HarnessOutcome(f"opencode timed out after {self.timeout}s", succeeded=False)
        text = stdout.decode(errors="replace").strip()
        return HarnessOutcome(
            conclusion=text[-3_000:] or "(no output)",
            succeeded=process.returncode == 0,
            uncertainty="OpenCode does not report its tool calls; verified by the build petal",
        )


def _prompt(task: HarnessTask) -> str:
    parts = [task.instruction]
    if task.objective and task.objective != task.instruction:
        parts.insert(0, f"Team objective: {task.objective}")
    if task.feedback:
        parts.append(f"Your previous attempt was rejected:\n{task.feedback}")
    if task.permissions.restricted:
        parts.append("Never touch: " + ", ".join(task.permissions.restricted))
    return "\n\n".join(parts)


async def main(project: Path, model: str | None) -> None:
    bus = InMemoryEventBus()
    center = Anther(
        "frontend",
        petals=[
            HarnessPetal(
                "coder",
                OpenCodeHarness(project, model=model),
                description="writes React code with OpenCode",
                policy=Policy.for_petal("coder", restricted={"*.env*", "node_modules/*"}),
            ),
            CommandPetal(
                "build",
                SubprocessRunner(cwd=str(project)),
                ["npm", "run", "build"],
                policy=Policy.for_petal("build", tools={"command/npm"}),
            ),
        ],
        planning=StaticPlanning(
            [Step("coder", OBJECTIVE), Step("build", "Build the app", after=("coder",))]
        ),
        reinference=RepairLoopReinference({"build": "coder"}),
        max_rounds=3,
        bus=bus,
    )

    decision = await center.handle(OBJECTIVE)

    for event in bus.history:
        print(f"  {event.event_type:32} {event.attributes.get('agent.name', '')}")
    print(f"\nstatus: {decision.status.value} after {decision.rounds} round(s)")
    if decision.escalation_reason:
        print(f"escalated: {decision.escalation_reason}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="path to a Vite React project")
    parser.add_argument("--model", help="OpenCode model, e.g. google/gemini-2.5-pro")
    args = parser.parse_args()
    asyncio.run(main(args.project.resolve(), args.model))
