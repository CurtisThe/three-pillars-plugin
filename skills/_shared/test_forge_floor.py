"""Tests for forge_floor.py -- the `## Forge behaviour` design-floor check (forge-interface 2.1).

At `floor: 3`, a design whose class is not just-do-it and whose body names a forge
surface (a PR create / read / comment / label / merge, a review loop, a merge gate,
CI status, branch protection, a `gh`/`tea` call) must carry a non-placeholder
`## Forge behaviour` section. Below floor 3, or at just-do-it, the same shape only
warns on stderr (one line). Both validators (`validate_design_floor.main` and
`validate_artifact`) share the verdict through `floor_sections.apply`. Assertions
read keys, exit codes and section/surface names -- never prose wording.

Run with: pytest skills/_shared/test_forge_floor.py -q
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import floor_sections  # noqa: E402
import forge_floor  # noqa: E402
import validate_design_floor  # noqa: E402
from validate_artifact import validate_artifact  # noqa: E402

SECTION = "Forge behaviour"
NAMED = "PR comment"

_FORGE_BODY = (
    "## Forge behaviour\n"
    "GitHub posts the verdict through the API; Gitea posts it through the tea CLI, and "
    "a missing backend degrades visibly with one stderr line.\n"
)


def _design(*, floor: str | None = "3", klass: str | None = "light",
            named: str | None = NAMED, forge: str | None = None) -> str:
    """A design.md carrying every base section plus Consumer-repo behaviour.

    ``named`` is woven into ``## Behaviors`` (None names no forge surface);
    ``forge`` is the raw ``## Forge behaviour`` section to append (None omits it).
    """
    lines = ["---"]
    if klass is not None:
        lines.append(f"weight-class: {klass}")
    if floor is not None:
        lines.append(f"floor: {floor}")
    lines.append("---")
    behaviour = (
        f"The harness drives the {named} path end to end for every run."
        if named else "The harness walks every configured step in order for every run."
    )
    body = (
        "# test-design\n\n"
        "## Problem\nA real problem, stated long enough to clear the content floor bar.\n\n"
        "## Vision alignment\nIt advances the floor rather than the ceiling of the tooling.\n\n"
        "## Scope\n### In scope\nGate the forge-facing designs on one extra named section.\n\n"
        f"## Behaviors\n{behaviour}\n\n"
        "## Constraints\nStdlib only; no new dependency and no circular import at load.\n\n"
        "## Consumer-repo behaviour\nShips under skills/_shared and runs in a user's repo.\n"
    )
    if forge is not None:
        body += "\n" + forge
    return "\n".join(lines) + "\n" + body


def _run(tmp_path: Path, text: str) -> tuple[int, str]:
    (tmp_path / "design.md").write_text(text, encoding="utf-8")
    err = io.StringIO()
    with redirect_stderr(err):
        code = validate_design_floor.main(["validate_design_floor.py", str(tmp_path)])
    return code, err.getvalue()


def _verdict(err: str) -> dict:
    return json.loads(err.strip().splitlines()[-1])


def _forge_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if SECTION in ln]


# ---------------------------------------------------------------------------
# validate_design_floor.main -- BLOCKED / PASS at floor 3
# ---------------------------------------------------------------------------


def test_floor3_light_forge_surface_without_section_blocks(tmp_path):
    code, err = _run(tmp_path, _design())
    assert code == 1, err
    verdict = _verdict(err)
    assert verdict["verdict"] == "BLOCKED"
    assert SECTION in verdict["missing"]


def test_floor3_with_non_placeholder_section_passes(tmp_path):
    code, err = _run(tmp_path, _design(forge=_FORGE_BODY))
    assert code == 0, err
    assert _forge_lines(err) == []


def test_floor3_placeholder_only_section_is_flagged(tmp_path):
    code, err = _run(tmp_path, _design(forge="## Forge behaviour\nTBD\n"))
    assert code == 1, err
    verdict = _verdict(err)
    assert SECTION in verdict["placeholder_only"]
    assert SECTION not in verdict["missing"]


def test_floor3_full_class_also_requires_the_section(tmp_path):
    code, err = _run(tmp_path, _design(klass="full"))
    assert code == 1 and SECTION in _verdict(err)["missing"]


# ---------------------------------------------------------------------------
# Warn-only shapes: just-do-it, floor 2, floor 1 -- exit 0 and one stderr line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kwargs", [
    {"klass": "just-do-it", "floor": "3"},
    {"klass": "light", "floor": "2"},
    {"klass": "light", "floor": None},
], ids=["just-do-it-floor3", "light-floor2", "light-legacy-floor1"])
def test_below_the_bar_warns_once_and_passes(tmp_path, kwargs):
    code, err = _run(tmp_path, _design(**kwargs))
    assert code == 0, err
    lines = _forge_lines(err)
    assert len(lines) == 1, err
    assert NAMED in lines[0]


def test_warn_shape_with_section_present_is_silent(tmp_path):
    code, err = _run(tmp_path, _design(klass="just-do-it", forge=_FORGE_BODY))
    assert code == 0 and _forge_lines(err) == []


def test_no_forge_surface_is_silent_at_every_floor(tmp_path):
    for floor in ("3", "2", None):
        code, err = _run(tmp_path, _design(floor=floor, named=None))
        assert code == 0, err
        assert _forge_lines(err) == []


# ---------------------------------------------------------------------------
# The keyword table -- case-insensitive over FORGE_SURFACES
# ---------------------------------------------------------------------------

_EXPECTED_SURFACES = {
    "pull request", "PR create", "PR read", "PR comment", "PR label", "PR merge",
    "review loop", "merge gate", "CI status", "branch protection",
    "gh pr", "gh api", "tea pr",
}


def test_surface_table_holds_the_documented_keywords():
    assert set(forge_floor.FORGE_SURFACES) == _EXPECTED_SURFACES
    assert forge_floor.FORGE_SECTION == SECTION == floor_sections.FORGE_SECTION


@pytest.mark.parametrize("surface", sorted(_EXPECTED_SURFACES))
@pytest.mark.parametrize("variant", [str.lower, str.upper, str.title],
                         ids=["lower", "upper", "title"])
def test_every_surface_matches_case_insensitively(tmp_path, surface, variant):
    text = _design(named=variant(surface))
    assert forge_floor.surfaces_named(text) == [surface]
    assert forge_floor.required(text) is True
    code, err = _run(tmp_path, text)
    assert code == 1 and SECTION in _verdict(err)["missing"]


@pytest.mark.parametrize("phrase", [
    "the high priority queue", "a tea practice run", "weigh prices",
])
def test_substrings_inside_other_words_do_not_match(phrase):
    assert forge_floor.surfaces_named(_design(named=phrase)) == []


def test_plural_surfaces_match():
    assert forge_floor.surfaces_named(_design(named="PR comments")) == ["PR comment"]
    assert forge_floor.surfaces_named(_design(named="pull requests")) == ["pull request"]


def test_surfaces_named_lists_every_match_once_in_table_order():
    text = _design(named="a merge gate plus a pull request plus another merge gate")
    assert forge_floor.surfaces_named(text) == ["pull request", "merge gate"]


# ---------------------------------------------------------------------------
# required() / warning() -- the predicate and the line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("floor,klass,expected", [
    ("3", "light", True), ("3", "full", True), ("3", "spike", True),
    ("3", None, True), ("4", "light", True),
    ("3", "just-do-it", False), ("2", "light", False), (None, "light", False),
    ("two", "light", False),
])
def test_required_truth_table(floor, klass, expected):
    assert forge_floor.required(_design(floor=floor, klass=klass)) is expected


def test_required_false_without_a_surface():
    assert forge_floor.required(_design(named=None)) is False


def test_warning_is_none_when_the_section_blocks_or_is_present():
    blocking = _design()
    assert forge_floor.warning(blocking, {}) is None
    assert forge_floor.warning(_design(klass="just-do-it"), {SECTION: "body"}) is None
    assert forge_floor.warning(_design(named=None, klass="just-do-it"), {}) is None


def test_warning_names_the_surface_and_the_section():
    line = forge_floor.warning(_design(klass="just-do-it"), {})
    assert line is not None and "\n" not in line
    assert NAMED in line and SECTION in line


# ---------------------------------------------------------------------------
# Both validators agree
# ---------------------------------------------------------------------------


def test_extra_required_adds_the_forge_section_only_when_required():
    assert floor_sections.extra_required(_design()) == [
        floor_sections.CONSUMER_REPO_SECTION, SECTION]
    assert floor_sections.extra_required(_design(named=None)) == [
        floor_sections.CONSUMER_REPO_SECTION]
    assert floor_sections.extra_required(_design(floor="2")) == [
        floor_sections.CONSUMER_REPO_SECTION]


@pytest.mark.parametrize("kwargs,blocked", [
    ({}, True),
    ({"forge": _FORGE_BODY}, False),
    ({"forge": "## Forge behaviour\nTBD\n"}, True),
    ({"klass": "just-do-it"}, False),
    ({"floor": "2"}, False),
    ({"named": None}, False),
], ids=["missing", "present", "placeholder", "just-do-it", "floor2", "no-surface"])
def test_validate_artifact_agrees_with_validate_design_floor(tmp_path, kwargs, blocked):
    text = _design(**kwargs)
    code, _ = _run(tmp_path, text)
    result = validate_artifact("design", tmp_path / "design.md")
    assert (code == 1) is blocked
    assert (result.verdict == "BLOCKED") is blocked
    if blocked:
        assert SECTION in {v.location for v in result.violations}


def test_blocked_verdict_stays_the_only_stderr_output(tmp_path):
    """A blocked design prints the JSON line alone -- no stray forge warning."""
    code, err = _run(tmp_path, _design())
    assert code == 1
    assert len(err.strip().splitlines()) == 1
    json.loads(err)
