# ADR 0003: Planning and reinference are swappable strategies

- **Status:** accepted
- **Date:** 2026-11-21

## Context

The center must plan before delegating and reason again after the evidence comes back. How it
does that should be able to change (smarter, cheaper, deterministic) without rewriting it.

## Decision

- `PlanningStrategy` and `ReinferenceStrategy` are ports. Defaults are model-driven
  (`ModelPlanning`, `ModelReinference`); deterministic alternatives ship too (`StaticPlanning`,
  `ThresholdReinference`).
- Strategies reach the model only through `CenterMind.think()`, which applies the center's own
  prompt, skills, RAG, read-only tools, policy, and events.
- Reinference returns `complete`, `refine` (with per-petal feedback), or `escalate`, bounded by
  `max_rounds`. Plans are validated (unknown petal, empty instruction, missing dependency,
  cycle) before running.
- The center **always** publishes a decision; failures in planning or reinference escalate
  with the reason instead of raising.

## Consequences

- The constitution's "never just concatenate" rule holds: even `ThresholdReinference` makes an
  explicit judgement on failures, risk, and confidence.
- Teams can start deterministic and adopt model planning gradually.
