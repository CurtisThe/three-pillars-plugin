"""Tests for revert_probe: forecast and CLI contract. Cap: <=160 lines."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from _probe_fixtures import MergeRepo, land_merge, make_gh_fn
from _probe_fixtures import merge_repo  # noqa: F401  — registers pytest fixture
from revert_probe import Forecast, forecast, main


# ---------------------------------------------------------------------------
# Task 1.3: forecast
# ---------------------------------------------------------------------------

def test_forecast_clean_on_newest(merge_repo: MergeRepo) -> None:
    sha = land_merge(merge_repo, "tp/clean", {"c.txt": "line\n"})
    r = forecast(str(merge_repo.clone), sha, "master")
    assert isinstance(r, Forecast) and r.clean is True and r.conflicted == []


def test_forecast_conflicted(merge_repo: MergeRepo) -> None:
    """Later commit on same file -> clean=False, conflicted lists the path."""
    sha = land_merge(merge_repo, "tp/cf", {"shared.txt": "orig\n"})
    c = merge_repo.clone
    subprocess.run(["git", "-C", str(c), "checkout", "master"],
                   check=True, capture_output=True)
    (c / "shared.txt").write_text("later\n")
    subprocess.run(["git", "-C", str(c), "add", "shared.txt"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(c), "commit", "-m", "later"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(c), "push", "origin", "master"],
                   check=True, capture_output=True)
    r = forecast(str(c), sha, "master")
    assert not r.clean and "shared.txt" in r.conflicted


def test_forecast_worktree_removed(merge_repo: MergeRepo) -> None:
    """Scratch worktree is cleaned up on normal exit."""
    sha = land_merge(merge_repo, "tp/cleanup", {"cl.txt": "cl\n"})
    wt = merge_repo.clone / ".claude" / "worktrees" / f"revert-probe-{sha[:8]}"
    forecast(str(merge_repo.clone), sha, "master")
    wt_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(merge_repo.clone), capture_output=True, text=True
    ).stdout
    assert str(wt) not in wt_list and not wt.exists()


def test_forecast_worktree_removed_on_raise(merge_repo: MergeRepo,
                                             monkeypatch) -> None:
    """Scratch worktree is cleaned up even when an intermediate step raises."""
    sha = land_merge(merge_repo, "tp/raise", {"r.txt": "r\n"})
    wt = merge_repo.clone / ".claude" / "worktrees" / f"revert-probe-{sha[:8]}"
    real_run = subprocess.run
    calls = [0]

    def patched(cmd, **kw):
        if isinstance(cmd, list) and "revert" in cmd and "--no-commit" in cmd:
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("simulated")
        return real_run(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", patched)
    with pytest.raises(RuntimeError, match="simulated"):
        forecast(str(merge_repo.clone), sha, "master")
    wt_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(merge_repo.clone), capture_output=True, text=True
    ).stdout
    assert str(wt) not in wt_list and not wt.exists()


# ---------------------------------------------------------------------------
# Task 1.4: CLI contract
# ---------------------------------------------------------------------------

def test_cli_json_keys_and_exit_zero(merge_repo: MergeRepo) -> None:
    sha = land_merge(merge_repo, "tp/cli", {"cli.txt": "cli\n"})
    data = {"mergeCommit": {"oid": sha}, "headRefName": "tp/cli",
            "baseRefName": "master", "state": "MERGED"}
    cap = io.StringIO()
    with patch("sys.stdout", cap):
        rc = main(["--repo", str(merge_repo.clone), "--pr", "7", "--json"],
                  gh_fn=make_gh_fn(data))
    assert rc == 0
    out = json.loads(cap.getvalue())
    assert set(out.keys()) == {
        "merge_sha", "pr", "slug", "base", "depth", "clean", "conflicted", "error"}
    assert out["merge_sha"] == sha and out["pr"] == 7
    assert out["slug"] == "cli" and out["error"] is None
    assert out["depth"] == 0 and out["clean"] is True


def test_cli_error_exits_zero(merge_repo: MergeRepo) -> None:
    data = {"mergeCommit": None, "headRefName": "tp/foo",
            "baseRefName": "master", "state": "OPEN"}
    cap = io.StringIO()
    with patch("sys.stdout", cap):
        rc = main(["--repo", str(merge_repo.clone), "--pr", "9", "--json"],
                  gh_fn=make_gh_fn(data))
    assert rc == 0
    out = json.loads(cap.getvalue())
    assert out["error"] is not None and out["depth"] is None


def test_cli_fetch_fail_open(merge_repo: MergeRepo, capsys) -> None:
    sha = land_merge(merge_repo, "tp/ff", {"ff.txt": "ff\n"})
    data = {"mergeCommit": {"oid": sha}, "headRefName": "tp/ff",
            "baseRefName": "master", "state": "MERGED"}
    import revert_probe

    def fake_fetch(repo):
        print("warning: fetch failed", file=sys.stderr)
        return False

    with patch.object(revert_probe, "_fetch_origin", fake_fetch):
        cap = io.StringIO()
        with patch("sys.stdout", cap):
            rc = main(["--repo", str(merge_repo.clone), "--pr", "7", "--json"],
                      gh_fn=make_gh_fn(data))
    assert rc == 0
    assert "warning" in capsys.readouterr().err.lower()


def test_cli_mutually_exclusive(merge_repo: MergeRepo) -> None:
    with pytest.raises(SystemExit):
        main(["--repo", str(merge_repo.clone), "--pr", "1", "--sha", "abc", "--json"])


# ---------------------------------------------------------------------------
# Item 3: worktree-add failure routes through the JSON error field, not conflicted[]
# ---------------------------------------------------------------------------

def test_forecast_worktree_add_failure_routes_to_error_field(
        merge_repo: MergeRepo, monkeypatch) -> None:
    """A worktree-add failure must set Forecast.error (not conflicted[]) and clean=None."""
    sha = land_merge(merge_repo, "tp/wtfail", {"wt.txt": "wt\n"})
    real_run = subprocess.run

    def patched(cmd, **kw):
        if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
            import subprocess as _sp
            cp = _sp.CompletedProcess(cmd, 128, stdout="", stderr="fatal: fake add fail")
            return cp
        return real_run(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", patched)
    r = forecast(str(merge_repo.clone), sha, "master")
    assert r.error is not None, "worktree-add failure must set Forecast.error"
    assert "worktree-add failed" in r.error, (
        f"Forecast.error should mention worktree-add failed; got: {r.error!r}"
    )
    assert r.conflicted == [], (
        f"worktree-add failure must NOT populate conflicted[]; got: {r.conflicted!r}"
    )
    assert r.clean is None, (
        f"worktree-add failure must set clean=None, not False; got: {r.clean!r}"
    )
