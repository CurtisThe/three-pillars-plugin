"""Frozen-round tests for `fix_round.run_round(frozen=, follow_up_dir=)`.

design: review-convergence (Task 5.6, detailed-design-pr-loop §D2, Behavior 9)

After a clean round the loop freezes its review bar: `round_freeze.partition`
keeps only structural (blocking) fixes and defers the rest. These tests pin the
three consequences in `run_round` — a minor-only round under a freeze commits
nothing and lands its item in `follow-up.json`; a structural finding after the
freeze is still fixed and pushed; and an unfrozen round behaves byte-identically
to before (reason `minor-only`, no follow-up store touched).

Fixtures follow `test_fix_round_paths.py`: a real tmp git repo, `git push` and
`ensure_pr_label` stubbed, findings stamped `source == "code-review"` so the
identity gate passes without a `gh` call.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fix_round  # noqa: E402

PR = "https://github.com/o/r/pull/3"
_REAL_RUN = subprocess.run


def _minor():
    return {"source": "code-review", "comment_id": "c-minor", "reviewer": "",
            "verdict": "minor", "issue_phrase": "rename x", "file": "src/a.py"}


def _structural():
    return {"source": "code-review", "comment_id": "c-block", "reviewer": "",
            "verdict": "structural", "issue_phrase": "fix a", "file": "src/a.py"}


def _git(cwd, *args):
    return _REAL_RUN(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "feat")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(argv, *a, **kw):
        calls.append(list(argv))
        if list(argv[:2]) == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return _REAL_RUN(argv, *a, **kw)

    monkeypatch.setattr(fix_round.subprocess, "run", run)
    monkeypatch.setattr(fix_round, "ensure_pr_label", lambda *a, **k: None)
    return tmp_path, calls


def _rounds_dir(tmp_path) -> Path:
    """The `<proof_root>/rounds/<pr>` dir the loop hands to `follow_up_dir`."""
    d = tmp_path / "proof" / "rounds" / "3"
    d.mkdir(parents=True)
    return d


def _stored(rounds_dir: Path) -> list:
    return json.loads((rounds_dir / "follow-up.json").read_text(encoding="utf-8"))


def _head(repo_root) -> str:
    return _git(repo_root, "rev-parse", "HEAD").stdout.strip()


def test_frozen_minor_only_no_commit_and_item_in_follow_up(repo, tmp_path):
    """Behavior 9: frozen + minor-only → `no-applicable-fixes`, nothing committed,
    the item deferred as `frozen-follow-up` and stored in follow-up.json."""
    root, calls = repo
    before = _head(root)
    rounds_dir = _rounds_dir(tmp_path)
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("d", PR, 4, [_minor()], head_ref="feat", loop_mode=True,
                              paths=["src/a.py"], frozen=True,
                              follow_up_dir=str(rounds_dir))

    assert env["verdict"] == "no-applicable-fixes"
    assert env["fixes_applied"] == []
    assert env["fixes_deferred"] == [{"comment_id": "c-minor",
                                      "reason": "frozen-follow-up"}]
    assert not any(c[:2] == ["git", "commit"] for c in calls)
    assert not any(c[:2] == ["git", "push"] for c in calls)
    assert _head(root) == before
    stored = _stored(rounds_dir)
    assert [s["comment_id"] for s in stored] == ["c-minor"]
    assert stored[0]["reason"] == "frozen-follow-up"


def test_frozen_structural_finding_is_still_fixed(repo, tmp_path):
    """The freeze defers non-blocking notes only — a blocker found after the
    freeze still gets its commit, push and label."""
    root, calls = repo
    rounds_dir = _rounds_dir(tmp_path)
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("d", PR, 5, [_structural()], head_ref="feat",
                              loop_mode=True, paths=["src/a.py"], frozen=True,
                              follow_up_dir=str(rounds_dir))

    assert env["verdict"] == "applied"
    assert env["fixes_applied"] == [{"comment_id": "c-block", "summary": "fix a"}]
    assert env["fixes_deferred"] == []
    assert any(c[:2] == ["git", "commit"] for c in calls)
    assert ["git", "push"] in calls
    assert not (rounds_dir / "follow-up.json").exists()


def test_frozen_mixed_round_fixes_blocker_defers_minor(repo, tmp_path):
    """One round, both kinds: the blocker is committed, the minor note goes to the
    follow-up store — the freeze never swallows the blocker."""
    root, calls = repo
    rounds_dir = _rounds_dir(tmp_path)
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("d", PR, 6, [_minor(), _structural()], head_ref="feat",
                              loop_mode=True, paths=["src/a.py"], frozen=True,
                              follow_up_dir=str(rounds_dir))

    assert env["verdict"] == "applied"
    assert [f["comment_id"] for f in env["fixes_applied"]] == ["c-block"]
    assert env["fixes_deferred"] == [{"comment_id": "c-minor",
                                      "reason": "frozen-follow-up"}]
    assert any(c[:2] == ["git", "commit"] for c in calls)
    assert [s["comment_id"] for s in _stored(rounds_dir)] == ["c-minor"]


def test_not_frozen_is_unchanged_and_writes_no_follow_up(repo, tmp_path):
    """Unfrozen behaviour is byte-identical to today: the minor item is deferred
    with `minor-only`, and the follow-up store is never created."""
    root, _calls = repo
    rounds_dir = _rounds_dir(tmp_path)
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("d", PR, 7, [_minor()], head_ref="feat", loop_mode=True,
                              paths=["src/a.py"], follow_up_dir=str(rounds_dir))

    assert env["verdict"] == "no-applicable-fixes"
    assert env["fixes_deferred"] == [{"comment_id": "c-minor", "reason": "minor-only"}]
    assert not (rounds_dir / "follow-up.json").exists()


def test_frozen_without_follow_up_dir_still_reports_deferred(repo):
    """A frozen round with no place to store the note must not drop it silently —
    it still appears in `fixes_deferred`."""
    root, _calls = repo
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("d", PR, 8, [_minor()], head_ref="feat", loop_mode=True,
                              paths=["src/a.py"], frozen=True)

    assert env["verdict"] == "no-applicable-fixes"
    assert env["fixes_deferred"] == [{"comment_id": "c-minor",
                                      "reason": "frozen-follow-up"}]
