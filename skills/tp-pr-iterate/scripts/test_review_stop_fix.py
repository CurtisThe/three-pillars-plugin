"""A review-stop `fix` commits on a frozen bar; an ordinary frozen note still defers.

design: seat-escalate-first (Task 1.3). A converging round is clean, so the bar is
frozen and `fix_round` keeps only `verdict == "structural"`. `review_stop.settle`
re-tags the leftover notes for the inline-fix contract, so they commit unchanged
through `fix_round.run_round(frozen=True)`; the same note as reviewed (`minor`)
still goes to `follow-up.json`. `fix_round.py` and `round_freeze.py` are untouched.

Harness copied from `skills/tp-pr-fix/scripts/test_fix_round_frozen.py`: a real tmp
git repo, `git push` and `ensure_pr_label` stubbed, no `gh` call.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SKILLS = _HERE.parents[1]
for _p in (_HERE, _SKILLS / "_shared", _SKILLS / "tp-pr-fix" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import finalizer_ruling  # noqa: E402
import fix_round  # noqa: E402
import iterate_state  # noqa: E402
import review_stop  # noqa: E402
import ruling_file  # noqa: E402

PR = "https://github.com/o/r/pull/3"
_REAL_RUN = subprocess.run
NOTE = {"source": "code-review", "comment_id": "c-minor", "reviewer": "",
        "verdict": "minor", "issue_phrase": "rename x", "summary": "rename x",
        "file": "src/a.py"}


def _git(cwd, *args):
    return _REAL_RUN(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    monkeypatch.chdir(root)
    calls = []

    def run(argv, *a, **kw):
        calls.append(list(argv))
        if list(argv[:2]) == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return _REAL_RUN(argv, *a, **kw)

    monkeypatch.setattr(fix_round.subprocess, "run", run)
    monkeypatch.setattr(fix_round, "ensure_pr_label", lambda *a, **k: None)
    return root, calls


def _rounds_dir(tmp_path) -> Path:
    d = tmp_path / "proof" / "rounds" / "3"
    d.mkdir(parents=True)
    return d


def _head(root) -> str:
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _settle_notes(tmp_path) -> list:
    """`settle`'s fix notes for NOTE, from a resolved `fix` ruling outside the repo."""
    aux = tmp_path / "aux"
    aux.mkdir()
    head = "cd" * 20
    stop = review_stop.due({}, [NOTE], pr_url=PR, head=head)
    ruling = {**finalizer_ruling.EMPTY_RULING, "options": [
        {"id": "stop", "label": "Stop here", "description": "s", "recommended": False},
        {"id": "fix", "label": "Fix these notes first", "description": "f",
         "recommended": True}]}
    rid = ruling_file.write(aux, scope="demo", entry="run", stop=stop, key="k",
                            result={"outcome": "resolved", "ruling": ruling},
                            model="fable", at="2026-10-21T00:00:00Z").stem
    state = iterate_state.fresh_state(now="2026-10-21T00:00:00+00:00")
    state.update(iteration=1, last_codereview_head_sha=head,
                 last_codereview_findings=[NOTE], frozen_at="2026-10-21T00:00:00+00:00")
    state_path = aux / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    out = review_stop.settle(aux, rid, state_path=state_path,
                             decisions=aux / "decisions.md")
    assert out["action"] == "fix"
    return out["notes"]


def test_settle_fix_notes_commit_on_a_frozen_bar(repo, tmp_path):
    root, calls = repo
    notes = _settle_notes(tmp_path)
    rounds_dir = _rounds_dir(tmp_path)
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("demo", PR, 4, classified=notes, head_ref="feat",
                              loop_mode=True, paths=["src/a.py"], frozen=True,
                              follow_up_dir=str(rounds_dir))

    assert env["verdict"] == "applied"
    assert env["fixes_deferred"] == []
    subject = _git(root, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("[tp-pr-fix iter-4]")
    assert ["git", "push"] in calls
    assert not (rounds_dir / "follow-up.json").exists()


def test_same_note_as_reviewed_still_defers_on_a_frozen_bar(repo, tmp_path):
    root, calls = repo
    before = _head(root)
    rounds_dir = _rounds_dir(tmp_path)
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    env = fix_round.run_round("demo", PR, 4, classified=[dict(NOTE)], head_ref="feat",
                              loop_mode=True, paths=["src/a.py"], frozen=True,
                              follow_up_dir=str(rounds_dir))

    assert env["verdict"] == "no-applicable-fixes"
    assert not any(c[:2] == ["git", "commit"] for c in calls)
    assert _head(root) == before
    stored = json.loads((rounds_dir / "follow-up.json").read_text(encoding="utf-8"))
    assert [s["comment_id"] for s in stored] == ["c-minor"]
