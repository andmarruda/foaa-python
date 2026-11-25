# ADR 0005: LLM adapters over user-owned clients, with a conformance kit

- **Status:** accepted
- **Date:** 2026-11-21

## Context

FOAA must work with any LLM without depending on one (ADR 0002). People will also write their
own adapters, and "is this adapter right?" should have an objective answer.

## Decision

- The contract is `ModelPort.complete(ModelRequest) -> ModelResponse`, documented in
  `docs/adapters.md`.
- Two contract additions make tool loops correct on every provider:
  - `ModelResponse.provider_content` / `Message.provider_content`: opaque native content of an
    assistant turn, replayed verbatim (the Messages API requires the full content, including
    reasoning blocks, during tool loops);
  - `Message.is_error` on tool results and a normalized `StopReason` (`refusal` makes petals
    fail honestly and centers escalate).
- Bundled adapters take a client the user creates (`AsyncAnthropic`, `AsyncOpenAI`, or any
  compatible client), so the core still imports no SDK:
  - `AnthropicModel`: native Claude adapter (default `claude-opus-5-5`, server-side refusal
    fallbacks and prompt caching on by default);
  - `OpenAICompatibleModel`: one adapter for every Chat Completions-compatible server.
- `foaa.testing.conformance` is an executable contract: required checks (text, system prompt,
  tool call, tool-result round trip, failed tool result) and recommended ones (usage, stop
  reason).
- Each bundled adapter is verified three ways: fake-client unit tests, wire tests with the real
  SDK against a local fake server, and opt-in live conformance.

## Consequences

- New providers cost one small adapter plus a passing conformance run.
- Tool names are capped at 64 characters by the harness so they are valid everywhere.
