"""Prose pins for the launch defaults in design-run-launch.md (design-run-launch-defaults).

The rule doc names the TP_LOCAL precedence, the committed seat brief and its first line,
the delivery and watcher tools, and that they never kill; the launcher wording in the rule
doc, the pro fleet skill (when shipped) and architecture.md says a design run opens a tmux *session*, not a window.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_brief  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "skills" / "_shared" / "design-run-launch.md"
# the pro-tier fleet skill is absent from free-tier trees (release leak guard): find it by glob
FLEET = next(iter(sorted(ROOT.glob("skills/*fleet/SKILL.md"))), None)
ARCH = ROOT / "three-pillars-docs" / "architecture.md"


def _flat(p: Path) -> str:
    return " ".join(p.read_text(encoding="utf-8").split())


def test_rule_doc_names_the_launch_defaults():
    body = _flat(RULE)
    assert "`--local` / `--no-local` > `TP_LOCAL` > `local_implement.default_run_flag` > off" in body
    for token in ("TP_LOCAL", "--brief", "seat-brief.md", design_run_brief.FIRST_LINE,
                  "design_run_send.py", "design_run_watch.py", "never kills", "--wait"):
        assert token in body, token
    assert len(RULE.read_text(encoding="utf-8").splitlines()) <= 120


def test_rule_doc_states_the_brief_source_order_and_wait_zero():
    body = _flat(RULE)
    order = ["`--brief` file", "design dir's `seat-brief.md`", "`.three-pillars/seat-brief.md`",
             "shipped `seat-brief-template.md`"]
    assert [body.index(o) for o in order] == sorted(body.index(o) for o in order)
    assert "`--wait 0`" in body and "routing" in body


def test_no_doc_describes_a_design_run_as_opening_a_window():
    for doc in (RULE, FLEET, ARCH):
        if doc is not None:
            assert "opens a detached tmux window" not in _flat(doc), doc.name
    if FLEET is not None:
        fleet = _flat(FLEET)
        assert "fresh tmux window" not in fleet and "separate `<design>` window" not in fleet
    assert "tmux session" in _flat(ARCH).split("launch_design_run.py <slug>")[1][:400]
