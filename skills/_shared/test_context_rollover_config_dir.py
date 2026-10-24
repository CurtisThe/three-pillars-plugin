"""test_context_rollover_config_dir.py — the driver reads the run's real transcript dir.

design: fleet-watcher-reliability (Task 1.2). A classicai run launched from a personal seat
writes its transcripts under the classicai profile, so the seat's own `CLAUDE_CONFIG_DIR`
holds none and the driver printed `context size unknown` for a run that was far past the
threshold. `real_seams` now hands the slug and the tmux runner to `_newest_transcript`, which
asks `run_config_dir.project_dir` (the run's `claude` process environ); with no slug or no
runner, or no answer, it resolves exactly as before.

Fakes only: tmux is a fake runner and `run_config_dir.config_dir` is monkeypatched, so no
real tmux server, process table or config dir is touched.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
import design_run_observe as dro  # noqa: E402
import run_config_dir  # noqa: E402
from test_context_rollover_drive import SLUG, _assistant  # noqa: E402


def _transcript(config_dir, worktree, name):
    pdir = dro.project_dir(str(worktree), {"CLAUDE_CONFIG_DIR": str(config_dir), "PATH": ""})
    pdir.mkdir(parents=True)
    (pdir / f"{name}.jsonl").write_text(json.dumps(_assistant()) + "\n", encoding="utf-8")


def _seams(tmp_path, monkeypatch, answer):
    """`real_seams` for a run whose `claude` environ answers `answer` (None = no answer)."""
    run = tmp_path / "run"
    run.mkdir()
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "personal"), "PATH": "", "HOME": str(tmp_path)}
    monkeypatch.setattr(drive.drt, "_tmux_runner", lambda _env: lambda args: (0, ""))
    seen = []

    def config_dir(slug, runner, **_seams):
        seen.append(slug)
        return answer
    monkeypatch.setattr(run_config_dir, "config_dir", config_dir)
    return run, env, seen


def test_a_classicai_runs_transcript_is_found_under_a_personal_seat(tmp_path, monkeypatch):
    run, env, seen = _seams(tmp_path, monkeypatch, str(tmp_path / "classicai"))
    _transcript(tmp_path / "classicai", run, "run-sess")  # only here; none under `personal`
    seams = drive.real_seams(SLUG, str(run), env, out=[].append)
    assert seams["session"]() == "run-sess"
    assert len(seams["records"]()) == 1
    assert seen and set(seen) == {SLUG}


def test_no_answer_falls_back_to_the_seats_resolution(tmp_path, monkeypatch):
    run, env, _seen = _seams(tmp_path, monkeypatch, None)
    _transcript(tmp_path / "personal", run, "seat-sess")
    seams = drive.real_seams(SLUG, str(run), env, out=[].append)
    assert seams["session"]() == "seat-sess"
    assert len(seams["records"]()) == 1


def test_without_a_slug_or_runner_the_old_resolution_is_used(tmp_path, monkeypatch):
    run, env, seen = _seams(tmp_path, monkeypatch, str(tmp_path / "classicai"))
    _transcript(tmp_path / "personal", run, "seat-sess")
    _transcript(tmp_path / "classicai", run, "run-sess")
    assert drive._newest_transcript(str(run), env)[0] == "seat-sess"
    assert drive._newest_transcript(str(run), env, slug=SLUG)[0] == "seat-sess"
    assert drive._newest_transcript(str(run), env, runner=lambda a: (0, ""))[0] == "seat-sess"
    assert seen == []  # the run's environ is never asked without both
    both = drive._newest_transcript(str(run), env, slug=SLUG, runner=lambda a: (0, ""))
    assert both[0] == "run-sess" and seen == [SLUG]


def test_no_transcript_anywhere_is_still_none(tmp_path, monkeypatch):
    run, env, _seen = _seams(tmp_path, monkeypatch, str(tmp_path / "classicai"))
    seams = drive.real_seams(SLUG, str(run), env, out=[].append)
    assert seams["session"]() is None and seams["records"]() == []
