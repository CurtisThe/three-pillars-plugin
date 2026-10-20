"""`launch_design_run.main --resume / --session / --list-resumable` through the CLI.

design: fleet-windows-reboot-resume (Task 1.5; behaviours 1-4 and 9)

The rig (fixture repo, profile, stub tmux on PATH) is test_launch_design_run.py's. Every run
here passes `--wait 0`, so no test waits on a real `claude`; the resume orchestration itself
is design_run_resume_run's (test_design_run_resume_run.py). Nothing here signals a process.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boot_time  # noqa: E402
import design_run_command as drc  # noqa: E402
import design_run_observe as dro  # noqa: E402
import launch_design_run as ldr  # noqa: E402
from test_launch_design_run import _run, _set_design_run, _trusted, rig  # noqa: E402,F401

SID_OLD = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID_NEW = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
BOOT = 2_000_000_000


def _transcript(rig, sid, mtime):
    pdir = dro.project_dir(rig["wt"], rig["env"])
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / f"{sid}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _two(rig, mtime=1_700_000_000):
    _transcript(rig, SID_OLD, mtime)
    _transcript(rig, SID_NEW, mtime + 60)


def _resume_cmd(rig, sid):
    return drc.resume_window_command("foo", rig["wt"], sid, config_dir=rig["cfg"])


def _brief(rig):
    return Path(rig["wt"]) / "three-pillars-docs" / "tp-designs" / "foo" / "seat-brief.md"


def _decisions(rig):
    return Path(rig["wt"]) / "three-pillars-docs" / "tp-designs" / "foo" / "decisions.md"


def test_resume_opens_the_session_on_the_newest_transcript(rig, capsys):
    _two(rig)
    assert _run(rig, ["foo", "--resume", "--wait", "0"]) == 0
    logged = rig["log"].read_text(encoding="utf-8").splitlines()
    for arg in ("new-session", "-d", "-s", "foo", _resume_cmd(rig, SID_NEW)):
        assert arg in logged
    assert "link-window" in logged and "=seat:" in logged
    assert not any("/tp-run-full-design" in arg for arg in logged)
    out = capsys.readouterr().out
    assert f"resumed foo: session {SID_NEW}" in out
    assert "/tp-run-full-design" not in out
    assert "continue line skipped (--wait 0)" in out


def test_resume_never_writes_the_brief_or_a_fable_notice(rig, capsys):
    _set_design_run(rig, "fable")
    _two(rig)
    assert _run(rig, ["foo", "--resume", "--wait", "0"]) == 0
    assert not _brief(rig).exists() and not _decisions(rig).exists()
    assert "WARNING" not in capsys.readouterr().err
    assert "--resume" in rig["log"].read_text(encoding="utf-8")


def test_resume_refuses_a_live_run(rig, capsys, monkeypatch):
    _two(rig)
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda slug, runner: "claude")
    assert _run(rig, ["foo", "--resume", "--wait", "0"]) == 2
    cap = capsys.readouterr()
    assert "already live" in cap.err and "/tp-run-full-design" not in cap.out
    assert not rig["log"].exists()  # the patched live check made no tmux call at all


def test_resume_without_a_transcript_launches_nothing(rig, capsys):
    assert _run(rig, ["foo", "--resume", "--wait", "0"]) == 2
    cap = capsys.readouterr()
    assert "no session to resume for foo" in cap.err
    last = cap.out.strip().splitlines()[-1]
    assert last.endswith("launch_design_run.py foo") and "--resume" not in last
    assert "new-session" not in rig["log"].read_text(encoding="utf-8")


def test_session_resumes_the_named_conversation(rig, capsys):
    _two(rig)
    assert _run(rig, ["foo", "--resume", "--session", SID_OLD, "--wait", "0"]) == 0
    logged = rig["log"].read_text(encoding="utf-8").splitlines()
    assert _resume_cmd(rig, SID_OLD) in logged
    assert f"resumed foo: session {SID_OLD}" in capsys.readouterr().out


def test_unknown_session_exits_2_and_names_the_transcript_dir(rig, capsys):
    _two(rig)
    assert _run(rig, ["foo", "--resume", "--session", "no-such-sid", "--wait", "0"]) == 2
    err = capsys.readouterr().err
    assert "no-such-sid" in err and str(dro.project_dir(rig["wt"], rig["env"])) in err
    assert "new-session" not in rig["log"].read_text(encoding="utf-8")


def test_resume_dry_run_prints_the_command_and_writes_nothing(rig, capsys):
    _set_design_run(rig, "fable")
    _two(rig)
    assert _run(rig, ["foo", "--resume", "--dry-run"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == drc.resume_window_command("foo", rig["wt"], SID_NEW, config_dir=rig["cfg"],
                                                model="fable", configured="fable")
    assert not rig["log"].exists() and _trusted(rig) is None
    assert not _brief(rig).exists() and not _decisions(rig).exists()


def test_resume_dry_run_without_a_transcript_exits_2(rig, capsys):
    assert _run(rig, ["foo", "--resume", "--dry-run"]) == 2
    assert "no session to resume for foo" in capsys.readouterr().err
    assert not rig["log"].exists()


@pytest.mark.parametrize("argv,words", [
    (["foo", "--session", SID_OLD], ("--session", "--resume")),
    (["foo", "--resume", "--base-sync"], ("--resume", "--base-sync")),
    ([], ("slug",)),
    (["foo", "--list-resumable"], ("--list-resumable", "slug")),
])
def test_flag_misuse_is_a_parser_error(rig, capsys, argv, words):
    with pytest.raises(SystemExit) as exc:
        _run(rig, argv)
    assert exc.value.code == 2
    reason = capsys.readouterr().err.strip().splitlines()[-1]  # the `error:` line, not the usage
    assert all(word in reason for word in words)
    assert not rig["log"].exists()


def test_list_resumable_is_none_without_a_stale_transcript(rig, capsys, monkeypatch):
    monkeypatch.setattr(boot_time, "boot_epoch", lambda *a, **k: BOOT)
    assert _run(rig, ["--list-resumable"]) == 0
    assert capsys.readouterr().out.strip().splitlines() == ["none"]


def test_list_resumable_names_a_worktree_a_reboot_left_idle(rig, capsys, monkeypatch):
    monkeypatch.setattr(boot_time, "boot_epoch", lambda *a, **k: BOOT)
    _two(rig, mtime=BOOT - 1000)
    assert _run(rig, ["--list-resumable"], PATH="/nonexistent-dir") == 0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(BOOT - 1000 + 60))
    assert capsys.readouterr().out.strip().splitlines() == [f"foo {SID_NEW} {stamp}"]


def test_list_resumable_skips_a_worktree_with_a_live_run(rig, capsys, monkeypatch):
    monkeypatch.setattr(boot_time, "boot_epoch", lambda *a, **k: BOOT)
    monkeypatch.setattr(ldr.design_run_tmux, "live", lambda slug, runner: "claude")
    _two(rig, mtime=BOOT - 1000)
    assert _run(rig, ["--list-resumable"]) == 0
    assert capsys.readouterr().out.strip().splitlines() == ["none"]


def test_list_resumable_says_so_when_the_boot_time_is_unknown(rig, capsys, monkeypatch):
    monkeypatch.setattr(boot_time, "boot_epoch", lambda *a, **k: None)
    _two(rig, mtime=BOOT - 1000)
    assert _run(rig, ["--list-resumable"]) == 0
    assert "boot time unknown" in capsys.readouterr().out
