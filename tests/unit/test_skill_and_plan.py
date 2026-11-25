from __future__ import annotations

from pathlib import Path

import pytest

from foaa import Assignment, InvalidPlanError, Skill
from foaa.flowers.anther import execution_waves, validate_plan


def test_skill_from_markdown_reads_front_matter(tmp_path: Path) -> None:
    folder = tmp_path / "security-review"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: owasp\ndescription: reviewing web code\nowner: sec\n---\n\nCheck injection.\n"
    )
    skill = Skill.from_markdown(folder / "SKILL.md")
    assert skill.name == "owasp"
    assert skill.description == "reviewing web code"
    assert skill.instructions == "Check injection."
    assert skill.metadata == {"owner": "sec"}


def test_skill_name_defaults_to_folder_for_skill_md(tmp_path: Path) -> None:
    folder = tmp_path / "copywriting"
    folder.mkdir()
    (folder / "SKILL.md").write_text("Write clearly.")
    assert Skill.from_markdown(folder / "SKILL.md").name == "copywriting"


def test_waves_respect_dependencies() -> None:
    a = Assignment("research", "find")
    b = Assignment("ux", "sketch")
    c = Assignment("writer", "write", depends_on=(a.id, b.id))
    waves = execution_waves([c, a, b])
    assert [{x.id for x in wave} for wave in waves] == [{a.id, b.id}, {c.id}]


@pytest.mark.parametrize(
    "plan",
    [
        [],
        [Assignment("ghost", "x")],
        [Assignment("p", "")],
        [Assignment("p", "x", depends_on=("missing",))],
    ],
)
def test_invalid_plans_are_rejected(plan: list[Assignment]) -> None:
    with pytest.raises(InvalidPlanError):
        validate_plan(plan, {"p"})


def test_cycles_are_rejected() -> None:
    a = Assignment("p", "a", id="a", depends_on=("b",))
    b = Assignment("p", "b", id="b", depends_on=("a",))
    with pytest.raises(InvalidPlanError, match="cycle"):
        validate_plan([a, b], {"p"})


def test_dependencies_may_point_to_earlier_rounds() -> None:
    plan = [Assignment("p", "redo", depends_on=("old",))]
    assert validate_plan(plan, {"p"}, known_results={"old"}) == plan
