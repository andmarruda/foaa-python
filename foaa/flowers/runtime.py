"""The harness shared by centers (agents) and petals (subagents).

A center and a petal receive the same capability kit (prompt, skills, MCP connections,
RAG sources, policy), by constructor parameter or setter. The only structural difference
lives in their own classes: the center calls and coordinates petals; a petal executes.

:class:`AgentHarness` runs one governed, observable conversation with the model:

* skills, RAG sources, and tools are filtered by policy before the model sees them;
* every tool call is authorized again at call time (and may wait for the gardener);
* every retrieval, tool call, and denial is published as an event.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from foaa.common import FoaaError, RiskLevel
from foaa.edd.events import types
from foaa.flowers.branches import McpConnection
from foaa.flowers.common import (
    Message,
    ModelPort,
    ModelRequest,
    RunContext,
    Skill,
    StopReason,
    ToolCall,
    ToolSpec,
)
from foaa.flowers.root import RetrievedDocument, Retriever
from foaa.governance import Action, ActionKind, Governor, Policy


@dataclass
class CapabilityKit:
    """Everything an agent or subagent may be given. Every item is optional."""

    prompt: str = ""
    skills: list[Skill] = field(default_factory=list)
    mcp: list[McpConnection] = field(default_factory=list)
    rag: list[Retriever] = field(default_factory=list)
    policy: Policy = field(default_factory=Policy.deny_all)


class Configurable:
    """Constructor-or-setter configuration shared by :class:`Anther` and :class:`Petal`.

    Setters return ``self`` so they can be chained::

        petal.set_prompt("...").add_skill(review).add_mcp(github).set_policy(policy)
    """

    name: str
    model: ModelPort | None
    kit: CapabilityKit

    def set_model(self, model: ModelPort) -> Self:
        self.model = model
        return self

    def set_prompt(self, prompt: str) -> Self:
        self.kit.prompt = prompt
        return self

    def set_skills(self, skills: Iterable[Skill]) -> Self:
        self.kit.skills = list(skills)
        return self

    def add_skill(self, skill: Skill) -> Self:
        self.kit.skills.append(skill)
        return self

    def set_mcp(self, connections: Iterable[McpConnection]) -> Self:
        self.kit.mcp = list(connections)
        return self

    def add_mcp(self, connection: McpConnection) -> Self:
        self.kit.mcp.append(connection)
        return self

    def set_rag(self, retrievers: Iterable[Retriever]) -> Self:
        self.kit.rag = list(retrievers)
        return self

    def add_rag(self, retriever: Retriever) -> Self:
        self.kit.rag.append(retriever)
        return self

    def set_policy(self, policy: Policy) -> Self:
        self.kit.policy = policy
        return self

    @property
    def policy(self) -> Policy:
        return self.kit.policy

    def _require_model(self) -> ModelPort:
        if self.model is None:
            raise FoaaError(f"{type(self).__name__} {self.name!r} has no model; call set_model()")
        return self.model


@dataclass(frozen=True, slots=True)
class Conversation:
    """The outcome of one harness conversation."""

    text: str
    steps: int
    exhausted: bool
    actions: tuple[str, ...] = ()
    stop_reason: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.stop_reason == StopReason.REFUSAL


@dataclass(frozen=True, slots=True)
class _ExposedTool:
    connection: McpConnection
    spec: ToolSpec

    @property
    def target(self) -> str:
        return f"{self.connection.name}/{self.spec.name}"


_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


class AgentHarness:
    """Runs one agent or subagent inside a :class:`RunContext`. Created per run."""

    def __init__(
        self,
        *,
        name: str,
        role: str,
        model: ModelPort,
        kit: CapabilityKit,
        ctx: RunContext,
    ) -> None:
        self.name = name
        self.role = role
        self.model = model
        self.kit = kit
        self.ctx = ctx
        self.attributes = {"agent.role": role, "agent.name": name}
        self.governor = Governor(kit.policy, ctx.review_gate, self._emit_for_governor)
        self._tool_calls = 0

    # -- observability -----------------------------------------------------------------------

    async def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        risk_level: RiskLevel = RiskLevel.NONE,
        requires_review: bool = False,
    ) -> None:
        await self.ctx.emit(
            event_type,
            payload,
            attributes=self.attributes,
            risk_level=risk_level,
            requires_review=requires_review,
        )

    async def _emit_for_governor(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        risk_level: RiskLevel = RiskLevel.NONE,
        requires_review: bool = False,
    ) -> None:
        await self.emit(event_type, payload, risk_level=risk_level, requires_review=requires_review)

    async def _authorize(self, action: Action, arguments: Mapping[str, Any] | None = None) -> bool:
        authorization = await self.governor.authorize(
            action,
            actor=self.name,
            flower_id=self.ctx.flower_id,
            correlation_id=self.ctx.correlation_id,
            arguments=arguments,
        )
        return authorization.allowed

    # -- skills ------------------------------------------------------------------------------

    async def governed_skills(self) -> list[Skill]:
        allowed = []
        for skill in self.kit.skills:
            if await self._authorize(Action(ActionKind.SKILL, skill.name)):
                allowed.append(skill)
        return allowed

    async def system_prompt(self, contract: str) -> str:
        """Prompt + allowed skills + the output contract of the caller (center or petal)."""
        parts = [self.kit.prompt.strip()] if self.kit.prompt.strip() else []
        skills = await self.governed_skills()
        if skills:
            parts.append("# Skills available to you\n\n" + "\n\n".join(s.render() for s in skills))
        parts.append(contract.strip())
        return "\n\n".join(parts)

    # -- roots (RAG) -------------------------------------------------------------------------

    async def retrieve(self, query: str) -> list[RetrievedDocument]:
        """Draw the smallest relevant context from every allowed RAG source."""
        budget = self.kit.policy.max_retrieved_documents
        documents: list[RetrievedDocument] = []
        for retriever in self.kit.rag:
            if budget <= 0:
                break
            if not await self._authorize(Action(ActionKind.RAG, retriever.name)):
                continue
            try:
                found = list(await retriever.retrieve(query, limit=budget))
            except Exception as error:
                await self.emit(
                    types.RETRIEVAL_FAILED,
                    {"source": retriever.name, "error": f"{type(error).__name__}: {error}"},
                    risk_level=RiskLevel.LOW,
                )
                continue
            documents.extend(found[:budget])
            budget -= len(found[:budget])

        documents.sort(key=lambda doc: doc.score if doc.score is not None else 0.0, reverse=True)
        if self.kit.rag:
            await self.emit(
                types.RETRIEVAL_COMPLETED,
                {
                    "count": len(documents),
                    "sources": sorted({doc.source for doc in documents}),
                    "document_ids": [doc.id for doc in documents],
                },
            )
        return documents

    # -- branches (MCP) ----------------------------------------------------------------------

    async def exposed_tools(self) -> dict[str, _ExposedTool]:
        """Tools the policy may allow, keyed by a model-safe name (``conn__tool``).

        Tools the policy would always deny are hidden so they do not waste context; every call
        is still authorized again when it happens.
        """
        exposed: dict[str, _ExposedTool] = {}
        for connection in self.kit.mcp:
            for spec in await connection.list_tools():
                tool = _ExposedTool(connection, spec)
                decision = self.kit.policy.evaluate(
                    Action(ActionKind.TOOL, tool.target, read_only=spec.read_only)
                )
                if not decision.allowed:
                    continue
                # Model-safe and unique: ^[A-Za-z0-9_-]{1,64}$ (see TOOL_NAME_PATTERN).
                key = _UNSAFE.sub("_", f"{connection.name}__{spec.name}")[:64]
                suffix = 1
                while key in exposed:
                    suffix += 1
                    key = f"{key[: 64 - len(str(suffix)) - 1]}_{suffix}"
                exposed[key] = tool
        return exposed

    async def _call_tool(self, call: ToolCall, exposed: Mapping[str, _ExposedTool]) -> str:
        tool = exposed.get(call.name)
        if tool is None:
            return f"error: unknown tool {call.name!r}"

        if self._tool_calls >= self.kit.policy.max_tool_calls:
            await self.emit(
                types.ACTION_DENIED,
                {"action": f"tool:{tool.target}", "reason": "tool-call budget exhausted"},
                risk_level=RiskLevel.LOW,
            )
            return "denied: tool-call budget exhausted"

        action = Action(ActionKind.TOOL, tool.target, read_only=tool.spec.read_only)
        authorization = await self.governor.authorize(
            action,
            actor=self.name,
            flower_id=self.ctx.flower_id,
            correlation_id=self.ctx.correlation_id,
            arguments=call.arguments,
        )
        if not authorization.allowed:
            return f"denied: {authorization.reason}"

        self._tool_calls += 1
        try:
            result = await tool.connection.call_tool(tool.spec.name, call.arguments)
        except Exception as error:
            await self.emit(
                types.TOOL_FAILED,
                {"tool": tool.target, "error": f"{type(error).__name__}: {error}"},
                risk_level=RiskLevel.LOW,
            )
            return f"error: {type(error).__name__}: {error}"

        await self.emit(
            types.TOOL_CALLED,
            {
                "tool": tool.target,
                "argument_keys": sorted(call.arguments),  # values may be sensitive
                "is_error": result.is_error,
                "reviewed": authorization.reviewed,
                "read_only": tool.spec.read_only,
            },
            risk_level=RiskLevel.NONE if tool.spec.read_only else RiskLevel.LOW,
        )
        return f"error: {result.content}" if result.is_error else result.content

    # -- the governed loop -------------------------------------------------------------------

    async def converse(self, system: str, user: str) -> Conversation:
        """Talk to the model, executing governed tool calls, until it answers in text."""
        exposed = await self.exposed_tools()
        specs = tuple(
            ToolSpec(key, tool.spec.description, tool.spec.input_schema, tool.spec.read_only)
            for key, tool in exposed.items()
        )
        messages: list[Message] = [Message.system(system), Message.user(user)]
        actions: list[str] = []
        metadata = {"flower.id": self.ctx.flower_id, **self.attributes}
        last_text = ""
        last_stop: str | None = None
        usage: dict[str, int] = {}

        for step in range(1, self.kit.policy.max_steps + 1):
            response = await self.model.complete(
                ModelRequest(messages=tuple(messages), tools=specs, metadata=metadata)
            )
            for key, value in response.usage.items():
                usage[key] = usage.get(key, 0) + value
            last_text, last_stop = response.content, response.stop_reason
            if not response.tool_calls:
                return Conversation(
                    response.content,
                    step,
                    exhausted=False,
                    actions=tuple(actions),
                    stop_reason=response.stop_reason,
                    usage=usage,
                )

            # Replay the provider's native content untouched (e.g. reasoning blocks).
            messages.append(
                Message.assistant(
                    response.content,
                    response.tool_calls,
                    provider_content=response.provider_content,
                )
            )
            for call in response.tool_calls:
                output = await self._call_tool(call, exposed)
                failed = output.startswith(("error:", "denied:"))
                if call.name in exposed and not output.startswith("denied:"):
                    actions.append(exposed[call.name].target)
                messages.append(Message.tool(call.id, output, is_error=failed))

        return Conversation(
            last_text,
            self.kit.policy.max_steps,
            exhausted=True,
            actions=tuple(actions),
            stop_reason=last_stop,
            usage=usage,
        )


def render_context(documents: Sequence[RetrievedDocument]) -> str:
    """Format retrieved documents for the model, keeping provenance visible."""
    if not documents:
        return ""
    blocks = [f"[{doc.source}:{doc.id}]\n{doc.content.strip()}" for doc in documents]
    return "# Retrieved context\n\n" + "\n\n".join(blocks)
