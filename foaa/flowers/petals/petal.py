from __future__ import annotations

from collections.abc import Iterable, Sequence

from foaa.common import ModelOutputError, RiskLevel
from foaa.edd.events import types
from foaa.flowers.branches import McpConnection
from foaa.flowers.common import (
    Assignment,
    Evidence,
    ModelPort,
    PetalResult,
    Risk,
    RunContext,
    Skill,
    TaskStatus,
)
from foaa.flowers.common.parsing import as_float_01, as_list, as_str, extract_json_object
from foaa.flowers.root import Retriever
from foaa.flowers.runtime import AgentHarness, CapabilityKit, Configurable, render_context
from foaa.governance import Policy

PETAL_CONTRACT = """\
# How to answer

You are one specialist inside a team. Work only within your specialty and your tools.
When you are done, answer with a single JSON object (you may wrap it in ```json):

{
  "conclusion": "your answer to the assignment",
  "evidence": [{"claim": "what supports it", "source": "where it came from"}],
  "risks": [{"description": "what could go wrong", "level": "none|low|medium|high|critical"}],
  "uncertainty": "what you do not know or could not verify",
  "confidence": 0.0
}

Be honest about uncertainty. Never invent sources. Confidence is a number from 0 to 1."""


class Petal(Configurable):
    """A subagent: one clear, bounded specialty inside a flower.

    A petal receives the same capability kit as a center (prompt, skills, MCP connections,
    RAG sources, policy), by constructor parameter or setter. It executes its assignment and
    returns a :class:`PetalResult` to the center. It never calls or coordinates other
    subagents (Constitution, Principle I).

    Without an explicit policy, a petal may use the skills and RAG sources handed to it, but no
    tools: tools must be granted by name (deny-by-default, Constitution, Principle II).
    """

    role = "petal"

    def __init__(
        self,
        name: str,
        model: ModelPort | None = None,
        *,
        description: str = "",
        prompt: str = "",
        skills: Iterable[Skill] = (),
        mcp: Iterable[McpConnection] = (),
        rag: Iterable[Retriever] = (),
        policy: Policy | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("a petal needs a name")
        self.name = name
        self.description = description
        self.model = model
        self.kit = CapabilityKit(
            prompt=prompt,
            skills=list(skills),
            mcp=list(mcp),
            rag=list(rag),
            policy=policy or Policy.for_petal(f"{name}-default"),
        )

    def set_description(self, description: str) -> Petal:
        self.description = description
        return self

    def __repr__(self) -> str:
        return f"Petal(name={self.name!r})"

    async def run(
        self,
        assignment: Assignment,
        ctx: RunContext,
        *,
        objective: str | None = None,
        upstream: Sequence[PetalResult] = (),
    ) -> PetalResult:
        """Execute one assignment. Never raises for model or tool problems: it reports them."""
        harness = AgentHarness(
            name=self.name, role=self.role, model=self._require_model(), kit=self.kit, ctx=ctx
        )
        await harness.emit(
            types.TASK_STARTED,
            {"task_id": assignment.id, "petal": self.name, "instruction": assignment.instruction},
        )

        try:
            documents = await harness.retrieve(assignment.instruction)
            system = await harness.system_prompt(PETAL_CONTRACT)
            user = _render_assignment(assignment, objective, upstream, render_context(documents))
            conversation = await harness.converse(system, user)
        except Exception as error:
            return await self._finish(
                harness,
                _failed(
                    assignment, self.name, f"{type(error).__name__}: {error}", RiskLevel.MEDIUM
                ),
            )

        sources = tuple(f"{doc.source}:{doc.id}" for doc in documents)
        if conversation.exhausted:
            result = _failed(
                assignment,
                self.name,
                f"step budget ({self.kit.policy.max_steps}) exhausted before a final answer",
                RiskLevel.MEDIUM,
                sources=sources,
                actions=conversation.actions,
            )
        elif conversation.refused:
            result = _failed(
                assignment,
                self.name,
                "the model provider declined this assignment (refusal)",
                RiskLevel.MEDIUM,
                sources=sources,
                actions=conversation.actions,
            )
        else:
            result = _parse_result(
                assignment, self.name, conversation.text, sources, conversation.actions
            )
        return await self._finish(harness, result)

    async def _finish(self, harness: AgentHarness, result: PetalResult) -> PetalResult:
        await harness.emit(
            types.TASK_COMPLETED if result.succeeded else types.TASK_FAILED,
            {
                "task_id": result.task_id,
                "petal": result.petal,
                "status": result.status.value,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence),
                "risk_count": len(result.risks),
                "actions": list(result.actions),
            },
            risk_level=result.risk_level,
            requires_review=result.risk_level.weight >= RiskLevel.HIGH.weight,
        )
        return result


def _render_assignment(
    assignment: Assignment,
    objective: str | None,
    upstream: Sequence[PetalResult],
    context: str,
) -> str:
    parts = []
    if objective:
        parts.append(f"# Team objective\n\n{objective}")
    parts.append(f"# Your assignment\n\n{assignment.instruction}")
    if assignment.feedback:
        parts.append(f"# Feedback from your center on a previous attempt\n\n{assignment.feedback}")
    if upstream:
        lines = [f"- [{r.petal}] ({r.status.value}) {r.conclusion}" for r in upstream]
        parts.append("# Results you depend on\n\n" + "\n".join(lines))
    if context:
        parts.append(context)
    return "\n\n".join(parts)


def _parse_result(
    assignment: Assignment,
    petal: str,
    text: str,
    sources: tuple[str, ...],
    actions: tuple[str, ...],
) -> PetalResult:
    try:
        data = extract_json_object(text)
    except ModelOutputError:
        # The work may still be useful; say clearly that it did not follow the contract.
        return PetalResult(
            task_id=assignment.id,
            petal=petal,
            status=TaskStatus.COMPLETED,
            conclusion=text.strip(),
            context_sources=sources,
            risks=(Risk("answer did not follow the structured contract", RiskLevel.LOW),),
            uncertainty="unstructured answer: evidence and confidence were not reported",
            actions=actions,
        )

    evidence = tuple(
        Evidence(claim=as_str(item.get("claim")), source=as_str(item.get("source")) or None)
        for item in as_list(data.get("evidence"))
        if isinstance(item, dict) and as_str(item.get("claim"))
    )
    risks = tuple(
        Risk(as_str(item.get("description")), RiskLevel.parse(item.get("level")))
        for item in as_list(data.get("risks"))
        if isinstance(item, dict) and as_str(item.get("description"))
    )
    return PetalResult(
        task_id=assignment.id,
        petal=petal,
        status=TaskStatus.COMPLETED,
        conclusion=as_str(data.get("conclusion")) or text.strip(),
        evidence=evidence,
        context_sources=sources,
        risks=risks,
        uncertainty=as_str(data.get("uncertainty")) or None,
        confidence=as_float_01(data.get("confidence")),
        actions=actions,
    )


def _failed(
    assignment: Assignment,
    petal: str,
    reason: str,
    level: RiskLevel,
    *,
    sources: tuple[str, ...] = (),
    actions: tuple[str, ...] = (),
) -> PetalResult:
    return PetalResult(
        task_id=assignment.id,
        petal=petal,
        status=TaskStatus.FAILED,
        conclusion=reason,
        context_sources=sources,
        risks=(Risk(reason, level),),
        uncertainty=reason,
        actions=actions,
    )
