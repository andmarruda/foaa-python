"""LLM adapters: implementations of :class:`~foaa.flowers.common.ModelPort`.

Adapters receive a client the user already created, so FOAA itself never imports a
provider SDK. Install the matching extra for the client: ``foaa[anthropic]``,
``foaa[openai]``. To write your own adapter, see ``docs/adapters.md`` and run
``foaa.testing.conformance`` against it.
"""

from foaa.adapters.anthropic_messages import AnthropicModel
from foaa.adapters.openai_compatible import OpenAICompatibleModel

__all__ = ["AnthropicModel", "OpenAICompatibleModel"]
