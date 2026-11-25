# ADR 0004: Deny-by-default governance and events for every meaningful outcome

- **Status:** accepted
- **Date:** 2026-11-21

## Context

Autonomy must stay bounded and visible (Constitution, Principles II, III, V).

## Decision

- Every skill, RAG source, and tool use passes through `Governor` + `Policy`, deny-by-default,
  with shell-style patterns and a `restricted` list that always wins.
- Tools in `review_tools` wait for a `ReviewGate` (the gardener); the default gate denies.
- Tools the policy would deny are hidden from the model; every call is authorized again.
- Every meaningful outcome is an `EventEnvelope` on the `EventBus`, carrying `flower.id`,
  `agent.role`, `agent.name`, `correlation_id`, and `causation_id`. Tool argument **values** are
  never published.
- The default `InMemoryEventBus` de-duplicates by `event_id`, records history, and isolates
  failing listeners.

## Consequences

- Forgetting a policy makes an agent *less* capable, never *more*.
- The future wind and light observers can be built purely as event consumers.
