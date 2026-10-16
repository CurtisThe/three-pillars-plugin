"""Token pins for the seat's design-run launch rule (design-run-launch-fixes Task 1.8).

The rule ("launch through launch_design_run.py, never a hand-written tmux
new-session; --local-mode wait") is in all three repo CLAUDE templates, the
launch doc names the new flags, and L208 / architecture.md record the S4
waiver with the config key set. Token pins only (test-fragility.md).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import certify_issues

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ("CLAUDE.md", "CLAUDE.plugin.md", "CLAUDE.pro.md")
LAUNCH_DOCS = (ROOT / "skills" / "_shared" / "design-run-launch.md",
               ROOT / "skills" / "_shared" / "design-run-launch-flags.md")


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_carries_the_launch_rule(name):
    body = _flat(ROOT / name)
    assert "Launching design runs" in body
    for token in ("launch_design_run.py", "skills/_shared/design-run-launch.md",
                  "tmux new-session", "--local-mode wait"):
        assert token in body, (name, token)
    rule = body[body.index("Launching design runs"):][:900].lower()
    assert "never" in rule and "hand-written" in rule


def test_launch_doc_names_the_new_flags():
    body = " ".join(_flat(p) for p in LAUNCH_DOCS if p.exists())
    for token in ("--local-mode", "TP_LOCAL_MODE", "CLAUDE_LAUNCHER_FORCE_PROFILE",
                  "CLAUDE_LAUNCHER_OWNED", "design_run_backend", "--worktree"):
        assert token in body, token


def test_l208_and_architecture_record_the_waiver():
    # L208 is a Low: it lives in the cold `known_issues_low.md`, so the pin reads
    # every live issue doc (the Task 2.1 tuple), not just `known_issues.md`.
    issues = " ".join(
        _flat(ROOT / rel) for rel in certify_issues.LIVE_ISSUE_DOCS
        if (ROOT / rel).exists())
    entry = issues[issues.index("### L208"):][:1500]
    assert "waived" in entry.lower() and 'design_run_backend: "direct"' in entry
    arch = _flat(ROOT / "three-pillars-docs" / "architecture.md")
    assert "waived" in arch.lower() and "design-run-launch-fixes" in arch
