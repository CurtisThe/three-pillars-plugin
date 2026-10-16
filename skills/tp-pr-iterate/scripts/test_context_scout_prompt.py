"""Tests for context_scout.py — sources, scout agent, prompt.

design: local-role-routing (Task 5.1)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_scout  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


def _prompt(tmp_path, *, live=False, archived=False):
    if live:
        (tmp_path / "tp-designs" / "d").mkdir(parents=True)
    if archived:
        (tmp_path / "completed-tp-designs" / "d").mkdir(parents=True)
    return context_scout.prompt(str(tmp_path / "tp-designs" / "d"), "BASE", "HEAD", "/out/dir")


def test_sources_cover_repo_only_inputs():
    text = " ".join(context_scout.SOURCES).lower()
    for needle in ("design.md", "non-goals", "decisions.md", "operator rulings", "vision",
                   "architecture", "known_issues", "pr body"):
        assert needle in text


def test_scout_agent_is_confirmer_with_bash():
    assert context_scout.SCOUT_AGENT == "tp-review-confirmer"
    fm = (REPO / "agents" / "tp-review-confirmer.md").read_text(encoding="utf-8").split("---")[1]
    tools = re.search(r"^tools:\s*\[(.*)\]", fm, re.M).group(1)
    assert '"Bash"' in tools and '"Write"' not in tools


def test_prompt_contract(tmp_path):
    p = _prompt(tmp_path, live=True)
    assert str(tmp_path / "tp-designs" / "d") in p
    assert "25" in p
    assert context_scout.SLOT_LOSS_SUFFIX in p
    assert "context_scout.py put --out-dir /out/dir" in p
    assert "<<'EOF'" in p
    assert '{"block": ..., "files": [...]}' in p
    assert "git diff --name-only BASE...HEAD" in p


def test_archived_design_dir_named(tmp_path):
    p = _prompt(tmp_path, archived=True)
    assert str(tmp_path / "completed-tp-designs" / "d") in p


def test_no_design_dir(tmp_path):
    assert "no design dir found" in _prompt(tmp_path)
