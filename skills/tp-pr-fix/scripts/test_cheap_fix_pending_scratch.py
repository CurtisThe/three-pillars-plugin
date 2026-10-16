"""cheap_fix: an accepted adopt re-baselines every other pending scratch (PR #191 r3).

Two scratches cut before the first adopt: the second adopt must neither undo the first
accepted fix nor blame its drafter for it, and a drafter write to that file afterwards
is still caught. A snapshot that cannot be re-baselined fails closed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_fix  # noqa: E402
from test_cheap_fix import GREEN, PY, _finding, _git, _head, repo  # noqa: E402,F401


def _finding_for(name: str) -> dict:
    check = (f"import pathlib; raise SystemExit(0 if pathlib.Path('{name}')"
             ".read_text(encoding='utf-8') == 'fixed' else 1)")
    return _finding(file=name, reproducer={"kind": "command", "argv": [PY, "-c", check],
                                           "expect": {"exit": 0}})


def _two_scratches(repo):
    sa, sb = cheap_fix.scratch(repo, _head(repo)), cheap_fix.scratch(repo, _head(repo))
    (sa / "a.py").write_text("fixed", encoding="utf-8")
    (sb / "b.py").write_text("fixed", encoding="utf-8")
    va = cheap_fix.adopt(sa, repo, _finding_for("a.py"), test_argv=GREEN)
    assert va["action"] == "accept", va
    return sb


def test_a_second_adopt_keeps_the_first_accepted_fix(repo):
    sb = _two_scratches(repo)
    vb = cheap_fix.adopt(sb, repo, _finding_for("b.py"), test_argv=GREEN)
    assert vb["action"] == "accept", vb
    assert (repo / "a.py").read_text(encoding="utf-8") == "fixed"
    assert (repo / "b.py").read_text(encoding="utf-8") == "fixed"


def test_a_drafter_write_over_the_accepted_fix_is_still_caught(repo):
    sb = _two_scratches(repo)
    (repo / "a.py").write_text("weakened", encoding="utf-8")  # drafter B, live tree
    vb = cheap_fix.adopt(sb, repo, _finding_for("b.py"), test_argv=GREEN)
    assert vb["action"] == "escalate", vb
    assert vb["reason"].startswith("drafter-wrote-live-tree: a.py"), vb
    assert (repo / "a.py").read_text(encoding="utf-8") == "fixed"  # A's fix, not HEAD's
    assert (repo / "b.py").read_text(encoding="utf-8") == "b"


def test_a_snapshot_that_cannot_be_rebased_fails_closed(repo, monkeypatch):
    def broken(root, store, paths):
        raise cheap_fix.live_tree_guard.GuardError("unreadable")

    monkeypatch.setattr(cheap_fix.live_tree_guard, "rebase", broken)
    sb = _two_scratches(repo)
    vb = cheap_fix.adopt(sb, repo, _finding_for("b.py"), test_argv=GREEN)
    assert vb["action"] == "escalate" and "unobservable" in vb["reason"], vb
    assert (repo / "a.py").read_text(encoding="utf-8") == "fixed"
