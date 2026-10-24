"""Tests for run_scratch — the run's in-tree scratch dir (design: run-scratch-in-fence 1.1)."""
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_scratch as rs  # noqa: E402


def _repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def test_run_dir_is_realpath_join(tmp_path):
    repo = _repo(tmp_path / "r")
    link = tmp_path / "link"
    link.symlink_to(repo)
    assert rs.run_dir(link) == os.path.join(os.path.realpath(repo), ".tp-scratch", "run")


def test_env_pairs_order_and_values(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", "/should/not/be/read")
    repo = _repo(tmp_path / "r")
    d = rs.run_dir(repo)
    pairs = rs.env_pairs(repo, {"TMPDIR": "/other"})
    assert [k for k, _ in pairs] == [
        "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "npm_config_cache", "UV_CACHE_DIR"]
    vals = dict(pairs)
    assert vals["TMPDIR"] == vals["TMP"] == vals["TEMP"] == d
    assert vals["XDG_CACHE_HOME"] == d + "/cache"
    assert vals["PIP_CACHE_DIR"] == d + "/pip"
    assert vals["npm_config_cache"] == d + "/npm"
    assert vals["UV_CACHE_DIR"] == d + "/uv"


def test_cache_vars():
    assert rs.CACHE_VARS == ("XDG_CACHE_HOME", "PIP_CACHE_DIR", "npm_config_cache", "UV_CACHE_DIR")


def test_ensure_run_dir_creates_0700_idempotent_excluded(tmp_path):
    repo = _repo(tmp_path / "r")
    p = rs.ensure_run_dir(repo)
    assert p == rs.run_dir(repo)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o700
    assert rs.ensure_run_dir(repo) == p
    out = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert ".tp-scratch" not in out


def test_ensure_run_dir_unwritable_returns_none(tmp_path):
    assert rs.ensure_run_dir(tmp_path / "missing" / "deeper" / "x" / "\0bad") is None


def test_run_dir_from_env_accepts_repo_dir_and_gitfile(tmp_path):
    repo = _repo(tmp_path / "r")
    d = rs.ensure_run_dir(repo)
    assert rs.run_dir_from_env({"TMPDIR": d}) == os.path.realpath(d)
    wt = tmp_path / "wt"
    (wt / ".tp-scratch" / "run").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /x\n")
    assert rs.run_dir_from_env({"TMPDIR": str(wt / ".tp-scratch" / "run")}) == os.path.realpath(
        wt / ".tp-scratch" / "run")


def test_run_dir_from_env_rejects_other_shapes(tmp_path):
    nonrepo = tmp_path / "n"
    (nonrepo / ".tp-scratch" / "run").mkdir(parents=True)
    (tmp_path / "plain").mkdir()
    repo = _repo(tmp_path / "r")
    (repo / "run").mkdir()
    for v in ("~/t", str(tmp_path / "plain"), str(nonrepo / ".tp-scratch" / "run"), str(repo / "run")):
        assert rs.run_dir_from_env({"TMPDIR": v}) is None
    assert rs.run_dir_from_env({}) is None


def test_run_dir_from_env_rejects_symlinks(tmp_path):
    repo = _repo(tmp_path / "r")
    real = tmp_path / "elsewhere"
    (real / "run").mkdir(parents=True)
    (repo / ".tp-scratch").symlink_to(real)
    assert rs.run_dir_from_env({"TMPDIR": str(repo / ".tp-scratch" / "run")}) is None
    repo2 = _repo(tmp_path / "r2")
    (repo2 / ".tp-scratch").mkdir()
    (tmp_path / "tgt").mkdir()
    (repo2 / ".tp-scratch" / "run").symlink_to(tmp_path / "tgt")
    assert rs.run_dir_from_env({"TMPDIR": str(repo2 / ".tp-scratch" / "run")}) is None


def test_tag_stable_and_distinct(tmp_path):
    a, b = _repo(tmp_path / "a"), _repo(tmp_path / "b")
    t = rs.tag(a)
    assert t == rs.tag(a) and len(t) == 6 and int(t, 16) >= 0
    assert t != rs.tag(b)


def test_outside_tmpdir_only_for_the_run_dir_shape(tmp_path, monkeypatch):
    sysdir = tmp_path / "systmp"
    sysdir.mkdir()
    monkeypatch.setattr(rs, "_SYSTEM_TMP", str(sysdir))
    assert rs.outside_tmpdir({"TMPDIR": "/w/x/.tp-scratch/run"}) == str(sysdir)
    assert rs.outside_tmpdir({"TMPDIR": "/w/x/.tp-scratch/run/"}) == str(sysdir)
    assert rs.outside_tmpdir({"TMPDIR": "/srv/t"}) is None
    assert rs.outside_tmpdir({}) is None
    monkeypatch.setenv("TMPDIR", "/w/x/.tp-scratch/run")
    assert rs.outside_tmpdir() == str(sysdir)
    monkeypatch.setattr(rs, "_SYSTEM_TMP", str(tmp_path / "missing"))
    assert rs.outside_tmpdir({"TMPDIR": "/w/x/.tp-scratch/run"}) is None
