"""Tests for the callers of the scratch sweep — every site that runs the reaper.

design: scratch-reaper (Task 1.2). Each Python caller test imports the calling
module with its own heavy collaborators monkeypatched, then monkeypatches the new
module-level sweep hook and asserts when it does and does not run.

The ci-local caller tests live in `skills/_shared/ci_local_tests/test_cil_sweep.py`
(dev-only) because they source `scripts/ci-local-lib.sh`, which never ships; this
file ships to consumers, so it must not reference `scripts/` at all.

Run with: pytest skills/_shared/test_scratch_reap_callers.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "tp-post-merge" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teardown  # noqa: E402

SLUG = "demo"
BASE = "master"


@pytest.fixture
def quiet_steps(monkeypatch):
    """No real git: every teardown step helper and the merge gate are stubbed."""
    monkeypatch.setattr(teardown, "verify_merged", lambda *a, **k: True)
    monkeypatch.setattr(teardown, "unlanded_commits", lambda root, slug: [])
    monkeypatch.setattr(teardown, "remove_worktrees", lambda root, slug: "removed x")
    monkeypatch.setattr(teardown, "delete_local_branch", lambda root, slug: "deleted")
    monkeypatch.setattr(teardown, "delete_remote_branch", lambda root, slug: "deleted")
    monkeypatch.setattr(teardown, "clear_mru", lambda root, slug: "cleared")


def _sweeper(monkeypatch, calls: list) -> None:
    monkeypatch.setattr(teardown, "_sweep_scratch", lambda: calls.append("sweep"))


def test_teardown_runs_sweep_fail_open(tmp_path, monkeypatch, quiet_steps):
    calls: list = []
    _sweeper(monkeypatch, calls)
    payload = teardown.teardown(tmp_path, SLUG, BASE)
    assert calls == ["sweep"], "teardown must sweep exactly once after the steps"
    assert set(payload) == {"steps", "verify_argv"}
    assert set(payload["steps"]) == {"c_worktree", "d_local_branch", "e_remote_branch",
                                     "h_mru"}


def test_teardown_sweep_failure_is_ignored(tmp_path, monkeypatch, quiet_steps):
    def boom():
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(teardown, "_sweep_scratch", boom)
    payload = teardown.teardown(tmp_path, SLUG, BASE)
    assert set(payload) == {"steps", "verify_argv"}
    assert payload["steps"]["h_mru"] == "cleared"


def test_teardown_forwards_sweep_summary_to_stderr(monkeypatch, capsys):
    """The operator sees the reaper's summary and error lines, never on stdout."""
    class FakeRun:
        returncode = 0
        stdout = "scratch_reap: 2 removed\n"
        stderr = "scratch_reap: x failed\n"

    monkeypatch.setattr(teardown.subprocess, "run", lambda *a, **k: FakeRun())
    assert teardown._sweep_scratch() is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "teardown: scratch_reap: 2 removed" in captured.err
    assert "teardown: scratch_reap: x failed" in captured.err


def test_refused_teardown_does_not_sweep(tmp_path, monkeypatch, quiet_steps):
    calls: list = []
    _sweeper(monkeypatch, calls)
    monkeypatch.setattr(teardown, "verify_merged", lambda *a, **k: False)
    assert teardown.teardown(tmp_path, SLUG, BASE) is None
    monkeypatch.setattr(teardown, "verify_merged", lambda *a, **k: True)
    monkeypatch.setattr(teardown, "unlanded_commits", lambda root, slug: ["deadbeef"])
    refused = teardown.teardown(tmp_path, SLUG, BASE)
    assert "refused" in refused and "steps" not in refused
    assert calls == [], "a refused teardown must not sweep"
