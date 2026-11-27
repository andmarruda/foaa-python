"""Fitness functions for ADR 0006: FOAA governs harnesses, it is not one.

The flower *defines* agents (roles, limits, evidence contract). Execution belongs to whatever
harness the user already has. These checks keep that boundary from eroding.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "foaa"
PETALS = PACKAGE / "flowers" / "petals"


def _imported_names(path: Path, module_prefix: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith(module_prefix)
        ):
            names.update(alias.name for alias in node.names)
    return names


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_center_depends_on_the_petal_port_not_an_implementation() -> None:
    """The center coordinates *any* subagent: native, external harness, or command."""
    for path in (PACKAGE / "flowers" / "anther").rglob("*.py"):
        names = _imported_names(path, "foaa.flowers.petals")
        assert names <= {"PetalPort"}, f"{path.name} imports petal implementations: {names}"


def test_harness_petals_never_run_their_own_model_loop() -> None:
    """Harness and command petals delegate execution; they never talk to a model directly."""
    for name in ("harness.py", "command.py"):
        modules = _imported_modules(PETALS / name)
        assert "foaa.flowers.runtime" not in modules, f"{name} must not use the native harness"
        source = (PETALS / name).read_text(encoding="utf-8")
        assert "ModelPort" not in source, f"{name} must not depend on a model"


def test_every_shipped_petal_satisfies_the_port() -> None:
    from foaa import CommandPetal, HarnessPetal, ModelPetal, PetalPort
    from foaa.testing import FakeCommandRunner, FakeHarness

    petals = [
        ModelPetal("native"),
        HarnessPetal("external", FakeHarness()),
        CommandPetal("tests", FakeCommandRunner(), ["pytest"]),
    ]
    for petal in petals:
        assert isinstance(petal, PetalPort), f"{type(petal).__name__} does not satisfy PetalPort"


def test_petal_name_stays_as_a_compatible_alias() -> None:
    """Renaming must not break existing users (evolutionary architecture)."""
    from foaa import ModelPetal, Petal

    assert Petal is ModelPetal


def test_package_does_not_describe_itself_as_a_harness() -> None:
    import tomllib

    pyproject = tomllib.loads((PACKAGE.parent / "pyproject.toml").read_text(encoding="utf-8"))
    description = pyproject["project"]["description"].lower()
    assert "and harness" not in description
