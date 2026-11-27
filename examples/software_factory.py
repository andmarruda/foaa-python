"""A mini software factory, simulated: no model, no network, no real harness.

spec (harness A) -> code (harness B) -> tests + lint (commands) -> security review (read-only)
The first test run fails; the center sends the failure back to the coder and verifies again.

Swap FakeHarness for a real HarnessPort adapter (Claude Code, Codex...) and FakeCommandRunner
for SubprocessRunner, and the flower stays exactly the same.

    uv run python examples/software_factory.py
"""

from __future__ import annotations

import asyncio

from foaa import (
    Anther,
    CommandPetal,
    HarnessPetal,
    InMemoryEventBus,
    Policy,
    RepairLoopReinference,
    StaticPlanning,
    Step,
)
from foaa.testing import FakeCommandRunner, FakeHarness, command_result, outcome


async def main() -> None:
    bus = InMemoryEventBus()
    center = Anther(
        "engineering",
        petals=[
            HarnessPetal("spec", FakeHarness(outcome("spec: yearly plan, 2 months free"))),
            HarnessPetal(
                "coder",
                FakeHarness(
                    outcome("billing v1", actions=["repo/write_file"]),
                    outcome("billing v2: fixed rounding", actions=["repo/write_file"]),
                ),
                policy=Policy.for_petal("coder", tools={"repo/*"}, restricted={"repo/secrets*"}),
            ),
            CommandPetal(
                "tests",
                FakeCommandRunner(
                    command_result(1, "FAILED test_yearly_price - 1199 != 1200"),
                    command_result(0, "42 passed"),
                ),
                ["pytest", "-q"],
                policy=Policy.for_petal("tests", tools={"command/pytest"}),
            ),
            HarnessPetal(
                "security",
                FakeHarness(outcome("no secrets touched", confidence=0.9)),
                policy=Policy.for_petal("security", tools={"repo/read_*"}),
            ),
        ],
        planning=StaticPlanning(
            [
                Step("spec", "Specify: {objective}"),
                Step("coder", "Implement the spec", after=("spec",)),
                Step("tests", "Run the test suite", after=("coder",)),
                Step("security", "Review the change", after=("coder",)),
            ]
        ),
        reinference=RepairLoopReinference({"tests": "coder"}),
        bus=bus,
    )

    decision = await center.handle("Launch yearly subscription plans")

    print(f"status: {decision.status.value} after {decision.rounds} round(s)")
    print(decision.summary)
    print("\ntrace:")
    for event in bus.history:
        print(f"  {event.event_type:32} {event.attributes.get('agent.name', '')}")


if __name__ == "__main__":
    asyncio.run(main())
