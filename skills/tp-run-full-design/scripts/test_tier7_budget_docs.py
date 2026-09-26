"""Tier 7 round-topology doc pins (iterate-convergence-budget Task 8.3, Q4).

Scoped to the text of Tier 7 `### Step 1`, not whole-file keywords, so a stray
mention elsewhere in the 1k-line SKILL.md cannot satisfy them.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
GRANDFATHERED_LINES = 1089  # grandfathered monolith: never grows net
GRANDFATHERED_CHARS = 120179  # len() of the pre-design text (chars, not bytes)


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _between(start: str, end: str) -> str:
    text = _text()
    i = text.index(start)
    return _flat(text[i:text.index(end, i)])


def _step1() -> str:
    return _between("### Step 1 — Orchestrator-owned round loop", "### Step 2 — Clip + log")


def _tier7() -> str:
    return _between("## Tier 7 — PR-iterate", "## Branch hygiene")


def _missing(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def test_step1_names_the_round_dir_flow_in_order():
    step1 = _step1()
    order = ["round_scratch.py prepare", 'model="opus"', "reply_path",
             "reproduce.py --round-dir", "converge.py --round-dir", "run_round.py"]
    assert not _missing(step1, *order)
    idx = [step1.index(s) for s in order]
    assert idx == sorted(idx), f"out of order: {list(zip(order, idx))}"


def test_step1_run_round_stdin_carries_the_round_identity():
    step1 = _step1()
    assert not _missing(step1, "`pr_url`", "`round`", "`ordinal`", "`class_log_path`",
                        "`review_base`")
    assert "the base-branch tip, re-fetched every round" in step1


def test_step1_fix_is_the_inline_fix_with_derived_paths():
    step1 = _step1()
    assert not _missing(step1, "fix_round.run_round(", "paths=", "tree_scope.derive_fix_paths")


def test_tier7_has_no_worktree_isolated_pr_fix_dispatch():
    assert not re.search(r"/tp-pr-fix[^.]{0,200}isolation=\"worktree\"", _tier7())


def test_uncapped_paragraph_replaced_by_the_round_budget():
    tier7 = _tier7()
    assert "UNCAPPED" not in tier7 and "run_loop" not in tier7
    assert not _missing(tier7, "round_cap", "budget-exhausted", "path authority", "tail-check",
                        "round_scratch.py flush", "pdw.guards.round_cap",
                        "pr-iterate-budget-exhausted")


def test_round_tail_is_the_one_working_tree_writer():
    slot11 = _between("### Slot 11 — `pr-iterate`", "### Light slot mapping")
    rule2 = _between("2. **Any slot needing", "3. **Assert before every orchestrator commit.**")
    for where, text in (("slot 11", slot11), ("step 1", _step1()), ("rule 2", rule2)):
        assert not _missing(text, "round tail", "one working-tree writer", "`tp/{slug}`"), where
    assert "never checks out" in rule2 and "idle" in rule2
    assert "3. **Assert before every orchestrator commit.**" in _text()


def test_two_stable_flush_is_committed_but_not_pushed():
    tier7 = _tier7()
    assert "committed locally and **not pushed**" in tier7
    assert "exception to commit-then-push" in tier7


def test_non_two_stable_terminal_reports_dirty_decisions_md():
    assert "`decisions.md` as modified and uncommitted" in _tier7()


def test_skill_md_does_not_grow_net():
    text = _text()
    assert len(text.splitlines()) <= GRANDFATHERED_LINES
    assert len(text) <= GRANDFATHERED_CHARS
