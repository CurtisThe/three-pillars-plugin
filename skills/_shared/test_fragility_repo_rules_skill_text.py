"""test_fragility_repo_rules_skill_text.py — a `forbidden-read-assert` rule over `skill_text`.

design: prose-pin-gate (design §Behaviors 1-2)

Every case is a source string parsed here and run through
`fragility_repo_rules.visit` with one hand-built `RepoRule` row, so the matcher is
exercised directly rather than through the CLI. A `path_glob` of `skills/*/SKILL.md`
flags an assert on the value of a `skill_text` reader (bare or module-qualified), on
a name bound to it, on a call of a same-module helper returning it, and on a read of
a path out of `skill_text.skill_paths(...)` (bound by assignment or by a `for`); the
same row with `path_glob` `agents/*.md` flags none of them, and a value from a parsed
structure such as `tier_map(...)` is never a finding. Nothing here asserts on the
wording of any `.md` file.
"""
from __future__ import annotations

import ast

import pytest

from fragility_repo_rules import RepoRule, visit

TEST_PATH = "skills/_shared/test_sample.py"
SKILL_GLOB = "skills/*/SKILL.md"
OTHER_GLOB = "agents/*.md"


def rule(path_glob: str) -> RepoRule:
    return RepoRule(id="no-skill-pin", kind="forbidden-read-assert",
                    params={"path_glob": path_glob}, reason="prose is not a contract",
                    approved_by="Curtis", date="2026-10-15")


def flagged_lines(src: str, path_glob: str = SKILL_GLOB) -> list[int]:
    """The lines of the `no-skill-pin` findings for `src` parsed as a test module."""
    tree = ast.parse(src, filename=TEST_PATH)
    return [f.line for f in visit(tree, TEST_PATH, [rule(path_glob)])
            if f.rule_id == "no-skill-pin"]


def assert_line(src: str) -> int:
    """The line the single `assert` of `src` sits on."""
    tree = ast.parse(src)
    return next(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert))


BARE_READER = """from skill_text import read_skill_text
def test_a():
    assert "x" in read_skill_text("s")
"""

QUALIFIED_READER = """import skill_text
def test_a():
    text = skill_text.read_skill_text("s")
    assert "x" in text
"""

SAME_MODULE_HELPER = """import skill_text
def _doc():
    return skill_text.read_skill_text("s")
def test_a():
    assert "x" in _doc()
"""

SUBSCRIPT_PATH = """import skill_text
def test_a():
    p = skill_text.skill_paths("s")[0]
    assert "x" in p.read_text(encoding="utf-8")
"""

FOR_OVER_PATHS = """import skill_text
def test_a():
    for p in skill_text.skill_paths("s"):
        assert "x" in p.read_text(encoding="utf-8")
"""

CASES = [BARE_READER, QUALIFIED_READER, SAME_MODULE_HELPER, SUBSCRIPT_PATH, FOR_OVER_PATHS]


@pytest.mark.parametrize("src", CASES)
def test_a_skill_text_read_under_a_matching_glob_is_flagged(src):
    assert flagged_lines(src) == [assert_line(src)]


@pytest.mark.parametrize("src", CASES)
def test_the_same_read_under_a_non_matching_glob_is_not_flagged(src):
    assert flagged_lines(src, OTHER_GLOB) == []


def test_a_value_from_a_parsed_structure_is_never_flagged():
    src = """import skill_text
def test_a():
    tiers = tier_map("s")
    assert "x" in tiers["s"]
"""
    assert flagged_lines(src) == []
