# ADR 0002: Provider-agnostic core through ports; MCP client only

- **Status:** accepted
- **Date:** 2026-11-21

## Context

FOAA must not bet on one LLM vendor, vector store, or broker. It consumes MCP servers but is not
one.

## Decision

- The core has **zero runtime dependencies**. Models, retrieval, tools, transport, and human
  review are reached through small `Protocol`s: `ModelPort`, `Retriever`, `McpConnection`,
  `EventBus`, `ReviewGate`.
- MCP support is an **adapter** (`McpSessionConnection`) over an already-initialized
  `mcp.ClientSession`, shipped as the optional extra `foaa[mcp]`. The user owns the session's
  lifecycle; FOAA never starts or exposes MCP servers.
- The adapter reads both SDK generations (2.x snake_case and 1.x camelCase attributes), and a
  contract test runs it against the real `mcp.types` when the SDK is installed.

## Consequences

- Fitness functions fail the build if a provider package is imported from the core.
- Using a provider requires a one-method adapter. Official adapters can ship later as extras.
