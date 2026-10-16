"""Structured checks for `/tp-pr-fix` SKILL.md and the contracts it documents.

The old prose pins (commit prefix, label name, committer email, standalone,
structured-extraction, trusted-bot gate, head-ref) are gone: the code side of each
is checked on the module's own API below, the behaviour is owned by test_fix_round.py
and test_label_manager.py, and any path/skill reference is covered by invariant 46
(`skill_refs`). SKILL.md is read only through shipped parsers.

Run with: pytest skills/tp-pr-fix/scripts/test_pr_fix_skill_md.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).parent.parent / "SKILL.md"
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / "_shared"))

import fix_round  # noqa: E402


def test_commit_prefix_and_label_contract():
    # owner: test_fix_round.py::test_end_to_end_with_stub_gh (prefix on a real commit)
    assert fix_round._commit_message(3, "x").startswith("[tp-pr-fix iter-3]")
    assert fix_round._FIX_LABEL == "tp:do-not-merge-yet"


def test_committer_identity_override_contract(monkeypatch):
    # owner: test_fix_round.py::test_commit_uses_orchestrator_committer_email
    env = fix_round._resolve_committer_env()
    assert set(env) == {"GIT_COMMITTER_EMAIL", "GIT_COMMITTER_NAME"}


def test_trusted_bot_env_extends_allowlist(monkeypatch):
    # owner: test_fix_round.py::test_trusted_bots_env_var_extends_allowlist
    monkeypatch.setenv("TP_PR_FIX_TRUSTED_BOTS", "MyBot")
    assert "mybot" in fix_round._trusted_reviewer_bots()


def test_skill_frontmatter_and_refs_clean():
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    skill_refs = pytest.importorskip("skill_refs")
    assert skill_frontmatter.check(SKILL_MD) == []
    fields, issues = skill_frontmatter.parse(SKILL_MD.read_text(encoding="utf-8"))
    assert not issues and fields["name"][1] == "tp-pr-fix"
    report = skill_refs.check(SKILL_MD.parents[2], [SKILL_MD])
    assert not report.issues, report.issues


def test_cheap_tier_stubs_leave_todays_calls_intact():
    """cheap-tier-offload 6.4: the two stubs fence around today's classifier and fix
    dispatches, never inside them, so both recorded exemption needles still match."""
    import json
    import re

    import pytest

    exemptions_path = SKILL_MD.parents[1] / "_shared" / "dispatch_exemptions.json"
    if not exemptions_path.is_file():  # dev-only: never in the core ship
        pytest.skip("no dispatch_exemptions.json in this tree")

    body = SKILL_MD.read_text(encoding="utf-8")
    stubs = [m.span() for m in re.finditer(
        r"<!-- cheap-tier:(\w+) -->.*?<!-- /cheap-tier -->", body, re.S)]
    assert len(stubs) == 2
    exemptions = json.loads(exemptions_path.read_text(encoding="utf-8"))[
        "skills/tp-pr-fix/SKILL.md"]
    for entry in exemptions:
        at = body.index(entry["needle"])
        assert not any(s <= at < e for s, e in stubs), entry["needle"]
