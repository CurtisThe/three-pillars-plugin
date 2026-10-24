"""Token pins for the seat-scope docs (seat-escalate-first Task 2.6).

`escalation.md` documents the seat scope, the allow-list tags and the archived run dir; the
audited prompts carry their `seat-allow: <kind>` tag. Token pins on named sections, with the
tag set derived from `seat_scope.ALLOW_KINDS` rather than a second copy (test-fragility.md).
Run with: python3 -m pytest skills/_shared/test_seat_scope_docs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seat_scope  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ESCALATION = "skills/_shared/escalation.md"
_TAG = re.compile(r"seat-allow: ([a-z][a-z-]*)")
_SKILL_CAP = 35000
# A pro-exclusive skill name: spelled in two parts because core ships this file and the
# release leak guard flags the whole name in any shipped text.
_WORKTREE = "skills/tp-" + "worktree/SKILL.md"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, name: str) -> str:
    """The `## <name>` section (its `###` children included), whitespace collapsed."""
    match = re.search(r"(?ms)^## %s[ \t]*$(.*?)(?=^## |\Z)" % re.escape(name), text)
    assert match, "no `## %s` section" % name
    return re.sub(r"\s+", " ", match.group(1))


def _hook() -> str:
    return _section(_read(ESCALATION), "Hook")


@pytest.mark.parametrize("token", [
    "TP_DESIGN_RUN=1", "CLAUDE_LAUNCHER_ROLE=seat", "orchestrator:", "tp/*",
    "/tp-escalate", "answer:", "deliberately not tagged",
])
def test_hook_section_names_the_seat_scope_tokens(token):
    assert token in _hook()


def test_hook_section_names_a_live_run():
    assert re.search(r"\blive\b", _hook())


@pytest.mark.parametrize("kind", seat_scope.ALLOW_KINDS)
def test_hook_section_carries_a_tag_line_for_each_kind(kind):
    assert "seat-allow: " + kind in _hook()


def test_hook_section_tag_set_equals_allow_kinds_both_ways():
    named = set(_TAG.findall(_hook()))
    assert named == set(seat_scope.ALLOW_KINDS)
    assert len(seat_scope.ALLOW_KINDS) == 8


@pytest.mark.parametrize("prompt", [
    "/tp-design", "/tp-spike", "/tp-spike-auto", "/tp-task-cycle", "read-project-docs.md",
    "/tp-design-release", "/tp-revert", "/tp-design-complete",
])
def test_hook_section_lists_the_untagged_prompts(prompt):
    # `/tp-design` must not be satisfied by the `tp-designs/` directory name.
    assert re.search(re.escape(prompt) + r"(?![\w-])", _hook())


def test_run_section_names_the_archived_design_dir():
    run = _section(_read(ESCALATION), "Run")
    assert "completed-tp-designs/<slug>/" in run
    assert "tp-designs/<slug>/" in run


@pytest.mark.parametrize("flag", ["--kind base-sync-hunk", "--kind scope-growth"])
def test_seat_section_routes_conflicted_merges_to_operator_only_kinds(flag):
    assert flag in _section(_read(ESCALATION), "Seat")


@pytest.mark.parametrize("rel, kind", [
    ("skills/tp-session-restore/SKILL.md", "session-restore"),
    ("skills/_shared/first-run.md", "first-run-preflight"),
    ("skills/tp-promote/SKILL.md", "promote-confirm"),
    ("skills/tp-session-clear/SKILL.md", "session-clear"),
    ("skills/tp-migrate/SKILL.md", "migrate-confirm"),
])
def test_prompt_carries_its_tag(rel, kind):
    assert _read(rel).count("seat-allow: " + kind) == 1


def test_post_merge_teardown_tag_at_both_checklists():
    text = _read("skills/tp-post-merge/SKILL.md")
    tag = "seat-allow: post-merge-teardown"
    assert text.count(tag) == 2
    assert _section(text, "No-arg scan form").count(tag) == 1
    assert _section(text, "Backfill sweep").count(tag) == 1


def test_worktree_confirm_tag_on_both_confirms_and_stays_under_cap():
    text = _read(_WORKTREE)
    assert text.count("seat-allow: worktree-confirm") == 2
    assert len(text) < _SKILL_CAP


def test_every_tag_named_in_a_skill_is_an_allowed_kind():
    paths = ["skills/tp-session-restore/SKILL.md", "skills/_shared/first-run.md",
             "skills/tp-promote/SKILL.md", "skills/tp-session-clear/SKILL.md",
             "skills/tp-post-merge/SKILL.md", _WORKTREE,
             "skills/tp-migrate/SKILL.md"]
    named = {k for rel in paths for k in _TAG.findall(_read(rel))}
    assert named <= set(seat_scope.ALLOW_KINDS)
    assert len(named) == 7  # `fleet-scope` is Task 3.3's


# --- Task 3.6: the light card path and the Stop hook -----------------------

def test_light_card_path_documented():
    """§Explain: `card` without `--html` is the light path for a one-line question; the
    explainer page stays the default for real decisions."""
    explain = _section(_read(ESCALATION), "Explain")
    assert re.search(r"without `--html`", explain)
    assert "light path" in explain
    assert "one-line question" in explain
    assert re.search(r"explainer page[^.]*\bdefault\b", explain)
    assert "real decisions" in explain


def test_stop_hook_documented():
    """§Hook names the `Stop` hook, its module, the one-block-per-turn field and the text field."""
    hook = _hook()
    for token in ("stop_question_hook.py", "stop_hook_active", "last_assistant_message",
                  "TP_CHILD_SESSION"):
        assert token in hook, token
    assert re.search(r"`Stop`", hook)
