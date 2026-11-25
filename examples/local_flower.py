"""A local Product Flower: one center, three petals, skills, RAG, MCP, policy, and events.

Run it with:  uv run python examples/local_flower.py

It uses ScriptedModel so it runs offline. To use a real LLM, implement ``foaa.ModelPort``
(one async method) for your provider and pass it instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from foaa import (
    Anther,
    InMemoryEventBus,
    InMemoryMcpConnection,
    InMemoryRetriever,
    Objective,
    Petal,
    Policy,
    Skill,
    ToolSpec,
)
from foaa.testing import ScriptedModel, json_reply, reply, tool_call


def petal_answer(conclusion: str, source: str) -> Any:
    return json_reply(
        {
            "conclusion": conclusion,
            "evidence": [{"claim": conclusion, "source": source}],
            "risks": [{"description": "based on a single source", "level": "low"}],
            "uncertainty": "not validated with real customers yet",
            "confidence": 0.8,
        }
    )


async def main() -> None:
    # Branch: an MCP-like connection with one read-only tool.
    async def search_tickets(args: Mapping[str, Any]) -> str:
        return f"12 tickets mention '{args.get('query')}'"

    support = InMemoryMcpConnection("support").add_tool(
        ToolSpec("search_tickets", "Search support tickets", read_only=True), search_tickets
    )

    # Root: what the soil remembers.
    soil = InMemoryRetriever(
        "launch-history",
        ["Last pricing launch: international tax calculation broke annual billing."],
    )

    # Skill: stored wherever the user wants, handed in by parameter.
    interviews = Skill.from_text(
        "customer-interviews", "Prefer direct quotes. Separate facts from opinions.", "research"
    )

    research = Petal(
        "research",
        ScriptedModel(
            [
                reply("", tool_call("support__search_tickets", {"query": "yearly plan"})),
                petal_answer("Customers want a clear yearly discount.", "support:tickets"),
            ]
        ),
        description="customer research",
        prompt="You are a customer researcher.",
        skills=[interviews],
        mcp=[support],
        policy=Policy.for_petal("research", tools={"support/search_*"}),
    )
    ux = Petal(
        "ux",
        ScriptedModel(default=petal_answer("One-click upgrade from monthly.", "ux:flows")),
        description="user experience",
    )
    writer = Petal(
        "writer",
        ScriptedModel(default=petal_answer("Pay yearly, get two months free.", "copy:draft")),
        description="copywriting",
    )

    center_model = ScriptedModel(
        [
            json_reply(
                {
                    "assignments": [
                        {
                            "id": "a1",
                            "petal": "research",
                            "instruction": "What do customers expect?",
                        },
                        {"id": "a2", "petal": "ux", "instruction": "Design the upgrade flow."},
                        {
                            "id": "a3",
                            "petal": "writer",
                            "instruction": "Write the launch message.",
                            "depends_on": ["a1", "a2"],
                        },
                    ]
                }
            ),
            json_reply(
                {
                    "status": "complete",
                    "summary": "Launch yearly plans: 2 months free, one-click upgrade.",
                    "confidence": 0.82,
                    "risks": [{"description": "check international tax early", "level": "medium"}],
                }
            ),
        ]
    )

    bus = InMemoryEventBus()
    center = Anther(
        "product",
        center_model,
        petals=[research, ux, writer],
        prompt="You lead the product flower.",
        rag=[soil],
        bus=bus,
    )

    decision = await center.handle(Objective("Launch yearly subscription plans"))

    print(f"Decision: {decision.status.value} (confidence {decision.confidence})")
    print(f"Summary:  {decision.summary}")
    print(f"Risk:     {decision.risk_level.value}\n")
    print("Events:")
    for event in bus.history:
        who = event.attributes.get("agent.name", "")
        print(f"  {event.event_type:<32} {who}")


if __name__ == "__main__":
    asyncio.run(main())
