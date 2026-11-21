# FOAA (Flower-Orchestrated Agent Architecture) Constitution

FOAA is a philosophy for coordinating multi-team, multi-agent, and multi-subagent systems,
modeled on a living flower field. `foaa-python` is its Python implementation. This constitution
defines the non-negotiable rules every specification, plan, and line of code MUST respect.

## Core Principles

### I. Nature-Mapped Responsibilities

Every public component MUST map to exactly one element of the FOAA ecosystem, and MUST NOT take
over the responsibility of another element:

| Element | Package | Responsibility |
|---|---|---|
| Flower | `flowers/` | A team: one bounded unit of governed intelligence. |
| Anther (center) | `flowers/anther/` | The flower's manager: interprets goals, delegates, reasons again over evidence, makes the final local decision. |
| Petals | `flowers/petals/` | Specialist subagents with one clear, bounded role. |
| Root | `flowers/root/` | Retrieval (RAG): what the flower needs to know now. |
| Branches | `flowers/branches/` | Governed reach to tools and systems (MCP): what the flower can use. |
| Bees | `bees/` | Cross-flower orchestrators: route, sequence, translate context, synthesize. |
| Environment | `environment/` | Executive strategy: priorities, budgets, risk limits, quality thresholds. |
| Governance | `governance/` | Policies, permissions, human-review (gardener) gates. |
| Soil | `soil/` | Shared, governed, long-term memory. |
| Wind / Light | `observers/wind/`, `observers/light/` | Observers of movement and of understanding. |
| EDD | `edd/events/`, `edd/listeners/` | Event contracts and their consumers. |

Rules:
- A bee MUST communicate only with a flower's center, never directly with its petals.
- Petals MUST NOT communicate peer-to-peer unless the exchange is declared to, and visible from,
  the center.
- A center MUST NOT simply concatenate petal outputs; it MUST run an explicit re-evaluation
  (reinference) step before publishing a decision.
- No component may become a "universal orchestrator" that owns the internal decisions of flowers.

Rationale: the metaphor is the architecture. Blurred roles recreate the chaos FOAA exists to remove.

### II. Bounded Autonomy, Governed by Default

- Every petal MUST run under an explicit policy declaring allowed actions, accessible tools and
  data, restricted resources, and the actions that require review.
- Access is deny-by-default: an action not allowed by policy MUST be rejected, and the rejection
  MUST be observable.
- Human-review (gardener) gates MUST be expressible in policy and MUST block the action until
  resolved.
- A petal result MUST carry, alongside its conclusion: evidence, context sources, risks, and
  uncertainty/confidence.

Rationale: autonomy is welcome; unaccountable autonomy is not.

### III. Observability Is Not Optional (Wind & Light)

- Every meaningful action (delegation, tool call, retrieval, decision, escalation, policy
  evaluation) MUST emit a structured, machine-readable record.
- Every record MUST be traceable to its origin: at minimum `flower.id`, `agent.role`,
  `goal.id`/`correlation.id`, and a timestamp.
- Signals MUST follow OpenTelemetry-compatible conventions so existing tools can consume them.
- Observers MUST NOT execute the work they observe. They may alert, explain, block, or escalate;
  the responsible center or governance layer decides the correction.
- Wind covers movement (retries, latency, drift, overload, cost growth, failure to converge).
  Light covers understanding (decisions, provenance, evidence, risk, quality, health).

Rationale: managers govern action; observers govern perception. A field without light still
runs, but no one can govern it.

### IV. Provider-Agnostic Core (Ports & Adapters)

- The core package MUST NOT depend on any specific LLM provider, vector store, message broker,
  or MCP server implementation.
- Every external capability MUST be reached through a typed interface (port). Concrete
  integrations (e.g., Anthropic, OpenAI, local models, Redis, Kafka) MUST live in adapters
  shipped as optional extras.
- The core MUST be fully usable and testable with in-memory/fake adapters and no network access.

Rationale: FOAA is a philosophy of organization, not a bet on a vendor.

### V. Event-Driven Contracts

- Flowers and bees MUST interact through explicit, versioned event contracts, not through each
  other's internals.
