#!/usr/bin/env python3
"""Tests for verify_archive_staged.py — staged-blob stamp + lock-phase assertions.

The keystone: a working-tree file that HAS the completion stamp while its STAGED
index blob does NOT must FAIL — the helper inspects the index, never the disk.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "verify_archive_staged.py"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def _init_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def _write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _run(repo, slug):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--slug", slug],
        capture_output=True,
        text=True,
    )


def _design_rel(slug):
    return f"three-pillars-docs/completed-tp-designs/{slug}/design.md"


def _lock_rel(slug):
    return f"three-pillars-docs/completed-tp-designs/{slug}/lock.json"


def _fm(stamped):
    body = "---\nweight-class: light\n"
    if stamped:
        body += "completed: 2026-07-09\n"
    body += "---\n\n# demo design\n"
    return body


def _stage_lock(repo, slug, phase="cleanup-pending"):
    _write(repo, _lock_rel(slug), json.dumps({"phase": phase, "design": slug}))
    _git(repo, "add", _lock_rel(slug))


# ------------------------------------------------------------------ #
# Keystone
# ------------------------------------------------------------------ #


def test_keystone_working_tree_stamped_staged_blob_unstamped_fails(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    # Stage the UNSTAMPED blob.
    _write(repo, _design_rel(slug), _fm(stamped=False))
    _git(repo, "add", _design_rel(slug))
    _stage_lock(repo, slug)
    # Now add the stamp to the WORKING TREE only — do NOT re-add.
    _write(repo, _design_rel(slug), _fm(stamped=True))
    r = _run(repo, slug)
    assert r.returncode == 1, f"expected 1, got {r.returncode}: {r.stderr}"


def test_keystone_repaired_by_restaging_passes(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _write(repo, _design_rel(slug), _fm(stamped=False))
    _git(repo, "add", _design_rel(slug))
    _stage_lock(repo, slug)
    # Repair: stamp the working tree AND re-add.
    _write(repo, _design_rel(slug), _fm(stamped=True))
    _git(repo, "add", _design_rel(slug))
    r = _run(repo, slug)
    assert r.returncode == 0, f"expected 0, got {r.returncode}: {r.stderr}"


# ------------------------------------------------------------------ #
# Stamp + lock-phase pass / fail
# ------------------------------------------------------------------ #


def test_staged_stamp_and_lock_phase_pass(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _write(repo, _design_rel(slug), _fm(stamped=True))
    _git(repo, "add", _design_rel(slug))
    _stage_lock(repo, slug, phase="cleanup-pending")
    r = _run(repo, slug)
    assert r.returncode == 0, f"expected 0, got {r.returncode}: {r.stderr}"


def test_wrong_lock_phase_fails(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _write(repo, _design_rel(slug), _fm(stamped=True))
    _git(repo, "add", _design_rel(slug))
    _stage_lock(repo, slug, phase="active")
    r = _run(repo, slug)
    assert r.returncode == 1, f"expected 1, got {r.returncode}: {r.stderr}"


def test_lock_phase_asserted_via_json_not_substring(tmp_path):
    # A blob that merely contains the substring 'cleanup-pending' but whose parsed
    # phase field is something else must FAIL (parse JSON, not grep).
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _write(repo, _design_rel(slug), _fm(stamped=True))
    _git(repo, "add", _design_rel(slug))
    _write(
        repo,
        _lock_rel(slug),
        json.dumps({"phase": "active", "note": "was cleanup-pending earlier"}),
    )
    _git(repo, "add", _lock_rel(slug))
    r = _run(repo, slug)
    assert r.returncode == 1, f"expected 1, got {r.returncode}: {r.stderr}"


# ------------------------------------------------------------------ #
# Precondition (exit 2)
# ------------------------------------------------------------------ #


def test_design_absent_from_index_exits_2(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    # Nothing staged at all.
    r = _run(repo, slug)
    assert r.returncode == 2, f"expected 2, got {r.returncode}: {r.stderr}"


def test_lock_absent_from_index_exits_2(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    # design.md staged, lock.json absent from index.
    _write(repo, _design_rel(slug), _fm(stamped=True))
    _git(repo, "add", _design_rel(slug))
    r = _run(repo, slug)
    assert r.returncode == 2, f"expected 2, got {r.returncode}: {r.stderr}"
