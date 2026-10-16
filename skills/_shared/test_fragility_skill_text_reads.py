"""test_fragility_skill_text_reads.py — tracing a `.md` read through `skill_text`.

design: prose-pin-gate (design §Behaviors 1-2)

Every case is a source string parsed here and run through the flag rules with
`fragility_rules_flag.visit`; only the `md-read-assert` findings are counted. The
value of `read_skill_text(...)` (bare or module-qualified), and a path from
`skill_paths(...)` once it is read, count as a `.md` read; so does a same-module
helper that joins a path parameter onto a root and reads it, but only where the
call-site argument is itself a `.md` string. A value from a parsed structure such
as `tier_map(...)` is never a read. Nothing here asserts on the wording of any
`.md` file.
"""
from __future__ import annotations

import ast

import pytest

from fragility_ast import is_md_read, md_reads, skill_paths_path, skill_text_path
from fragility_rules_flag import visit

TEST_PATH = "skills/_shared/test_sample.py"


def md_read_lines(src: str) -> list[int]:
    """The lines of the `md-read-assert` findings for `src` parsed as a test module."""
    tree = ast.parse(src, filename=TEST_PATH)
    return [f.line for f in visit(tree, TEST_PATH, None)
            if f.rule_id == "md-read-assert"]


def flagged(src: str) -> bool:
    return bool(md_read_lines(src))


# --- read_skill_text is a `.md` read -----------------------------------------------------

BARE_IMPORT = """from skill_text import read_skill_text
def test_a():
    assert "x" in read_skill_text("s")
"""

QUALIFIED = """import skill_text
def test_a():
    assert "x" in skill_text.read_skill_text("s")
"""

BOUND_NAME = """import skill_text
def test_a():
    text = skill_text.read_skill_text("s")
    assert "x" in text
"""

MODULE_HELPER = """import skill_text
def _doc():
    return skill_text.read_skill_text("s")
def test_a():
    assert "x" in _doc()
"""


@pytest.mark.parametrize("src", [BARE_IMPORT, QUALIFIED, BOUND_NAME, MODULE_HELPER])
def test_a_read_skill_text_value_in_an_assert_is_flagged(src):
    assert flagged(src)


def test_read_skill_text_path_names_the_skill_file():
    node = ast.parse('read_skill_text("worker")', mode="eval").body
    assert skill_text_path(node) == "skills/worker/SKILL.md"


def test_a_non_literal_skill_name_still_reads_a_skill_file():
    node = ast.parse("skill_text.read_skill_text(name)", mode="eval").body
    assert skill_text_path(node) == "skills/skill/SKILL.md"


def test_an_unrelated_call_is_not_a_skill_text_read():
    for src in ('read_file("s")', 'skill_text.tier_map("s")', 'open("x.md")'):
        node = ast.parse(src, mode="eval").body
        assert skill_text_path(node) is None, src


# --- skill_paths is a `.md` path once read ----------------------------------------------

FOR_LOOP = """import skill_text
def test_a():
    for p in skill_text.skill_paths("s"):
        assert "x" in p.read_text(encoding="utf-8")
"""

SUBSCRIPT_NAME = """import skill_text
def test_a():
    paths = skill_text.skill_paths("s")
    assert "x" in paths[0].read_text(encoding="utf-8")
"""

INLINE_SUBSCRIPT = """import skill_text
def test_a():
    assert "x" in skill_text.skill_paths("s")[0].read_text(encoding="utf-8")
"""


@pytest.mark.parametrize("src", [FOR_LOOP, SUBSCRIPT_NAME, INLINE_SUBSCRIPT])
def test_a_read_of_a_skill_paths_value_is_flagged(src):
    assert flagged(src)


def test_skill_paths_path_follows_a_subscript_off_the_call():
    node = ast.parse('skill_paths("worker")[0]', mode="eval").body
    assert skill_paths_path(node) == "skills/worker/SKILL.md"


def test_a_skill_paths_name_is_a_path_not_a_read():
    node = ast.parse('skill_text.skill_paths("worker")', mode="eval").body
    assert skill_paths_path(node) == "skills/worker/SKILL.md"
    assert skill_text_path(node) is None


def test_a_skill_paths_name_never_goes_unread():
    src = """import skill_text
def test_a():
    paths = skill_text.skill_paths("s")
    assert paths
"""
    assert not flagged(src)


# --- a same-module helper taking the path -----------------------------------------------

PARAM_HELPER_MD = """ROOT = None
def _doc(rel):
    return (ROOT / rel).read_text(encoding="utf-8")
def test_a():
    assert "x" in _doc("a.md")
"""

PARAM_HELPER_JSON = """ROOT = None
def _doc(rel):
    return (ROOT / rel).read_text(encoding="utf-8")
def test_a():
    assert "x" in _doc("a.json")
"""


def test_a_parameterised_helper_is_a_read_only_for_a_md_argument():
    assert flagged(PARAM_HELPER_MD)
    assert not flagged(PARAM_HELPER_JSON)


def test_the_parameterised_helper_is_recorded_by_position():
    tree = ast.parse(PARAM_HELPER_MD, filename=TEST_PATH)
    assert md_reads(tree, tree) == {"_doc#0"}


def test_is_md_read_accepts_the_helper_only_with_a_md_argument():
    tree = ast.parse(PARAM_HELPER_MD, filename=TEST_PATH)
    reads = md_reads(tree, tree)
    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_doc")
    assert is_md_read(call, reads, {})


# --- a parsed structure is never a read --------------------------------------------------

TIER_MAP_BARE = """from skill_text import tier_map
def test_a():
    assert "x" in tier_map("s")
"""

TIER_MAP_QUALIFIED = """import skill_text
def test_a():
    assert "x" in skill_text.tier_map("s")
"""

TIER_MAP_BOUND = """import skill_text
def test_a():
    names = skill_text.tier_map("s")
    assert "x" in names
"""


@pytest.mark.parametrize("src", [TIER_MAP_BARE, TIER_MAP_QUALIFIED, TIER_MAP_BOUND])
def test_a_value_from_a_parsed_structure_is_never_flagged(src):
    assert not flagged(src)
