from __future__ import annotations

import pytest

from foaa import Policy
from foaa.governance import Action, ActionKind


def tool(target: str, read_only: bool = False) -> Action:
    return Action(ActionKind.TOOL, target, read_only=read_only)


def test_deny_all_denies_everything() -> None:
    policy = Policy.deny_all()
    for action in (
        Action(ActionKind.SKILL, "x"),
        Action(ActionKind.RAG, "docs"),
        tool("github/create_issue"),
    ):
        assert not policy.evaluate(action).allowed


def test_patterns_allow_and_restricted_always_wins() -> None:
    policy = Policy(name="p", tools={"github/*"}, restricted={"*/delete_*"})
    assert policy.evaluate(tool("github/create_issue")).allowed
    assert not policy.evaluate(tool("github/delete_repo")).allowed
    assert not policy.evaluate(tool("slack/post")).allowed


def test_review_tools_are_allowed_only_with_review() -> None:
    policy = Policy(name="p", review_tools={"deploy/*"})
    decision = policy.evaluate(tool("deploy/production"))
    assert decision.allowed and decision.requires_review


def test_center_default_accepts_only_read_only_tools() -> None:
    policy = Policy.for_center()
    assert policy.evaluate(tool("github/get_file", read_only=True)).allowed
    assert not policy.evaluate(tool("github/push", read_only=False)).allowed
    assert policy.evaluate(Action(ActionKind.RAG, "anything")).allowed


def test_petal_default_grants_no_tools() -> None:
    policy = Policy.for_petal("engineer")
    assert not policy.evaluate(tool("github/get_file", read_only=True)).allowed
    assert policy.evaluate(Action(ActionKind.SKILL, "python")).allowed


def test_bare_string_pattern_is_treated_as_one_pattern() -> None:
    policy = Policy(name="p", tools="github/*")
    assert policy.evaluate(tool("github/x")).allowed


def test_budgets_are_validated() -> None:
    with pytest.raises(ValueError):
        Policy(name="p", max_steps=0)
