"""Tests for wt_root — one checkout root for every role, kept off `.claude/`.

design: worktrees-under-wt-only (Task 1.1)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attempt_fixture as fx  # noqa: E402
import wt_root  # noqa: E402
import worktree_isolation_guard as guard  # noqa: E402

SCRIPT = str(Path(__file__).resolve().parent / "wt_root.py")
ROLES = ("worker", "generator", "regress", "rerun", "audit", "cert",
         "attempt", "hot-patch", "baseline", "revert", "compile")
SLUG = "demo"


def _real(p):
    return os.path.realpath(str(p))


def _cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


@pytest.fixture
def repos(tmp_path):
    seat, wt = fx.make_seat(tmp_path)
    return Path(_real(seat)), Path(_real(wt))


def test_scratch_parent_in_wt_worktree(repos):
    _, wt = repos
    assert wt_root.scratch_parent(wt, SLUG) == str(wt / ".tp-scratch")


def test_scratch_parent_in_seat_is_pure(repos):
    seat, _ = repos
    expected = seat.parent / "repo-wt" / ".tp-scratch" / SLUG
    assert wt_root.scratch_parent(seat, SLUG) == str(expected)
    assert not expected.exists()


def test_ensure_parent_creates_and_excludes(repos):
    seat, wt = repos
    got = wt_root.ensure_parent(wt, SLUG)
    assert os.path.isdir(got)
    common = Path(fx.git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert "/.tp-scratch/" in (common / "info" / "exclude").read_text(encoding="utf-8")
    out = wt_root.ensure_parent(seat, SLUG)
    assert os.path.isdir(out) and out == wt_root.scratch_parent(seat, SLUG)


@pytest.mark.parametrize("where", ["seat", "wt"])
def test_open_checkout_every_role(repos, where):
    root = repos[0] if where == "seat" else repos[1]
    for role in ROLES:
        path = wt_root.open_checkout(root, role, SLUG, "HEAD")
        assert os.path.isdir(path)
        assert re.fullmatch(rf"{role}-{SLUG}-[0-9a-f]{{8}}", os.path.basename(path))
        assert ".claude" not in Path(_real(path)).parts
        assert fx.git(path, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


def test_guard_accepts_seat_fallback(repos):
    seat, _ = repos
    path = wt_root.open_checkout(seat, "worker", SLUG, "HEAD")
    assert guard._is_default_branch_root(path, "", False) is False


def _refused(case, call):
    """Every failure mode carries the marker `^wt-root-refused`."""
    try:
        call()
    except ValueError as exc:
        assert str(exc).startswith("wt-root-refused"), (
            f"expected message matching ^wt-root-refused for {case}, got {str(exc)!r}")
    except Exception as exc:  # wrong exception type
        pytest.fail(f"expected ValueError matching ^wt-root-refused for {case}, "
                    f"got {type(exc).__name__}: {exc}")
    else:
        pytest.fail(f"DID NOT RAISE; expected ValueError matching ^wt-root-refused for {case}")


def test_refusals(repos, tmp_path):
    seat, _ = repos
    bad = tmp_path / ("." + "claude") / "x"
    _refused("claude root", lambda: wt_root.scratch_parent(bad, SLUG))
    _refused("role nope", lambda: wt_root.open_checkout(seat, "nope", SLUG, "HEAD"))
    for slug in ("Bad Slug", "a b", "demo/../../x", "demo\n", "-demo", ""):
        _refused(f"slug {slug!r}", lambda s=slug: wt_root.open_checkout(seat, "worker", s, "HEAD"))
    for role in ("", "Worker", "worker ", "work"):
        _refused(f"role {role!r}", lambda r=role: wt_root.open_checkout(seat, r, SLUG, "HEAD"))
    # the root is judged by its resolved path, not only as given
    inside = tmp_path / ("." + "claude") / "worktrees" / "agent-1"
    inside.mkdir(parents=True)
    link = tmp_path / "plain-link"
    link.symlink_to(inside)
    for given in (link, inside / ".." / "agent-1"):
        _refused(f"resolved root {given}", lambda g=given: wt_root.scratch_parent(g, SLUG))
    cwd = os.getcwd()
    os.chdir(inside)
    try:
        _refused("root '.' inside .claude", lambda: wt_root.scratch_parent(".", SLUG))
        _refused("open_checkout root '.' inside .claude",
                 lambda: wt_root.open_checkout(".", "worker", SLUG, "HEAD"))
    finally:
        os.chdir(cwd)


def test_reap_only_matching_role_and_slug(repos):
    seat, _ = repos
    a = wt_root.open_checkout(seat, "audit", SLUG, "HEAD")
    b = wt_root.open_checkout(seat, "audit", "other", "HEAD")
    c = wt_root.open_checkout(seat, "cert", SLUG, "HEAD")
    wt_root.reap(seat, "audit", SLUG)
    assert not os.path.exists(a)
    assert os.path.isdir(b) and os.path.isdir(c)
    assert _real(a) not in fx.porcelain(seat)


def test_cli(repos, tmp_path):
    seat, _ = repos
    bad = tmp_path / ("." + "claude") / "x"
    r = _cli("check", str(bad))
    assert r.returncode == 1 and "wt-root-refused" in r.stderr
    assert _cli("check", str(seat)).returncode == 0
    r = _cli("open", "--role", "rerun", "--slug", SLUG, "--base-ref", "HEAD", "--root", str(seat))
    assert r.returncode == 0
    path = json.loads(r.stdout)["path"]
    assert os.path.isdir(path)
    r = _cli("reap", "--role", "rerun", "--slug", SLUG, "--root", str(seat))
    assert r.returncode == 0 and len(r.stdout.strip().splitlines()) == 1
    assert not os.path.exists(path)
    assert _cli("open", "--role", "zzz", "--slug", SLUG, "--base-ref", "HEAD",
                "--root", str(seat)).returncode == 1
