# ADR 0001: Center = agent, petal = subagent, one capability kit

- **Status:** accepted
- **Date:** 2026-11-21

## Context

FOAA needs a clear definition of "agent" and "subagent" that stays flexible: the project is an
orchestrator, and users define their own agents. (Amended by ADR 0006: FOAA governs
harnesses; the native loop is one petal implementation, `ModelPetal`.)

## Decision

- The flower center (`Anther`) is the **agent**; a petal (`Petal`) is a **subagent**.
- Both receive the same optional **capability kit**: prompt, skills, MCP connections, RAG
  sources, and policy, either as **constructor parameters or setters**.
- The only structural difference: the **center calls and coordinates subagents**; a petal
  executes and returns its result. A petal never calls other subagents.
- **Skills are data** (`Skill`: name, description, instructions), not classes to subclass.
  Users store them anywhere and pass them in; `Skill.from_markdown()` reads `SKILL.md` files.

## Consequences

- One harness (`AgentHarness`) serves both roles, so governance and observability behave the
  same everywhere.
- Fitness functions enforce that petals never import the center and that both classes expose
  the same setters.
