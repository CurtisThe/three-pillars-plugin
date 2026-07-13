#!/usr/bin/env python3
"""Tests for verify_archive_staged.py — no-dangling + staged-tree consistency.

Front-runs inv #38: a live `tp-designs/{slug}` cite left after the archive move
FAILS. Behavior 7: a cite rewritten on disk but NOT `git add`ed also FAILS — the
assertion reflects the STAGED tree that will be committed, not just the disk.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "verify_archive_staged.py"
RECONCILE = Path(__file__).resolve().parents[2] / "_shared" / "reconcile_docs.py"

DOC_REL = "three-pillars-docs/architecture.md"


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


def _run_reconcile(repo, slug, apply=True):
    args = [
        sys.executable, str(RECONCILE),
        "--repo", str(repo), "--archive-cites", "--slug", slug,
    ]
    if apply:
        args.append("--apply")
    return subprocess.run(args, capture_output=True, text=True)


def _design_rel(slug):
    return f"three-pillars-docs/completed-tp-designs/{slug}/design.md"


def _lock_rel(slug):
    return f"three-pillars-docs/completed-tp-designs/{slug}/lock.json"


def _stage_archived(repo, slug):
    """Stage a correctly-archived design.md (stamped) + lock.json (cleanup-pending)."""
    _write(
        repo, _design_rel(slug),
        "---\nweight-class: light\ncompleted: 2026-07-09\n---\n\n# demo\n",
    )
    _write(repo, _lock_rel(slug), json.dumps({"phase": "cleanup-pending", "design": slug}))
    _git(repo, "add", _design_rel(slug), _lock_rel(slug))


def _seed_committed_doc(repo, slug, body):
    """Write DOC_REL, stage the archive + doc, commit so working tree == index."""
    _stage_archived(repo, slug)
    _write(repo, DOC_REL, body)
    _git(repo, "add", DOC_REL)
    _git(repo, "commit", "-q", "-m", "seed")


# ------------------------------------------------------------------ #
# (a) dead-cite detection
# ------------------------------------------------------------------ #


def test_seeded_dangling_cite_fails(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _seed_committed_doc(
        repo, slug,
        f"See three-pillars-docs/tp-designs/{slug}/design.md for details.\n",
    )
    r = _run(repo, slug)
    assert r.returncode == 1, f"expected 1, got {r.returncode}: {r.stderr}"


def test_pre_sweep_plus_staging_resolves(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _seed_committed_doc(
        repo, slug,
        f"See three-pillars-docs/tp-designs/{slug}/design.md for details.\n",
    )
    rc = _run_reconcile(repo, slug, apply=True)
    assert rc.returncode == 0, rc.stderr
    _git(repo, "add", DOC_REL)
    r = _run(repo, slug)
    assert r.returncode == 0, f"expected 0, got {r.returncode}: {r.stderr}"


# ------------------------------------------------------------------ #
# (b) staged-tree consistency (Behavior 7)
# ------------------------------------------------------------------ #


def test_rewritten_but_unstaged_fails(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _seed_committed_doc(
        repo, slug,
        f"See three-pillars-docs/tp-designs/{slug}/design.md for details.\n",
    )
    # Pre-sweep rewrites the cite ON DISK — but we deliberately do NOT git add.
    rc = _run_reconcile(repo, slug, apply=True)
    assert rc.returncode == 0, rc.stderr
    # Working tree is now clean of the cite, but the STAGED tree still carries it.
    r = _run(repo, slug)
    assert r.returncode == 1, f"expected 1, got {r.returncode}: {r.stderr}"


def test_unrelated_unstaged_wip_not_flagged(tmp_path):
    """An unstaged tracked path with NO `tp-designs/{slug}` cite in its staged blob
    is unrelated WIP, not a rewritten-but-unstaged archive cite — it must NOT be
    flagged (else the repair advice would sweep WIP into the archival commit)."""
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    # Clean archive (no dangling cite), plus a committed unrelated skills/ file.
    _stage_archived(repo, slug)
    _write(repo, "skills/other/unrelated.py", "x = 1\n")
    _git(repo, "add", "skills/other/unrelated.py")
    _git(repo, "commit", "-q", "-m", "seed")
    # Dirty the unrelated file in the working tree, unstaged (no slug cite anywhere).
    _write(repo, "skills/other/unrelated.py", "x = 2\n")
    r = _run(repo, slug)
    assert r.returncode == 0, f"expected 0 (unrelated WIP not flagged), got {r.returncode}: {r.stderr}"


def test_modified_tracked_binary_does_not_exit_2(tmp_path):
    """A modified tracked BINARY file among the unstaged paths must not raise a
    precondition (exit 2) — part (b) reads staged blobs lossily, and a binary
    cannot carry a text cite anyway."""
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _stage_archived(repo, slug)
    asset = Path(repo) / "three-pillars-docs/assets/logo.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe\xfa\x01\x02")
    _git(repo, "add", "three-pillars-docs/assets/logo.png")
    _git(repo, "commit", "-q", "-m", "seed")
    # Modify the binary in the working tree, unstaged.
    asset.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe\xfa\x03\x04\x05")
    r = _run(repo, slug)
    assert r.returncode == 0, f"expected 0 (binary must not cause exit 2), got {r.returncode}: {r.stderr}"


# ------------------------------------------------------------------ #
# clean + precondition
# ------------------------------------------------------------------ #


def test_clean_repo_all_staged_passes(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    _seed_committed_doc(
        repo, slug,
        f"See three-pillars-docs/completed-tp-designs/{slug}/design.md now.\n",
    )
    r = _run(repo, slug)
    assert r.returncode == 0, f"expected 0, got {r.returncode}: {r.stderr}"


def test_archived_path_absent_from_index_exits_2(tmp_path):
    repo = _init_repo(tmp_path)
    slug = "demo-design"
    # No archived design.md staged at all → precondition error.
    r = _run(repo, slug)
    assert r.returncode == 2, f"expected 2, got {r.returncode}: {r.stderr}"
