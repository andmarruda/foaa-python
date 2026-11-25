"""FOAA: Flower-Orchestrated Agent Architecture.

An orchestrator and harness for governed, observable multi-agent systems. The user defines
the agents (centers) and subagents (petals); FOAA runs, governs, and observes them.

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
    "DecisionStatus",
    "DenyAllReviewGate",
    "EventBus",
    "EventEnvelope",
    "Evidence",
    "FlowerDecision",
    "FoaaError",
    "InMemoryEventBus",
    "InMemoryMcpConnection",
    "InMemoryRetriever",
    "InvalidPlanError",
    "McpConnection",
    "McpSessionConnection",
    "Message",
    "ModelOutputError",
    "ModelPlanning",
    "ModelPort",
    "ModelReinference",
    "ModelRequest",
    "ModelResponse",
    "Objective",
    "Petal",
    "PetalResult",
    "PlanningStrategy",
    "Policy",
    "ReinferenceStrategy",
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
