"""Petals: the flower's subagents.

The center depends only on :class:`PetalPort`. Three implementations ship:

* :class:`ModelPetal` (alias ``Petal``): FOAA's native reference loop over a model.
* :class:`HarnessPetal`: delegates execution to any external agent harness.
* :class:`CommandPetal`: turns a command (tests, lint, build) into objective evidence.
"""

from foaa.flowers.petals.command import (
    CommandOutcome,
    CommandPetal,
    CommandRunner,
    SubprocessRunner,
)
from foaa.flowers.petals.harness import (
    HarnessAction,
    HarnessOutcome,
    HarnessPermissions,
    HarnessPetal,
    HarnessPort,
    HarnessTask,
    UpstreamResult,
)
from foaa.flowers.petals.petal import PETAL_CONTRACT, ModelPetal, Petal
from foaa.flowers.petals.port import PetalPort

__all__ = [
    "PETAL_CONTRACT",
    "CommandOutcome",
    "CommandPetal",
    "CommandRunner",
    "HarnessAction",
    "HarnessOutcome",
    "HarnessPermissions",
    "HarnessPetal",
    "HarnessPort",
    "HarnessTask",
    "ModelPetal",
    "Petal",
    "PetalPort",
    "SubprocessRunner",
    "UpstreamResult",
]
