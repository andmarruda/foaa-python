# ADR 0006: FOAA governs harnesses; it is not one

- **Status:** accepted
- **Date:** 2026-11-26
- **Amends:** ADR 0001 (the native loop becomes one petal implementation, not the definition)

## Context

The book defines FOAA as a philosophy of *orchestration*: flowers define roles, limits, and
evidence; bees, environment, and observers coordinate and govern. The first implementation,
however, made the petal a concrete class that runs FOAA's own model loop, and the center
depended on that class. To join a flower, an agent had to be rewritten on FOAA's loop.

That made FOAA a harness, competing with runtimes that already do execution well (Claude
Code, the Agent SDK, Codex, LangGraph), and it blocked the long-term goal: orchestrating an
agentic software factory where teams of agents from different vendors work under the same
rules and the same light.

## Decision

- The center depends on a **`PetalPort`** (`name`, `description`, `run(...) -> PetalResult`),
  never on an implementation. A fitness function enforces it.
- Three implementations ship:
  - `ModelPetal` (alias `Petal`, kept for compatibility): the native reference loop, for
    users who have a model and no harness.
  - `HarnessPetal`: delegates execution to any **`HarnessPort`** (`execute(HarnessTask) ->
    HarnessOutcome`). Adapters for real harnesses ship as optional extras.
  - `CommandPetal`: turns a command (tests, lint, build) into objective evidence, through a
    `CommandRunner` port.
- **Governance in two moments**, because FOAA cannot intercept a harness' own tool calls:
  - *before*: the petal policy is translated into `HarnessPermissions` that the adapter must
    apply (allowlist, sandbox, approval mode);
  - *after*: every action the harness reports is audited against the same policy. Violations
    are published as `governance.action.denied` with `audit = "post_hoc"` and become HIGH
    risks, so the center escalates instead of trusting the result.
- Commands are governed like tools (`command/<program>`), deny-by-default, checked before they
  run (`audit = "pre_flight"`).
- A center whose strategies are deterministic needs **no model**.
- `RepairLoopReinference` ships as the deterministic verify-and-repair loop: a failing
  verifier sends its output to the petal that can fix it, and the verifiers run again.

## Consequences

- Any runtime joins a flower with one adapter method; the flower keeps its role, policy,
  evidence contract, and events regardless of who executes.
- Post-hoc audit is weaker than interception. Adapters must be honest about which actions
  they report; an adapter that cannot report actions must say so in its documentation, and
  the flower should rely on objective verifiers (`CommandPetal`) for those petals.
- Orchestrations can be simulated end to end with `foaa.testing.FakeHarness` and
  `FakeCommandRunner`, which is how `tests/orchestration/` grows from one petal to a mini
  software factory.
