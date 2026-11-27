"""FOAA: Flower-Orchestrated Agent Architecture.

An orchestrator for governed, observable multi-agent systems. It is not a harness: the flower
defines agents (centers) and subagents (petals); execution belongs to the harnesses and
connectors you already use (Claude Code, Codex, the Agent SDK, MCP...), and FOAA governs,
coordinates, and observes them (ADR 0006).

    from foaa import Anther, Petal, Policy, Skill

Implemented so far: the flower (center + petals), with skills, RAG roots, MCP branches,
governance, and events. Bees, environment, soil, and observers come next.
"""

from foaa.common import FoaaError, InvalidPlanError, ModelOutputError, RiskLevel
from foaa.edd import EventBus, EventEnvelope, InMemoryEventBus
from foaa.edd.events import types as event_types
from foaa.flowers import Anther, Petal
from foaa.flowers.anther import (
    ModelPlanning,
    ModelReinference,
    PlanningStrategy,
    ReinferenceStrategy,
    RepairLoopReinference,
    StaticPlanning,
    Step,
    ThresholdReinference,
    Verdict,
    VerdictStatus,
)
from foaa.flowers.branches import (
    InMemoryMcpConnection,
    McpConnection,
    McpSessionConnection,
    ToolResult,
)
from foaa.flowers.common import (
    Assignment,
    DecisionStatus,
    Evidence,
    FlowerDecision,
    Message,
    ModelPort,
    ModelRequest,
    ModelResponse,
    Objective,
    PetalResult,
    Risk,
    RunContext,
    Skill,
    StopReason,
    TaskStatus,
    ToolCall,
    ToolSpec,
)
from foaa.flowers.petals import (
    CommandOutcome,
    CommandPetal,
    CommandRunner,
    HarnessAction,
    HarnessOutcome,
    HarnessPermissions,
    HarnessPetal,
    HarnessPort,
    HarnessTask,
    ModelPetal,
    PetalPort,
    SubprocessRunner,
)
from foaa.flowers.root import InMemoryRetriever, RetrievedDocument, Retriever
from foaa.governance import (
    ApproveAllReviewGate,
    CallbackReviewGate,
    DenyAllReviewGate,
    Policy,
    ReviewDecision,
    ReviewGate,
    ReviewRequest,
)

__version__ = "0.1.0.dev0"

__all__ = [
    "Anther",
    "ApproveAllReviewGate",
    "Assignment",
    "CallbackReviewGate",
    "CommandOutcome",
    "CommandPetal",
    "CommandRunner",
    "DecisionStatus",
    "DenyAllReviewGate",
    "EventBus",
    "EventEnvelope",
    "Evidence",
    "FlowerDecision",
    "FoaaError",
    "HarnessAction",
    "HarnessOutcome",
    "HarnessPermissions",
    "HarnessPetal",
    "HarnessPort",
    "HarnessTask",
    "InMemoryEventBus",
    "InMemoryMcpConnection",
    "InMemoryRetriever",
    "InvalidPlanError",
    "McpConnection",
    "McpSessionConnection",
    "Message",
    "ModelOutputError",
    "ModelPetal",
    "ModelPlanning",
    "ModelPort",
    "ModelReinference",
    "ModelRequest",
    "ModelResponse",
    "Objective",
    "Petal",
    "PetalPort",
    "PetalResult",
    "PlanningStrategy",
    "Policy",
    "ReinferenceStrategy",
    "RepairLoopReinference",
    "RetrievedDocument",
    "Retriever",
    "ReviewDecision",
    "ReviewGate",
    "ReviewRequest",
    "Risk",
    "RiskLevel",
    "RunContext",
    "Skill",
    "StaticPlanning",
    "Step",
    "StopReason",
    "SubprocessRunner",
    "TaskStatus",
    "ThresholdReinference",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Verdict",
    "VerdictStatus",
    "__version__",
    "event_types",
]
