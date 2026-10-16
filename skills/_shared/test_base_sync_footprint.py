"""Disk-footprint tests for the base-sync scenario fixture: the clone of the framework
checkout borrows its objects (alternates) instead of copying the whole object store."""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_repo  # noqa: E402
from base_sync_repo import build_scenario  # noqa: E402


def clean_git_env() -> dict:
    """os.environ minus repo-local GIT_* vars (a hook-inherited GIT_DIR must not leak in)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


MIB = 1024 * 1024


def _tree_bytes(root) -> int:
    """Sum st_size of every file under root, counting each (st_dev, st_ino) once."""
    seen, total = set(), 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            st = os.lstat(os.path.join(dirpath, name))
            key = (st.st_dev, st.st_ino)
            if key not in seen:
                seen.add(key)
                total += st.st_size
    return total


def _tracked_bytes(src) -> int:
    out = subprocess.run(["git", "-C", str(src), "ls-files", "-z"], capture_output=True,
                         check=True, env=clean_git_env()).stdout
    total = 0
    for rel in out.split(b"\0"):
        if rel:
            p = os.path.join(str(src), os.fsdecode(rel))
            if os.path.isfile(p):
                total += os.lstat(p).st_size
    return total


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          env=clean_git_env())


def test_origin_borrows_objects_via_alternates(tmp_path):
    s = build_scenario(tmp_path)
    alt = s.origin_dir / ".git" / "objects" / "info" / "alternates"
    assert alt.is_file()
    names = [ln.strip() for ln in alt.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert names and all(os.path.isdir(n) for n in names)


def test_own_object_stores_are_small(tmp_path):
    s = build_scenario(tmp_path)
    for d in (s.origin_dir, s.repo_dir):
        assert _tree_bytes(d / ".git" / "objects") <= 2 * MIB


def test_scenario_root_size_ratio(tmp_path):
    s = build_scenario(tmp_path)
    tracked = _tracked_bytes(base_sync_repo._this_repo_root())
    assert _tree_bytes(s.root) <= 2.5 * tracked


def test_offline_behaviour_unchanged(tmp_path):
    s = build_scenario(tmp_path)
    assert _git(s.repo_dir, "fetch", "origin", s.base_ref).returncode == 0
    for d in (s.origin_dir, s.repo_dir):
        r = _git(d, "fsck", "--connectivity-only")
        assert r.returncode == 0, r.stderr


def test_origin_commit_writes_to_own_store(tmp_path):
    s = build_scenario(tmp_path)
    (s.origin_dir / "footprint-probe.txt").write_text("probe\n")
    _git(s.origin_dir, "add", "footprint-probe.txt")
    r = subprocess.run(["git", "-C", str(s.origin_dir), "-c", "user.name=t",
                        "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "commit", "-q", "-m", "probe"], capture_output=True, text=True,
                       env=clean_git_env())
    assert r.returncode == 0, r.stderr
    sha = _git(s.origin_dir, "rev-parse", "HEAD").stdout.strip()
    assert (s.origin_dir / ".git" / "objects" / sha[:2] / sha[2:]).is_file()