- Every event envelope MUST include: `event_id`, `event_type`, `event_version`, `occurred_at`,
  producing `flower_id`, `correlation_id`, `causation_id`, risk level, and review requirement.
- Events MUST describe meaningful outcomes (e.g., `architecture.review.completed`), not every
  internal step of a flower.
- Event handling MUST be idempotent.
- The default transport is an in-memory bus. Distributed brokers MUST plug in through the same
  transport interface without changing flower or bee code.
- Contract changes that break consumers MUST bump `event_version`.

Rationale: a flower's identity is an architectural boundary; its server is an implementation detail.

### VI. Governed Memory (The Soil Remembers)

- Memory MUST distinguish at least: temporary working context, execution traces, proposed
  knowledge, validated knowledge, restricted records, and obsolete information.
- Only validated knowledge may return to the shared soil; promotion MUST be an explicit,
  observable step.
- Retrieval MUST select the smallest relevant context for the objective, not hand every agent
  everything.
- Knowledge sources MUST be able to be marked obsolete or restricted so that no flower draws
  from them afterwards.

Rationale: unfiltered memory preserves errors as faithfully as wisdom.

### VII. Simplicity, Typing, and Tests

- Public APIs MUST be fully type-annotated and pass strict static type checking.
- Every public behavior MUST have automated tests; contract and governance rules
  (Principles I, II, V) MUST have dedicated tests that prove violations are rejected.
- Start with the simplest design that satisfies the spec (YAGNI). Added complexity MUST be
  justified in the plan's complexity tracking.
- Prefer composition and small modules aligned with the ecosystem map over deep inheritance.

Rationale: a framework about clarity must itself be clear.

## Scope: What FOAA Is and Is Not

**FOAA is:**
- A Python framework/library (`import foaa`) for building governed, observable multi-agent systems.
- A set of building blocks (flowers, anthers, petals, roots, branches, bees, environment,
  governance, soil, observers, events) and the contracts between them.
- Provider-agnostic, running in a single process by default and distributable through events.

**FOAA is not:**
- An LLM or model: it does not train or host models.
- A vector database: roots and soil use storage through interfaces.
- A dashboard or APM tool: wind and light emit signals; visualization is left to existing tools.
- An MCP server or protocol implementation: branches consume MCP through the official SDK.
- A ready-to-run platform or hosted service.

**Intellectual property:** the book *Flower-Orchestrated Agent Architecture (FOAA)* is copyrighted
and MUST NOT be committed, reproduced, or quoted beyond brief references in this repository.
`docs/foaa.pdf` MUST remain git-ignored. Code is MIT-licensed; the book is not.

## Technical Standards & Development Workflow

- Language: Python 3.11+. Async-first public APIs (`asyncio`), with sync helpers only where they
  add clear value.
- Packaging: `pyproject.toml`; optional integrations exposed as extras (e.g., `foaa[anthropic]`).
- Quality gates for every change: tests pass, strict type check passes, linter/formatter pass.
- Work flows through Spec Kit: constitution → specify → (clarify) → plan → tasks → implement.
  Every plan MUST include a Constitution Check against Principles I–VII.
- Documentation and code identifiers are written in English. Ecosystem vocabulary (flower,
  anther, petal, root, branch, bee, soil, wind, light, environment) MUST be used consistently.
- Placeholder `.gitkeep` files are removed when a folder receives its first real module.

## Governance

- This constitution supersedes other practices in this repository. Specs, plans, and reviews
  MUST verify compliance; violations MUST be fixed or explicitly justified in the plan's
  complexity tracking.
- Amendments require: a written proposal stating the change and rationale, approval by the
  project maintainer (Anderson Matheus Arruda), and a migration note when existing code is affected.
- Versioning follows semantic versioning: MAJOR for removing or redefining principles, MINOR for
  new principles or materially expanded guidance, PATCH for clarifications and wording.
- Compliance is reviewed at every plan (Constitution Check) and before every release.

**Version**: 1.0.0 | **Ratified**: 2026-11-21 | **Last Amended**: 2026-11-21
