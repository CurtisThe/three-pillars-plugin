"""A recorded child's transcript is never the session a rebooted run resumes.

design: fleet-windows-reboot-resume. `child_spawn.py start` runs `claude -p` in the design
worktree, so a child's transcript lands beside the run's own and can be the newest one. The
child state files (`<git common dir>/tp-children/<run8>/*.json`) name each `child_session`.
The common dir is monkeypatched onto `tmp_path`; the real `.git` is never touched.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import child_state as cs  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_resume as drr  # noqa: E402

RUN = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CHILD = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CHILD2 = "33333333-cccc-4ccc-8ccc-cccccccccccc"


def _env(tmp_path):
    return {"CLAUDE_CONFIG_DIR": str(tmp_path / "profile"), "HOME": str(tmp_path / "home"),
            "PATH": ""}


def _worktree(tmp_path):
    wt = tmp_path / "wt" / "my-design"
    wt.mkdir(parents=True)
    return wt


def _transcript(tmp_path, wt, sid, mtime):
    pdir = dro.project_dir(str(wt), _env(tmp_path))
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{sid}.jsonl"
    f.write_text("{}\n")
    os.utime(f, (mtime, mtime))


@pytest.fixture
def common(tmp_path, monkeypatch):
    path = tmp_path / "common"
    path.mkdir()
    monkeypatch.setattr(cs, "_git_common_dir", lambda root: path)
    return path


def _record(common, sid, name="c1"):
    rdir = cs.run_dir("run00001", root=common)
    cs.write(rdir / f"{name}.json", {"child_session": sid})


def test_newer_child_transcript_is_skipped(tmp_path, common):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, RUN, 1000)
    _transcript(tmp_path, wt, CHILD, 5000)
    _record(common, CHILD)
    assert drr.resolve_session(str(wt), _env(tmp_path)) == (RUN, 1000)
    rows = drr.list_candidates([("my-design", str(wt))], _env(tmp_path), 9000, lambda s: False)
    assert rows == [("my-design", RUN, 1000)]


def test_no_child_records_changes_nothing(tmp_path, common):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, RUN, 1000)
    _transcript(tmp_path, wt, CHILD, 5000)
    assert drr.resolve_session(str(wt), _env(tmp_path)) == (CHILD, 5000)


def test_only_children_means_no_session(tmp_path, common):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, CHILD, 5000)
    _transcript(tmp_path, wt, CHILD2, 6000)
    _record(common, CHILD, "c1")
    _record(common, CHILD2, "c2")
    with pytest.raises(drr.ResumeError):
        drr.resolve_session(str(wt), _env(tmp_path))
    assert drr.list_candidates([("my-design", str(wt))], _env(tmp_path), 9000,
                               lambda s: False) == []


def test_unreadable_children_dir_fails_open(tmp_path, monkeypatch):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, RUN, 1000)
    _transcript(tmp_path, wt, CHILD, 5000)
    monkeypatch.setattr(cs, "_git_common_dir", lambda root: tmp_path / "missing")
    assert drr.resolve_session(str(wt), _env(tmp_path)) == (CHILD, 5000)
    monkeypatch.setattr(cs, "_git_common_dir", lambda root: None)
    assert drr.resolve_session(str(wt), _env(tmp_path)) == (CHILD, 5000)


def test_override_ignores_child_records(tmp_path, common):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, CHILD, 5000)
    _record(common, CHILD)
    assert drr.resolve_session(str(wt), _env(tmp_path), CHILD) == (CHILD, 5000)
