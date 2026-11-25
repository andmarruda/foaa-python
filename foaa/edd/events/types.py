"""Catalog of the event types emitted by flowers.

Keeping them in one place makes the public contract easy to review and to version.
Every type here is a meaningful outcome; internal chatter between a center and its petals
is intentionally not published.
"""

from __future__ import annotations

from typing import Final

# Flower lifecycle ---------------------------------------------------------------------------
OBJECTIVE_RECEIVED: Final = "flower.objective.received"
DECISION_PUBLISHED: Final = "flower.decision.published"

# Center (anther) ----------------------------------------------------------------------------
PLAN_CREATED: Final = "center.plan.created"
PLAN_REJECTED: Final = "center.plan.rejected"
REINFERENCE_COMPLETED: Final = "center.reinference.completed"

# Petals --------------------------------------------------------------------------------------
TASK_STARTED: Final = "petal.task.started"
TASK_COMPLETED: Final = "petal.task.completed"
TASK_FAILED: Final = "petal.task.failed"

# Capabilities (roots, branches, skills) ------------------------------------------------------
RETRIEVAL_COMPLETED: Final = "root.retrieval.completed"
RETRIEVAL_FAILED: Final = "root.retrieval.failed"
TOOL_CALLED: Final = "branch.tool.called"
TOOL_FAILED: Final = "branch.tool.failed"

# Governance ----------------------------------------------------------------------------------
ACTION_DENIED: Final = "governance.action.denied"
REVIEW_REQUESTED: Final = "governance.review.requested"
REVIEW_RESOLVED: Final = "governance.review.resolved"

ALL_EVENT_TYPES: Final = frozenset(
    {
        OBJECTIVE_RECEIVED,
        DECISION_PUBLISHED,
        PLAN_CREATED,
        PLAN_REJECTED,
        REINFERENCE_COMPLETED,
        TASK_STARTED,
        TASK_COMPLETED,
        TASK_FAILED,
        RETRIEVAL_COMPLETED,
        RETRIEVAL_FAILED,
        TOOL_CALLED,
        TOOL_FAILED,
        ACTION_DENIED,
        REVIEW_REQUESTED,
        REVIEW_RESOLVED,
    }
)
