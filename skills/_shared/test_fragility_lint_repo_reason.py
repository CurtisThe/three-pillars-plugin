"""test_fragility_lint_repo_reason.py — a per-repo rule's hit prints its own reason.

design: prose-pin-gate (design §Behaviors 3)

Every case is a source string parsed here and run through `fragility_lint.lint_source`
with one hand-built `RepoRule` row, so the reason travels the core rather than the CLI.
A hit from a per-repo rule renders that rule's `reason` text (the fixture's own string,
never wording from a doc); a hit from a generic rule still renders its registry summary.
Nothing here asserts on the wording of any `.md` file.
"""
from __future__ import annotations

import fragility_lint
from fragility_registry import RULES
from fragility_repo_rules import RepoRule

TEST_PATH = "test_x.py"
REASON = "the repo pins this call by name, not by prose"
REPO_ID = "no-direct-subprocess"
SUMMARIES = {rule.id: rule.summary for rule in RULES}

FORBIDDEN_CALL_SRC = """import subprocess
def test_a():
    subprocess.run(["true"])
"""

MD_READ_ASSERT_SRC = """def test_a():
    text = Path("skills/x/SKILL.md").read_text(encoding="utf-8")
    assert "tp-merge" in text
"""


def repo_rule(gating: bool = True) -> RepoRule:
    return RepoRule(id=REPO_ID, kind="forbidden-call", params={"call": "subprocess.run"},
                    reason=REASON, approved_by="Curtis", date="2026-10-15", gating=gating)


def test_a_per_repo_hit_renders_its_own_reason():
    hits = fragility_lint.lint_source(TEST_PATH, FORBIDDEN_CALL_SRC, repo=[repo_rule()])
    hit = next(h for h in hits if h.rule_id == REPO_ID)
    assert hit.gating
    assert REASON in fragility_lint.render(hit)


def test_a_generic_hit_still_renders_its_registry_summary():
    hits = fragility_lint.lint_source(TEST_PATH, MD_READ_ASSERT_SRC)
    hit = next(h for h in hits if h.rule_id == "md-read-assert")
    assert SUMMARIES["md-read-assert"] in fragility_lint.render(hit)
