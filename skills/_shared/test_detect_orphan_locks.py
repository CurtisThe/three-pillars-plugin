"""Unit tests for detect_orphan_locks.py.

All tests are network-free: they pass an explicit `remote_branches` set via
the injectable parameter, so no `git ls-remote` call is made.

Test cases:
  (a) lock-only dir whose branch is NOT in remote_branches → orphan
  (b) lock-only dir whose branch IS in remote_branches → not orphan (live branch)
  (c) dir with lock.json AND design.md (or any other file) → never orphan
  (d) bad/malformed lock.json → fail-open (no raise, dir contributes nothing)
  (e) missing tp-designs dir / empty input → []
  (f) indeterminate live probe (git ls-remote failed → None) → [] (no false positives)
"""

from __future__ import annotations

import json
from pathlib import Path

import detect_orphan_locks
from detect_orphan_locks import OrphanLock, find_orphan_locks

DESIGNS_SUBDIR = "three-pillars-docs/tp-designs"


def _make_lock(dir_path: Path, branch: str, **extra) -> None:
    """Write a lock.json with the given branch into dir_path."""
    dir_path.mkdir(parents=True, exist_ok=True)
    data = {"branch": branch, "owner": "test@example.com", **extra}
    (dir_path / "lock.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# (a) lock-only dir whose branch is NOT in remote_branches → orphan
# ---------------------------------------------------------------------------

def test_orphan_lock_absent_branch(tmp_path):
    """A lock-only dir with a branch not in remote_branches is returned as orphan."""
    designs = tmp_path / DESIGNS_SUBDIR
    slug_dir = designs / "my-design"
    _make_lock(slug_dir, branch="tp/my-design")

    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert len(result) == 1
    orphan = result[0]
    assert orphan.slug == "my-design"
    assert orphan.branch == "tp/my-design"
    assert isinstance(orphan, OrphanLock)


# ---------------------------------------------------------------------------
# (b) lock-only dir whose branch IS in remote_branches → not orphan
# ---------------------------------------------------------------------------

def test_live_branch_not_orphan(tmp_path):
    """A lock-only dir with a branch present in remote_branches is NOT an orphan."""
    designs = tmp_path / DESIGNS_SUBDIR
    slug_dir = designs / "active-design"
    _make_lock(slug_dir, branch="tp/active-design")

    result = find_orphan_locks(tmp_path, remote_branches={"tp/active-design"})
    assert result == []


# ---------------------------------------------------------------------------
# (c) dir with lock.json AND design.md → never orphan (in-flight or archivable)
# ---------------------------------------------------------------------------

def test_dir_with_design_md_not_orphan(tmp_path):
    """A dir containing lock.json plus any other file is NOT an orphan."""
    designs = tmp_path / DESIGNS_SUBDIR
    slug_dir = designs / "in-flight-design"
    _make_lock(slug_dir, branch="tp/in-flight-design")
    (slug_dir / "design.md").write_text("# In-flight\n")

    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert result == []


def test_dir_with_extra_file_not_orphan(tmp_path):
    """Any file beyond lock.json disqualifies the dir from being an orphan."""
    designs = tmp_path / DESIGNS_SUBDIR
    slug_dir = designs / "has-extra"
    _make_lock(slug_dir, branch="tp/has-extra")
    (slug_dir / "implementation-audit.md").write_text("# audit\n")

    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert result == []


# ---------------------------------------------------------------------------
# (d) bad/malformed lock.json → fail-open (no raise)
# ---------------------------------------------------------------------------

def test_malformed_lock_json_fail_open(tmp_path):
    """A dir with malformed lock.json contributes nothing — fail-open."""
    designs = tmp_path / DESIGNS_SUBDIR
    slug_dir = designs / "bad-lock"
    slug_dir.mkdir(parents=True)
    (slug_dir / "lock.json").write_text("NOT VALID JSON {{{")

    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert result == []


def test_lock_json_missing_branch_key_fail_open(tmp_path):
    """A lock.json with no 'branch' key contributes nothing — fail-open."""
    designs = tmp_path / DESIGNS_SUBDIR
    slug_dir = designs / "no-branch-key"
    slug_dir.mkdir(parents=True)
    (slug_dir / "lock.json").write_text(json.dumps({"owner": "someone@x.com"}))

    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert result == []


# ---------------------------------------------------------------------------
# (e) missing tp-designs dir / empty input → []
# ---------------------------------------------------------------------------

def test_missing_designs_dir_returns_empty(tmp_path):
    """If three-pillars-docs/tp-designs/ does not exist, return []."""
    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert result == []


def test_empty_designs_dir_returns_empty(tmp_path):
    """If tp-designs/ is empty, return []."""
    designs = tmp_path / DESIGNS_SUBDIR
    designs.mkdir(parents=True)

    result = find_orphan_locks(tmp_path, remote_branches=set())
    assert result == []


# ---------------------------------------------------------------------------
# Multiple orphans — ensure all are returned
# ---------------------------------------------------------------------------

def test_multiple_orphans(tmp_path):
    """Two lock-only dirs with absent branches → two OrphanLocks returned."""
    designs = tmp_path / DESIGNS_SUBDIR
    _make_lock(designs / "alpha", branch="tp/alpha")
    _make_lock(designs / "beta", branch="tp/beta")

    result = find_orphan_locks(tmp_path, remote_branches=set())
    slugs = {o.slug for o in result}
    assert slugs == {"alpha", "beta"}


def test_mixed_orphan_and_live(tmp_path):
    """One orphan (branch absent) + one live (branch present) → only orphan returned."""
    designs = tmp_path / DESIGNS_SUBDIR
    _make_lock(designs / "orphan-slug", branch="tp/orphan-slug")
    _make_lock(designs / "live-slug", branch="tp/live-slug")

    result = find_orphan_locks(tmp_path, remote_branches={"tp/live-slug"})
    assert len(result) == 1
    assert result[0].slug == "orphan-slug"


# ---------------------------------------------------------------------------
# (f) indeterminate live probe → [] (the inverted-fail-open regression)
# ---------------------------------------------------------------------------

def test_indeterminate_probe_reports_nothing(tmp_path, monkeypatch):
    """When the live ls-remote probe is indeterminate (None: origin unreachable,
    offline, auth failure), find_orphan_locks must report NOTHING — never flag
    a lock-only dir as orphaned. This is the load-bearing fail-open contract:
    a failed probe must not look like 'no remote branches exist'.

    Drives the default (remote_branches=None) code path so the live probe runs,
    with _read_remote_branches forced to its error sentinel.
    """
    designs = tmp_path / DESIGNS_SUBDIR
    _make_lock(designs / "would-be-orphan", branch="tp/would-be-orphan")

    monkeypatch.setattr(
        detect_orphan_locks, "_read_remote_branches", lambda repo_root: None
    )

    # No explicit remote_branches → live probe path → indeterminate → [].
    result = find_orphan_locks(tmp_path)
    assert result == [], "indeterminate probe must never flag orphans"


def test_read_remote_branches_returns_none_on_ls_remote_failure(
    tmp_path, monkeypatch
):
    """_read_remote_branches returns the None sentinel (NOT an empty set) when
    git ls-remote fails — distinguishing 'error/unknown' from 'known-empty'.
    """
    class _FailResult:
        returncode = 128
        stdout = ""
        stderr = "fatal: 'origin' does not appear to be a git repository"

    monkeypatch.setattr(
        detect_orphan_locks.subprocess, "run", lambda *a, **k: _FailResult()
    )
    assert detect_orphan_locks._read_remote_branches(tmp_path) is None


def test_known_empty_probe_still_flags(tmp_path, monkeypatch):
    """A SUCCESSFUL probe that genuinely returns zero heads (known-empty set())
    is distinct from indeterminate: orphans MAY still be flagged. Guards against
    over-correcting the fix into 'never flag from the live path'.
    """
    designs = tmp_path / DESIGNS_SUBDIR
    _make_lock(designs / "real-orphan", branch="tp/real-orphan")

    monkeypatch.setattr(
        detect_orphan_locks, "_read_remote_branches", lambda repo_root: set()
    )

    result = find_orphan_locks(tmp_path)
    assert len(result) == 1
    assert result[0].slug == "real-orphan"
