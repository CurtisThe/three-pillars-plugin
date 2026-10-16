"""test_task_verify_attempts.py — attempt lifecycle: owner records, dirty refusal, discard.

design: local-implement-and-review

Real tmp repos (``attempt_fixture``); the ambient repository's worktrees and branches
are never read or touched (M23).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

import task_attempts
from attempt_fixture import DD, agent_worktree, branches, git, make_seat, write


def _common(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def _record(att: dict) -> dict:
    return json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))


def _dirty_design_dir(repo: Path) -> None:
    write(repo, f"{DD}/lock.json", '{"owner": "me"}\n')
    with open(repo / DD / "decisions.md", "a", encoding="utf-8") as fh:
        fh.write("### entry\n")


# --- Task 4.2: owner records, snapshots, dirty refusal ----------------------------

def test_open_writes_owner_record(tmp_path, monkeypatch):
    seat, wt = make_seat(tmp_path)
    agent = agent_worktree(seat)
    git(seat, "update-ref", "refs/remotes/origin/main", "HEAD")
    seen = {}
    real_add = task_attempts._add_worktree

    def spy(top, rec):
        seen["during"] = _record(rec)
        seen["dir_before_add"] = os.path.isdir(rec["attempt_dir"])
        return real_add(top, rec)

    monkeypatch.setattr(task_attempts, "_add_worktree", spy)
    att = task_attempts.open_attempt(agent, "1.1", DD, guard_ref="tp/demo")
    rec_file = _common(seat) / "tp-attempts" / "demo" / f"{att['attempt_id'].split('/')[1]}.json"
    assert Path(task_attempts.record_path(att)) == rec_file
    assert seen["during"]["status"] == "opening"
    assert seen["dir_before_add"] is False
    rec = json.loads(rec_file.read_text(encoding="utf-8"))
    assert rec["status"] == "open"
    owner = rec["owner"]
    assert owner["dispatcher_root"] == os.path.realpath(agent)
    assert owner["pid"] == os.getpid() and owner["host"] and owner["started_at"]
    assert rec["guard_ref"] == "tp/demo"
    assert rec["guard_root"] == os.path.realpath(wt)
    assert rec["guard_sha"] == git(seat, "rev-parse", "tp/demo")
    assert rec["remotes_snapshot"] == {"refs/remotes/origin/main": git(seat, "rev-parse", "HEAD")}
    assert rec["dirty_snapshot"] == {"dispatcher": [], "guard_root": []}
    assert rec["dispatcher_branch"] == "candidate/demo/single"
    assert {k: rec[k] for k in att} == att


def test_open_refuses_dirty_outside_design_dir(tmp_path):
    _seat, wt = make_seat(tmp_path)
    write(wt, "skills/a.py", "A = 2\n")
    with pytest.raises(task_attempts.DirtyTree) as err:
        task_attempts.open_attempt(wt, "1.1", DD)
    assert err.value.paths == ["skills/a.py"]
    assert "skills/a.py" in str(err.value)
    assert branches(wt) == []
    assert not (wt / ".tp-scratch").exists()
    assert not (_common(wt) / "tp-attempts" / "demo").exists() or \
        not list((_common(wt) / "tp-attempts" / "demo").iterdir())


def test_open_adds_info_exclude_once(tmp_path):
    _seat, wt = make_seat(tmp_path)
    task_attempts.open_attempt(wt, "1.1", DD)
    task_attempts.open_attempt(wt, "1.2", DD)
    lines = (_common(wt) / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert lines.count("/.tp-scratch/") == 1
    assert git(wt, "status", "--porcelain", "-uall") == ""


def test_consecutive_opens_with_dirty_lock_json(tmp_path):
    _seat, wt = make_seat(tmp_path)
    _dirty_design_dir(wt)
    first = task_attempts.open_attempt(wt, "1.1", DD)
    second = task_attempts.open_attempt(wt, "1.2", DD)
    assert first["branch"] != second["branch"]
    assert os.path.isdir(first["attempt_dir"]) and os.path.isdir(second["attempt_dir"])
    assert len(branches(wt)) == 2
    assert [_record(a)["status"] for a in (first, second)] == ["open", "open"]
    assert (wt / DD / "lock.json").read_text(encoding="utf-8") == '{"owner": "me"}\n'


# --- Task 4.3: idempotent discard -------------------------------------------------

def _gone(repo: Path, att: dict) -> None:
    assert not os.path.exists(att["attempt_dir"])
    assert att["branch"] not in branches(repo)
    assert not os.path.exists(task_attempts.record_path(att))
    assert att["attempt_dir"] not in git(repo, "worktree", "list", "--porcelain")


def test_discard_idempotent_after_hand_delete(tmp_path):
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    shutil.rmtree(att["attempt_dir"])
    first = task_attempts.discard(att, root=wt)
    _gone(wt, att)
    assert first["attempt_id"] == att["attempt_id"]
    again = task_attempts.discard(att, root=wt)
    assert again["removed_dir"] is False
    _gone(wt, att)


def test_discard_never_rms_outside_owner_prefix(tmp_path):
    _seat, wt = make_seat(tmp_path)
    sentinel = write(tmp_path / "outside", "keep.txt", "keep\n")
    escapes = {  # attempt_dir → a file that must survive the discard
        str(tmp_path / "outside"): sentinel,
        # `..` climbs out of the prefix into the dispatcher's own tracked tree
        os.path.join(str(wt), ".tp-scratch", "tp-attempt-x", "..", "..",
                     "skills"): wt / "skills" / "a.py",
    }
    for i, (attempt_dir, keep) in enumerate(escapes.items()):
        att = task_attempts.open_attempt(wt, f"1.{i}", DD)
        git(wt, "worktree", "remove", "--force", att["attempt_dir"])
        att["attempt_dir"] = attempt_dir
        text = keep.read_text(encoding="utf-8")
        task_attempts._write_record(att)
        out = task_attempts.discard(att, root=wt)
        assert keep.read_text(encoding="utf-8") == text
        assert out["removed_dir"] is False
        assert any("outside" in line and "not removed" in line for line in out["log"])
        assert att["branch"] not in branches(wt)
        assert not os.path.exists(task_attempts.record_path(att))


def test_discard_leaves_dispatcher_design_dir_identical(tmp_path):
    _seat, wt = make_seat(tmp_path)
    _dirty_design_dir(wt)
    write(wt, f"{DD}/notes.md", "untracked design note\n")
    before = git(wt, "status", "--porcelain", "-uall")
    files = {p: p.read_bytes() for p in (wt / DD).iterdir()}
    for commit_it in (True, False):
        att = task_attempts.open_attempt(wt, "2.1", DD)
        adir = Path(att["attempt_dir"])
        write(adir, "skills/a.py", "A = 3\n")
        if commit_it:
            git(adir, "commit", "-qam", "attempt")
        write(adir, "skills/new_untracked.py", "B = 1\n")
        task_attempts.discard(att, root=wt)
        _gone(wt, att)
        assert git(wt, "status", "--porcelain", "-uall") == before
        assert {p: p.read_bytes() for p in (wt / DD).iterdir()} == files
    assert task_attempts.open_attempt(wt, "2.2", DD)["status"] == "open"
