"""Prose pins for the four-line launch precedence (launch-role-precedence Task 1.8).

design-run-launch.md states the precedence in order — this launch's flags, the role,
routes.conf, never the parent session's env — names the `run` role and the `seat`
fallback, and no longer claims the window pins the seat's profile or `CLAUDE_CONFIG_DIR`.
Token pins only (test-fragility.md).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "skills" / "_shared" / "design-run-launch.md"
FLAGS = ROOT / "skills" / "_shared" / "design-run-launch-flags.md"


def _flat(p: Path) -> str:
    return " ".join(p.read_text(encoding="utf-8").split())


def test_rule_doc_states_the_precedence_in_order():
    body = _flat(RULE)
    order = ["flags passed on this launch", "the role", "routes.conf",
             "never the parent session's env"]
    assert [body.index(o) for o in order] == sorted(body.index(o) for o in order)


def test_rule_doc_names_the_run_role_and_seat_fallback():
    body = _flat(RULE)
    assert "role `run`" in body
    assert "Remote Control" in body
    assert "falls back to `seat`" in body


def test_rule_doc_no_longer_pins_the_seat_profile():
    body = _flat(RULE)
    assert "CLAUDE_LAUNCHER_FORCE_PROFILE" not in body
    assert "pins `CLAUDE_CONFIG_DIR`" not in body


def test_rule_doc_stays_within_its_line_pin():
    assert len(RULE.read_text(encoding="utf-8").splitlines()) <= 120


def test_flags_doc_mirrors_one_precedence_line():
    assert "never the parent session's env" in _flat(FLAGS)
