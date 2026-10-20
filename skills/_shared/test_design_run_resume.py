"""Example tests for design_run_resume (design: fleet-windows-reboot-resume, Task 1.2).

Every transcript lives on a `tmp_path` fake profile (`CLAUDE_CONFIG_DIR`), every tmux call
lands on a scripted runner, and no test signals a real PID or reads the real /proc.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import context_rollover_state as crs  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_resume as drr  # noqa: E402

SID_A = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID_B = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SID_C = "33333333-cccc-4ccc-8ccc-cccccccccccc"


def _env(tmp_path):
    return {"CLAUDE_CONFIG_DIR": str(tmp_path / "profile"), "HOME": str(tmp_path / "home"),
            "PATH": ""}


def _worktree(tmp_path, slug="my-design"):
    wt = tmp_path / "wt" / slug
    wt.mkdir(parents=True)
    return wt


def _transcript(tmp_path, wt, sid, mtime):
    pdir = dro.project_dir(str(wt), _env(tmp_path))
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{sid}.jsonl"
    f.write_text("{}\n")
    os.utime(f, (mtime, mtime))
    return f


# --- resolve_session ---------------------------------------------------------------------

def test_resolve_picks_newest_top_level_transcript(tmp_path):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, SID_A, 1000)
    _transcript(tmp_path, wt, SID_B, 3000)
    _transcript(tmp_path, wt, SID_C, 2000)
    sid, mtime = drr.resolve_session(str(wt), _env(tmp_path))
    assert sid == SID_B  # the whole uuid, not the 8-char prefix
    assert mtime == 3000


def test_resolve_never_picks_a_subdirectory_or_a_non_transcript(tmp_path):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, SID_A, 1000)
    sub = dro.project_dir(str(wt), _env(tmp_path)) / SID_A / "subagents"
    sub.mkdir(parents=True)
    newer = sub / "agent-deadbeef.jsonl"
    newer.write_text("{}\n")
    os.utime(newer, (9000, 9000))
    (dro.project_dir(str(wt), _env(tmp_path)) / "looks-like.jsonl").mkdir()
    other = dro.project_dir(str(wt), _env(tmp_path)) / "notes.txt"  # not a transcript
    other.write_text("x")
    os.utime(other, (9000, 9000))
    sid, mtime = drr.resolve_session(str(wt), _env(tmp_path))
    assert (sid, mtime) == (SID_A, 1000)


def test_resolve_with_no_transcript_dir_names_the_slug(tmp_path):
    wt = _worktree(tmp_path, "gone-slug")
    assert issubclass(drr.ResumeError, ValueError)
    with pytest.raises(drr.ResumeError) as exc:
        drr.resolve_session(str(wt), _env(tmp_path))
    assert str(exc.value) == "no session to resume for gone-slug"


def test_resolve_with_an_empty_transcript_dir_names_the_slug(tmp_path):
    wt = _worktree(tmp_path, "empty-slug")
    dro.project_dir(str(wt), _env(tmp_path)).mkdir(parents=True)
    with pytest.raises(drr.ResumeError) as exc:
        drr.resolve_session(str(wt), _env(tmp_path))
    assert str(exc.value) == "no session to resume for empty-slug"


def test_resolve_override_returns_that_session(tmp_path):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, SID_A, 1000)
    _transcript(tmp_path, wt, SID_B, 3000)
    sid, mtime = drr.resolve_session(str(wt), _env(tmp_path), override=SID_A)
    assert (sid, mtime) == (SID_A, 1000)  # not the newest


def test_resolve_unknown_override_names_the_transcript_dir(tmp_path):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, SID_A, 1000)
    with pytest.raises(drr.ResumeError) as exc:
        drr.resolve_session(str(wt), _env(tmp_path), override=SID_C)
    msg = str(exc.value)
    assert str(dro.project_dir(str(wt), _env(tmp_path))) in msg
    assert SID_C in msg


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "sid with space", "x.jsonl"])
def test_resolve_override_that_is_not_a_bare_sid_is_refused(tmp_path, bad):
    wt = _worktree(tmp_path)
    _transcript(tmp_path, wt, SID_A, 1000)
    with pytest.raises(drr.ResumeError):
        drr.resolve_session(str(wt), _env(tmp_path), override=bad)


def test_resolve_override_pointing_at_a_directory_is_unknown(tmp_path):
    wt = _worktree(tmp_path)
    (dro.project_dir(str(wt), _env(tmp_path)) / f"{SID_A}.jsonl").mkdir(parents=True)
    with pytest.raises(drr.ResumeError):
        drr.resolve_session(str(wt), _env(tmp_path), override=SID_A)


# --- list_candidates ---------------------------------------------------------------------

def _two_designs(tmp_path):
    old = _worktree(tmp_path, "old-run")
    new = _worktree(tmp_path, "new-run")
    _transcript(tmp_path, old, SID_A, 1000)
    _transcript(tmp_path, new, SID_B, 5000)
    return [("old-run", str(old)), ("new-run", str(new))]


def test_candidates_are_worktrees_whose_newest_transcript_predates_boot(tmp_path):
    rows = drr.list_candidates(_two_designs(tmp_path), _env(tmp_path), 3000, lambda s: "")
    assert rows == [("old-run", SID_A, 1000)]


def test_candidates_boot_boundary_is_strict(tmp_path):
    wts = _two_designs(tmp_path)
    assert drr.list_candidates(wts, _env(tmp_path), 1000, lambda s: "") == []
    assert [r[0] for r in drr.list_candidates(wts, _env(tmp_path), 1001, lambda s: "")] == [
        "old-run"]


def test_candidates_use_the_newest_transcript_per_worktree(tmp_path):
    wt = _worktree(tmp_path, "two-sessions")
    _transcript(tmp_path, wt, SID_A, 1000)
    _transcript(tmp_path, wt, SID_B, 4000)  # written after boot: the run was resumed already
    assert drr.list_candidates([("two-sessions", str(wt))], _env(tmp_path), 3000,
                               lambda s: "") == []


def test_candidates_skip_slugs_with_a_live_run(tmp_path):
    wts = _two_designs(tmp_path)
    asked = []

    def live(slug):
        asked.append(slug)
        return "claude" if slug == "old-run" else ""

    assert drr.list_candidates(wts, _env(tmp_path), 10_000, live) == [
        ("new-run", SID_B, 5000)]
    assert "old-run" in asked


def test_candidates_with_unknown_boot_time_is_none(tmp_path):
    assert drr.list_candidates(_two_designs(tmp_path), _env(tmp_path), None,
                               lambda s: "") is None
    assert drr.list_candidates([], _env(tmp_path), 10_000, lambda s: "") == []  # known boot


def test_candidates_skip_worktrees_without_a_transcript(tmp_path):
    bare = _worktree(tmp_path, "never-ran")
    assert drr.list_candidates([("never-ran", str(bare))], _env(tmp_path), 10_000,
                               lambda s: "") == []


# --- pane_pid ----------------------------------------------------------------------------

def _tmux(windows="0 @3\n1 @4", pid="4242", pid_rc=0, windows_rc=0):
    calls = []

    def run(args):
        calls.append(list(args))
        if args[0] == "list-windows":
            return windows_rc, windows if windows_rc == 0 else "can't find session"
        if args[0] == "display-message":
            return pid_rc, pid
        return 1, "unexpected"

    run.calls = calls
    return run


def test_pane_pid_reads_the_run_windows_pane_pid():
    runner = _tmux()
    assert drr.pane_pid(runner, "my-design") == 4242
    assert ["list-windows", "-t", "=my-design", "-F", "#{window_index} #{window_id}"] in (
        runner.calls)
    shown = [c for c in runner.calls if c[0] == "display-message"]
    assert len(shown) == 1 and "@3" in shown[0] and "#{pane_pid}" in shown[0]  # lowest index
    assert {c[0] for c in runner.calls} <= {"list-windows", "display-message"}  # read-only


def test_pane_pid_is_none_without_a_session():
    assert drr.pane_pid(_tmux(windows_rc=1), "my-design") is None


def test_pane_pid_is_none_when_tmux_cannot_say():
    assert drr.pane_pid(_tmux(pid_rc=1, pid="can't find pane"), "my-design") is None


@pytest.mark.parametrize("junk", ["", "p@3", "12x", "-5"])
def test_pane_pid_is_none_for_a_non_numeric_answer(junk):
    assert drr.pane_pid(_tmux(pid=junk), "my-design") is None


# --- refresh_run_state -------------------------------------------------------------------

def _run_dir(wt):
    return wt / ".three-pillars" / "run"


def _fleet_worker(wt, pid=111):
    run = _run_dir(wt)
    run.mkdir(parents=True)
    (run / "run.pid").write_text(f"{pid}\n")
    state = {"schema_version": 1,
             "supervisor": {"state": "interactive", "pid": pid,
                            "started_at": "2026-10-17T00:00:00Z"},
             "iterate": {"phase": "x"}}
    (run / "state.json").write_text(json.dumps(state))
    return state


def test_refresh_rewrites_run_pid_and_the_supervisor_pid(tmp_path):
    wt = _worktree(tmp_path)
    before = _fleet_worker(wt)
    assert drr.refresh_run_state(str(wt), 4242) is True
    assert (_run_dir(wt) / "run.pid").read_text(encoding="utf-8").strip() == "4242"
    after = json.loads((_run_dir(wt) / "state.json").read_text(encoding="utf-8"))
    assert after["supervisor"]["pid"] == 4242
    assert after["supervisor"]["state"] == "interactive"
    assert after["supervisor"]["started_at"] == before["supervisor"]["started_at"]
    assert after["iterate"] == before["iterate"]
    assert after["schema_version"] == 1


def test_refresh_leaves_no_temp_files_behind(tmp_path):
    wt = _worktree(tmp_path)
    _fleet_worker(wt)
    drr.refresh_run_state(str(wt), 4242)
    assert sorted(p.name for p in _run_dir(wt).iterdir()) == ["run.pid", "state.json"]


def test_refresh_without_a_run_dir_writes_nothing(tmp_path):
    wt = _worktree(tmp_path)
    assert drr.refresh_run_state(str(wt), 4242) is False
    assert not (wt / ".three-pillars").exists()


def test_refresh_without_run_pid_leaves_state_json_alone(tmp_path):
    wt = _worktree(tmp_path)
    _fleet_worker(wt)
    (_run_dir(wt) / "run.pid").unlink()
    snapshot = (_run_dir(wt) / "state.json").read_text(encoding="utf-8")
    assert drr.refresh_run_state(str(wt), 4242) is False
    assert (_run_dir(wt) / "state.json").read_text(encoding="utf-8") == snapshot
    assert not (_run_dir(wt) / "run.pid").exists()


@pytest.mark.parametrize("bad", [0, -1, -4242, None, "4242", 4242.0, True])
def test_refresh_refuses_a_non_positive_or_non_integer_pgid(tmp_path, bad):
    wt = _worktree(tmp_path)
    _fleet_worker(wt)
    pid_before = (_run_dir(wt) / "run.pid").read_text(encoding="utf-8")
    state_before = (_run_dir(wt) / "state.json").read_text(encoding="utf-8")
    assert drr.refresh_run_state(str(wt), bad) is False
    assert (_run_dir(wt) / "run.pid").read_text(encoding="utf-8") == pid_before
    assert (_run_dir(wt) / "state.json").read_text(encoding="utf-8") == state_before


def test_refresh_with_run_pid_only_does_not_create_state_json(tmp_path):
    wt = _worktree(tmp_path)
    _run_dir(wt).mkdir(parents=True)
    (_run_dir(wt) / "run.pid").write_text("111\n")
    assert drr.refresh_run_state(str(wt), 4242) is True
    assert (_run_dir(wt) / "run.pid").read_text(encoding="utf-8").strip() == "4242"
    assert not (_run_dir(wt) / "state.json").exists()


@pytest.mark.parametrize("body", ["not json", "[]", '{"schema_version": 1}',
                                  '{"supervisor": "interactive"}'])
def test_refresh_leaves_an_unusable_state_json_untouched(tmp_path, body):
    wt = _worktree(tmp_path)
    _run_dir(wt).mkdir(parents=True)
    (_run_dir(wt) / "run.pid").write_text("111\n")
    (_run_dir(wt) / "state.json").write_text(body)
    assert drr.refresh_run_state(str(wt), 4242) is True
    assert (_run_dir(wt) / "run.pid").read_text(encoding="utf-8").strip() == "4242"
    assert (_run_dir(wt) / "state.json").read_text(encoding="utf-8") == body


def test_refresh_signals_nothing(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("refresh_run_state must not signal a process")

    monkeypatch.setattr(os, "kill", boom)
    monkeypatch.setattr(os, "killpg", boom)
    wt = _worktree(tmp_path)
    _fleet_worker(wt)
    assert drr.refresh_run_state(str(wt), 4242) is True


# --- ledger_claimed ----------------------------------------------------------------------

def _ledger(wt):
    return _run_dir(wt) / "context-rollover.json"


def test_ledger_claimed_true_for_a_claimed_entry(tmp_path):
    wt = _worktree(tmp_path)
    assert crs.claim(_ledger(wt), SID_A, now=1.0)
    assert drr.ledger_claimed(str(wt), SID_A) is True


def test_ledger_claimed_false_once_the_rollover_finished_or_aborted(tmp_path):
    wt = _worktree(tmp_path)
    for sid, outcome in ((SID_A, "done"), (SID_B, "aborted")):
        assert crs.claim(_ledger(wt), sid, now=1.0)
        assert crs.finish(_ledger(wt), sid, outcome)
        assert drr.ledger_claimed(str(wt), sid) is False


def test_ledger_claimed_false_for_another_session_or_no_ledger(tmp_path):
    wt = _worktree(tmp_path)
    assert drr.ledger_claimed(str(wt), SID_A) is False
    assert crs.claim(_ledger(wt), SID_A, now=1.0)
    assert drr.ledger_claimed(str(wt), SID_B) is False


def test_ledger_claimed_false_for_a_corrupt_ledger(tmp_path):
    wt = _worktree(tmp_path)
    _run_dir(wt).mkdir(parents=True)
    _ledger(wt).write_text("{half a json")
    assert drr.ledger_claimed(str(wt), SID_A) is False

