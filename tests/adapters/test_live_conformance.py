"""Live conformance against real models. Off by default: it makes a few paid API calls.

    FOAA_LIVE=1 ANTHROPIC_API_KEY=... uv run --with anthropic pytest tests/adapters -k live
    FOAA_LIVE=1 OPENAI_API_KEY=... FOAA_OPENAI_MODEL=gpt-... uv run --with openai pytest -k live

For any OpenAI-compatible server, also set ``OPENAI_BASE_URL`` (e.g. a local Ollama).
"""

from __future__ import annotations

import os

import pytest

from foaa.adapters import AnthropicModel, OpenAICompatibleModel
from foaa.testing.conformance import run_conformance

pytestmark = pytest.mark.skipif(
    os.environ.get("FOAA_LIVE") != "1", reason="live calls are opt-in: set FOAA_LIVE=1"
)


async def test_live_anthropic_conformance() -> None:
    anthropic = pytest.importorskip("anthropic")
    model = AnthropicModel(anthropic.AsyncAnthropic(), max_tokens=2_000, effort="medium")
    report = await run_conformance(model)
    print(report.summary())
    report.raise_for_failures()


async def test_live_openai_compatible_conformance() -> None:
    openai = pytest.importorskip("openai")
    model_name = os.environ.get("FOAA_OPENAI_MODEL")
    if not model_name:
        pytest.skip("set FOAA_OPENAI_MODEL to the model to test")
    model = OpenAICompatibleModel(openai.AsyncOpenAI(), model=model_name)
    report = await run_conformance(model)
    print(report.summary())
    report.raise_for_failures()
