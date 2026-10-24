"""Doc pins: Tier 5.6 calls fold_union.py before giving up on a fold conflict.

design: closeout-fold-and-sweep 1.3. Load-bearing literals only.
"""
from __future__ import annotations

from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "tier-5-closeout.md"


def _text() -> str:
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def _step1_bullet() -> str:
    lines = [l for l in _text().splitlines() if l.startswith("- **Fold conflict**")]
    assert len(lines) >= 2
    return lines[0]


def test_literals_present():
    t = _text()
    for lit in ("fold_union.py --slug {slug}", "git commit --no-edit",
                "fold-decisions-union", "decisions.md"):
        assert lit in t, lit


def test_abort_follows_script_in_step1():
    b = _step1_bullet()
    assert "fold_union.py" in b and "git merge --abort" in b
    assert b.index("fold_union.py") < b.index("git merge --abort")


def test_step1_script_already_recorded_no_second_log():
    b = _step1_bullet()
    assert "already recorded" in b
    assert b.count("fold-decisions-union") <= 1


def test_outcomes_bullet_names_script():
    outcome = [l for l in _text().splitlines() if l.startswith("- **Fold conflict**")][-1]
    assert "fold_union.py" in outcome


def test_never_auto_resolve_narrowed():
    assert "Never auto-resolve anything but" in _text()
