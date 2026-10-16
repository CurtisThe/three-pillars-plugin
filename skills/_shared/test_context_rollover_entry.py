"""test_context_rollover_entry.py — the driver's entry point finds the run's worktree.

design: strata-spend-leaks (implementation audit F-1). The seat runs
`context_rollover_drive.py <slug>` from its **base checkout**, not from the run's
worktree, so the entry point must not take the cwd as the run: without `--worktree` it
resolves the `tp/<slug>` worktree from `git worktree list --porcelain` (the same
`launch_design_run.find_worktree` `design_run_watch.py` uses), and binds the transcript,
the ledger and the handoff `git log` to that worktree. No `tp/<slug>` worktree is one
`context rollover unavailable:` line, exit 0, nothing claimed.

Every test runs from a cwd that is NOT the run worktree. Fakes only: the listing is a
string, tmux is a fake runner, `git log` is a recorded fake; no real tmux server, git
or config dir is touched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402
import design_run_observe as dro  # noqa: E402
from test_context_rollover_drive import SLUG, _assistant  # noqa: E402


def _porcelain(seat, run, slug=SLUG):
    return (f"worktree {seat}\nHEAD 1111\nbranch refs/heads/master\n\n"
            f"worktree {run}\nHEAD 2222\nbranch refs/heads/tp/{slug}\n")


def _dirs(tmp_path, monkeypatch):
    seat, run = tmp_path / "seat", tmp_path / "run"
    seat.mkdir()
    run.mkdir()
    monkeypatch.chdir(seat)  # the seat's base checkout, never the run
    return seat, run


def test_main_resolves_the_tp_worktree_not_the_cwd(tmp_path, monkeypatch):
    """Without `--worktree` the seams are bound to the `tp/<slug>` worktree."""
    seat, run = _dirs(tmp_path, monkeypatch)
    seen = []

    def seams(slug, worktree, env, out):
        seen.append(worktree)
        return {"send": None, "handoff_sha": None, "records": None, "pane": None,
                "clock": None, "sleep": None, "ledger": None, "out": out,
                "session": None, "tmux_blocker": "fake: stop here"}

    lines = []
    assert drive.main([SLUG], listing=lambda: _porcelain(seat, run), seams=seams,
                      env={}, out=lines.append) == 0
    assert seen == [str(run)]
    assert lines == ["context rollover unavailable: fake: stop here"]


def test_explicit_worktree_skips_the_listing(tmp_path, monkeypatch):
    seat, run = _dirs(tmp_path, monkeypatch)
    seen = []

    def listing():
        raise AssertionError("--worktree given: the listing must not be read")

    def seams(slug, worktree, env, out):
        seen.append(worktree)
        return {"send": None, "handoff_sha": None, "records": None, "pane": None,
                "clock": None, "sleep": None, "ledger": None, "out": out,
                "session": None, "tmux_blocker": "stop"}

    assert drive.main([SLUG, "--worktree", str(run)], listing=listing, seams=seams,
                      env={}, out=[].append) == 0
    assert seen == [str(run)]


def test_no_tp_worktree_degrades_without_claiming(tmp_path, monkeypatch):
    """No `tp/<slug>` worktree (or a failed listing): one line, exit 0, nothing bound."""
    seat, run = _dirs(tmp_path, monkeypatch)

    def seams(*_a):
        raise AssertionError("no worktree: no seams may be bound")

    for listing in (lambda: _porcelain(seat, run, slug="other"), lambda: None):
        lines = []
        assert drive.main([SLUG], listing=listing, seams=seams, env={},
                          out=lines.append) == 0
        assert lines == [f"context rollover unavailable: no tp/{SLUG} worktree"]
    assert not (seat / ".three-pillars").exists()
    assert not (run / ".three-pillars").exists()


def test_real_seams_read_and_write_the_resolved_worktree(tmp_path, monkeypatch):
    """End to end through `real_seams`, from the seat's cwd: the transcript comes from
    the run worktree's project dir, the ledger lands in the run worktree, and the
    handoff is read from the run worktree (never the seat). The save is refused by a fake
    `deliver`, so the rollover aborts before any `/clear`."""
    seat, run = _dirs(tmp_path, monkeypatch)
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "PATH": ""}
    pdir = dro.project_dir(str(run), env)
    pdir.mkdir(parents=True)
    (pdir / "run-sess.jsonl").write_text(json.dumps(_assistant()) + "\n", encoding="utf-8")

    monkeypatch.setattr(drive.drt, "_tmux_runner", lambda _env: lambda args: (0, ""))
    monkeypatch.setattr(drive.dro, "pane_text", lambda runner, slug: "idle pane")
    sent = []
    monkeypatch.setattr(drive.drs, "deliver",
                        lambda slug, line, runner: sent.append(line) or "not-delivered")
    reads = []
    real_handoff_sha = drive._handoff_sha

    def recording_handoff_sha(worktree, slug):
        reads.append((worktree, slug))
        return real_handoff_sha(worktree, slug)

    monkeypatch.setattr(drive, "_handoff_sha", recording_handoff_sha)

    lines = []
    rc = drive.main([SLUG, "--idle", "0"], listing=lambda: _porcelain(seat, run), env=env,
                    out=lines.append)
    assert rc == 1, lines
    assert sent == [f"/tp-session-save {SLUG}"]  # never a /clear
    assert reads and all(r == (str(run), SLUG) for r in reads)
    ledger = run.joinpath(*drive.LEDGER_RELPATH)
    assert json.loads(ledger.read_text(encoding="utf-8"))["run-sess"]["state"] == "aborted"
    assert not (seat / ".three-pillars").exists()
