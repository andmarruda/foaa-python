"""Architectural fitness functions (evolutionary architecture).

These tests do not check behavior; they protect the *shape* of the system as it evolves.
Each one enforces a rule from the constitution, so a change that breaks the architecture
fails the build instead of slipping in silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "foaa"

# Which FOAA layers each layer may import. Lower layers never import higher ones.
ALLOWED_DEPENDENCIES: dict[str, set[str]] = {
    "foaa.common": set(),
    "foaa.edd": {"foaa.common"},
    "foaa.governance": {"foaa.common", "foaa.edd"},
    "foaa.flowers.common": {"foaa.common", "foaa.edd", "foaa.governance"},
    "foaa.flowers.root": {"foaa.common", "foaa.flowers.common"},
    # LLM adapters only translate the model contract; they never touch flowers or governance.
    "foaa.adapters": {"foaa.common", "foaa.flowers.common"},
    "foaa.flowers.branches": {"foaa.common", "foaa.flowers.common"},
    "foaa.flowers.runtime": {
        "foaa.common",
        "foaa.edd",
        "foaa.governance",
        "foaa.flowers.common",
        "foaa.flowers.root",
        "foaa.flowers.branches",
    },
    "foaa.flowers.petals": {
        "foaa.common",
        "foaa.edd",
        "foaa.governance",
        "foaa.flowers.common",
        "foaa.flowers.root",
        "foaa.flowers.branches",
        "foaa.flowers.runtime",
    },
    "foaa.flowers.anther": {
        "foaa.common",
        "foaa.edd",
        "foaa.governance",
        "foaa.flowers.common",
        "foaa.flowers.root",
        "foaa.flowers.branches",
        "foaa.flowers.runtime",
        "foaa.flowers.petals",
    },
}

# Third-party packages that belong in adapters, never in the core (Constitution, IV).
PROVIDER_PACKAGES = {
    "anthropic",
    "openai",
    "mcp",
    "langchain",
    "langgraph",
    "llama_index",
    "google",
    "cohere",
    "mistralai",
    "redis",
    "kafka",
    "aiokafka",
    "nats",
    "chromadb",
    "pinecone",
    "qdrant_client",
    "weaviate",
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _layer_of(module: str) -> str | None:
    matches = [
        layer for layer in ALLOWED_DEPENDENCIES if module == layer or module.startswith(f"{layer}.")
    ]
    return max(matches, key=len) if matches else None


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


SOURCES = sorted(PACKAGE.rglob("*.py"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE.parent)))
def test_layers_only_depend_downwards(path: Path) -> None:
    module = _module_name(path)
    layer = _layer_of(module)
    if layer is None:
        pytest.skip(f"{module} is a facade or tooling module, outside the layer map")
    allowed = ALLOWED_DEPENDENCIES[layer] | {layer}
    for imported in _imports(path):
        if not imported.startswith("foaa"):
            continue
        target = _layer_of(imported)
        assert target is not None, f"{module} imports {imported}, which is not in the layer map"
        assert target in allowed, f"{module} ({layer}) must not import {imported} ({target})"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE.parent)))
def test_core_is_provider_agnostic(path: Path) -> None:
    roots = {name.split(".")[0] for name in _imports(path)}
    leaked = roots & PROVIDER_PACKAGES
    assert not leaked, f"{path.name} imports provider packages {leaked}; move them to an adapter"


def test_core_has_no_runtime_dependencies() -> None:
    import tomllib

    pyproject = tomllib.loads((PACKAGE.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []


def test_petals_never_coordinate_other_subagents() -> None:
    """A petal executes; only the center calls and coordinates subagents (Principle I)."""
    for path in (PACKAGE / "flowers" / "petals").rglob("*.py"):
        assert not any(name.startswith("foaa.flowers.anther") for name in _imports(path))

    from foaa import Petal

    petal = Petal("p")
    assert not hasattr(petal, "petals")
    assert not hasattr(petal, "add_petal")


def test_center_and_petal_share_the_same_capability_kit() -> None:
    """Same kit, by parameter or setter; the difference is only the role."""
    from foaa import Anther, Petal

    setters = {"set_model", "set_prompt", "set_skills", "add_skill", "set_mcp", "add_mcp"}
    setters |= {"set_rag", "add_rag", "set_policy"}
    for cls in (Anther, Petal):
        missing = {name for name in setters if not callable(getattr(cls, name, None))}
        assert not missing, f"{cls.__name__} is missing {missing}"
