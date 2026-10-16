"""test_seat_resolve_where_wt.py — `--where` from a design worktree (review-convergence E2).

`seat_resolve.sh --where` inside a `*-wt/` design worktree answers NONE today, so a caller
running from the design worktree cannot find the seat. On `design-worktree` the script
re-runs `_classify` from the primary worktree and prints that verdict's seat path; a hub
with no standing base worktree still answers NONE, and `--detect` / `--am-i-seat` keep
reporting the design worktree as not-the-seat.

Fixtures are built with real git, mirroring the seat / bare-hub / missing-seat fixtures in
test_seat_resolve.sh.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
SCRIPT = _SHARED_DIR / "seat_resolve.sh"

_GIT_ENV_VARS = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_COMMON_DIR")


def _env() -> dict[str, str]:
    """os.environ minus any inherited repo-local git env (a hook may export them)."""
    env = dict(os.environ)
    for name in _GIT_ENV_VARS:
        env.pop(name, None)
    return env


def _git(*args: str, cwd: str | Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                       env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout


def _run(*args: str, cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args],
                          cwd=str(cwd) if cwd else None,
                          env=_env(), capture_output=True, text=True)


def _seat_fixture(tmp_path: Path) -> Path:
    """Non-bare repo on `main` (the seat) + sibling `repo-wt/x` worktree on `tp/x`."""
    seat = tmp_path / "repo"
    _git("init", "-q", "-b", "main", str(seat))
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "init", cwd=seat)
    _git("-C", str(seat), "branch", "tp/x")
    _git("-C", str(seat), "worktree", "add", str(tmp_path / "repo-wt/x"), "tp/x")
    return seat


def _bare_hub_fixture(tmp_path: Path) -> Path:
    """Bare hub with no standing base worktree + `hub-wt/x` design worktree on `tp/x`."""
    hub = tmp_path / "hub.git"
    scratch = tmp_path / "scratch"
    _git("init", "-q", "-b", "main", str(scratch))
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "init", cwd=scratch)
    _git("init", "--bare", "-q", str(hub))
    _git("-C", str(scratch), "push", "-q", str(hub), "main")
    _git("-C", str(hub), "worktree", "add", str(tmp_path / "hub-wt/x"), "-b", "tp/x", "main")
    return hub


def test_where_from_design_worktree_prints_seat_path(tmp_path):
    seat = _seat_fixture(tmp_path)
    r = _run("--where", "--repo", str(tmp_path / "repo-wt/x"))
    assert r.returncode == 0, r.stderr
    assert os.path.realpath(r.stdout.strip()) == os.path.realpath(str(seat)), r.stdout


def test_where_with_no_repo_arg_from_inside_design_worktree(tmp_path):
    seat = _seat_fixture(tmp_path)
    r = _run("--where", cwd=tmp_path / "repo-wt/x")
    assert r.returncode == 0, r.stderr
    assert os.path.realpath(r.stdout.strip()) == os.path.realpath(str(seat)), r.stdout


def test_where_from_design_worktree_of_seatless_hub_is_none(tmp_path):
    _bare_hub_fixture(tmp_path)
    r = _run("--where", "--repo", str(tmp_path / "hub-wt/x"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "NONE", r.stdout


def test_detect_and_am_i_seat_unchanged_for_design_worktree(tmp_path):
    _seat_fixture(tmp_path)
    wt = tmp_path / "repo-wt/x"
    r = _run("--detect", "--repo", str(wt))
    assert r.returncode == 0, r.stderr
    assert "state=design-worktree" in r.stdout, r.stdout
    r = _run("--am-i-seat", "--repo", str(wt))
    assert r.returncode == 1, r.stdout + r.stderr


def test_where_from_the_seat_itself_still_prints_seat_path(tmp_path):
    seat = _seat_fixture(tmp_path)
    r = _run("--where", "--repo", str(seat))
    assert r.returncode == 0, r.stderr
    assert os.path.realpath(r.stdout.strip()) == os.path.realpath(str(seat)), r.stdout
