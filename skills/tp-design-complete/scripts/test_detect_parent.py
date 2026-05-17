#!/usr/bin/env python3
"""Tests for detect_parent.py — parent-design detection for /tp-design-complete."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import detect_parent as dp  # noqa: E402

PASSED = 0
FAILED = 0


def assert_eq(actual, expected, msg=""):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}\n    expected: {expected!r}\n    actual:   {actual!r}")


def assert_in(needle, haystack, msg=""):
    global PASSED, FAILED
    if needle in haystack:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}\n    needle: {needle!r}\n    haystack: {haystack!r}")


# ── Fixture helpers ─────────────────────────────────────────


def make_design_dir(repo_root: Path, name: str, lock: dict | None = None) -> Path:
    """Create three-pillars-docs/tp-designs/{name}/ with optional lock.json."""
    d = repo_root / "three-pillars-docs" / "tp-designs" / name
    d.mkdir(parents=True, exist_ok=True)
    if lock is not None:
        (d / "lock.json").write_text(json.dumps(lock))
    return d


def default_lock(name: str, branch: str | None = None, last_touched: str = "2026-05-17T00:00:00Z") -> dict:
    return {
        "design": name,
        "branch": branch or f"tp/{name}",
        "owner": "test@example.com",
        "phase": "design",
        "acquired_at": last_touched,
        "last_touched": last_touched,
        "previous_owners": [],
    }


def git(repo: Path, *args: str) -> str:
    """Run a git command in repo and return stripped stdout."""
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def make_repo(repo: Path) -> str:
    """Initialize a git repo and produce one commit. Returns the commit SHA."""
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "commit", "-q", "--allow-empty", "-m", "initial")
    return git(repo, "rev-parse", "HEAD")


# ── enumerate_siblings tests ────────────────────────────────


def test_enumerate_returns_empty_when_no_siblings():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_design_dir(repo, "self", default_lock("self"))
        result = dp.enumerate_siblings(repo, "self")
        assert_eq(result, [], "no siblings should return empty list")


def test_enumerate_skips_self():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_design_dir(repo, "self", default_lock("self"))
        make_design_dir(repo, "sibling", default_lock("sibling"))
        result = dp.enumerate_siblings(repo, "self")
        assert_eq(len(result), 1, "self should be excluded; only sibling returned")
        assert_eq(result[0]["design"], "sibling", "result is the sibling")
        assert_eq(result[0]["branch"], "tp/sibling", "branch field carries through")


def test_enumerate_skips_missing_lock():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_design_dir(repo, "self", default_lock("self"))
        make_design_dir(repo, "sibling-with-lock", default_lock("sibling-with-lock"))
        make_design_dir(repo, "sibling-no-lock", lock=None)
        result = dp.enumerate_siblings(repo, "self")
        names = sorted(c["design"] for c in result)
        assert_eq(names, ["sibling-with-lock"], "design with no lock.json is silently skipped")


# ── resolve_ref tests ───────────────────────────────────────


def test_resolve_ref_local():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        sha = make_repo(repo)
        git(repo, "update-ref", "refs/heads/tp/A", sha)
        result = dp.resolve_ref(repo, "tp/A")
        assert_eq(result, "refs/heads/tp/A", "local branch resolves to refs/heads/")


def test_resolve_ref_origin_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        sha = make_repo(repo)
        git(repo, "update-ref", "refs/remotes/origin/tp/B", sha)
        result = dp.resolve_ref(repo, "tp/B")
        assert_eq(result, "refs/remotes/origin/tp/B", "remote-only branch falls through to origin")


def test_resolve_ref_missing_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        result = dp.resolve_ref(repo, "tp/missing")
        assert_eq(result, None, "missing ref returns None")


# ── is_ancestor tests ───────────────────────────────────────


def test_is_ancestor_true():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        commit1 = make_repo(repo)
        git(repo, "checkout", "-q", "-b", "feature")
        git(repo, "commit", "-q", "--allow-empty", "-m", "feature commit")
        # commit1 is parent of feature's tip → ancestor relation must hold
        assert_eq(dp.is_ancestor(repo, commit1, "refs/heads/feature"), True,
                  "initial commit is ancestor of feature tip")


def test_is_ancestor_false():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        git(repo, "checkout", "-q", "-b", "feature")
        git(repo, "commit", "-q", "--allow-empty", "-m", "feature commit")
        git(repo, "checkout", "-q", "master")
        git(repo, "commit", "-q", "--allow-empty", "-m", "second master commit")
        # master and feature have diverged after commit1
        assert_eq(dp.is_ancestor(repo, "refs/heads/master", "refs/heads/feature"), False,
                  "diverged master is not ancestor of feature")
        assert_eq(dp.is_ancestor(repo, "refs/heads/feature", "refs/heads/master"), False,
                  "diverged feature is not ancestor of master")


# ── resolve_default_ref / filter_active tests ──────────────


def _write_sibling_lock(repo: Path, sibling_name: str, branch: str, last_touched: str = "2026-05-17T00:00:00Z"):
    make_design_dir(repo, sibling_name, default_lock(sibling_name, branch=branch, last_touched=last_touched))


def _run_cli(repo: Path, design: str = "self", default_branch: str = "master") -> dict:
    script = Path(__file__).parent / "detect_parent.py"
    proc = subprocess.run(
        ["python3", str(script),
         "--repo", str(repo),
         "--design", design,
         "--default-branch", default_branch],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return {"_exit": proc.returncode, "_stderr": proc.stderr}
    return json.loads(proc.stdout)


def test_filter_single_inflight_parent():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        git(repo, "checkout", "-q", "-b", "tp/A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "A commit")
        git(repo, "checkout", "-q", "-b", "tp/X")  # current branch, descends from tp/A
        git(repo, "commit", "-q", "--allow-empty", "-m", "X commit")
        make_design_dir(repo, "self", default_lock("self", branch="tp/X"))
        _write_sibling_lock(repo, "A", "tp/A")
        result = _run_cli(repo)
        assert_eq(result["verdict"], "single", "single in-flight parent detected")
        assert_eq(len(result["candidates"]), 1, "exactly one candidate")
        assert_eq(result["candidates"][0]["design"], "A", "candidate is A")
        assert_eq(result["candidates"][0]["branch"], "tp/A", "branch is tp/A")


def test_filter_drops_merged_parent_via_origin():
    """tp/A merged to default; only refs/remotes/origin/master exists (no local master).

    Exercises the resolve_default_ref origin-fallback path.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        # init on 'main' so no refs/heads/master is auto-created
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "test")
        git(repo, "commit", "-q", "--allow-empty", "-m", "initial")
        git(repo, "checkout", "-q", "-b", "tp/A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "A commit")
        a_sha = git(repo, "rev-parse", "HEAD")
        # tp/X (current) descends from tp/A
        git(repo, "checkout", "-q", "-b", "tp/X")
        git(repo, "commit", "-q", "--allow-empty", "-m", "X commit")
        # simulate origin/master at the same commit as tp/A (i.e. master has merged A)
        git(repo, "update-ref", "refs/remotes/origin/master", a_sha)
        make_design_dir(repo, "self", default_lock("self", branch="tp/X"))
        _write_sibling_lock(repo, "A", "tp/A")
        result = _run_cli(repo)
        assert_eq(result["verdict"], "none", "merged parent filtered via origin fallback")
        assert_eq(result["candidates"], [], "no surviving candidates")


def test_filter_drops_merged_parent_via_local_default_fallback():
    """tp/A merged to local master; no origin/master configured. Heads-first resolution wins."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        git(repo, "checkout", "-q", "-b", "tp/A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "A commit")
        a_sha = git(repo, "rev-parse", "HEAD")
        # fast-forward master to include A's commit (merged)
        git(repo, "checkout", "-q", "master")
        git(repo, "merge", "-q", "--ff-only", a_sha)
        # tp/X (current) cut from tp/A so it descends from A
        git(repo, "checkout", "-q", "tp/A")
        git(repo, "checkout", "-q", "-b", "tp/X")
        git(repo, "commit", "-q", "--allow-empty", "-m", "X commit")
        make_design_dir(repo, "self", default_lock("self", branch="tp/X"))
        _write_sibling_lock(repo, "A", "tp/A")
        result = _run_cli(repo)
        assert_eq(result["verdict"], "none", "merged parent filtered via local master")
        assert_eq(result["candidates"], [], "no surviving candidates")


def test_filter_grandfathered_namespace():
    """Sibling lock declares a non-tp/* branch (e.g. legacy/feature-x). Algorithm reads from
    lock.json, so the branch name passes through verbatim — no namespace pattern matching."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        git(repo, "checkout", "-q", "-b", "legacy/feature-x")
        git(repo, "commit", "-q", "--allow-empty", "-m", "legacy commit")
        git(repo, "checkout", "-q", "-b", "tp/X")
        git(repo, "commit", "-q", "--allow-empty", "-m", "X commit")
        make_design_dir(repo, "self", default_lock("self", branch="tp/X"))
        _write_sibling_lock(repo, "legacy-design", "legacy/feature-x")
        result = _run_cli(repo)
        assert_eq(result["verdict"], "single", "any branch namespace is supported")
        assert_eq(result["candidates"][0]["branch"], "legacy/feature-x",
                  "branch passes through verbatim from lock.json")


# ── pick_leaf / verdict tests ───────────────────────────────


def test_verdict_multiple_for_disjoint_parents():
    """HEAD descends from two unrelated parents (via merge commit); neither is ancestor of the other.

    The CLI must return verdict=multiple with both candidates, sorted by last_touched desc.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        git(repo, "checkout", "-q", "-b", "tp/A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "A commit")
        git(repo, "checkout", "-q", "master")
        git(repo, "checkout", "-q", "-b", "tp/B")
        git(repo, "commit", "-q", "--allow-empty", "-m", "B commit")
        git(repo, "checkout", "-q", "-b", "tp/X")
        # Merge A into X so HEAD has both A and B as ancestors but neither contains the other
        git(repo, "merge", "-q", "--no-ff", "-m", "merge A", "tp/A")
        make_design_dir(repo, "self", default_lock("self", branch="tp/X"))
        # A is more recently touched than B → must appear first in sorted output
        _write_sibling_lock(repo, "A", "tp/A", last_touched="2026-05-17T01:00:00Z")
        _write_sibling_lock(repo, "B", "tp/B", last_touched="2026-05-15T01:00:00Z")
        result = _run_cli(repo)
        assert_eq(result["verdict"], "multiple", "disjoint parents → multiple")
        assert_eq(len(result["candidates"]), 2, "two candidates surface")
        assert_eq(result["candidates"][0]["design"], "A", "most recent first")
        assert_eq(result["candidates"][1]["design"], "B", "older follows")


def test_pick_leaf_chained_returns_direct_parent():
    """Chained designs: tp/B ← tp/A ← HEAD. tp/B is an ancestor of tp/A, so it's dropped."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        git(repo, "checkout", "-q", "-b", "tp/B")
        git(repo, "commit", "-q", "--allow-empty", "-m", "B commit")
        git(repo, "checkout", "-q", "-b", "tp/A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "A commit")
        git(repo, "checkout", "-q", "-b", "tp/X")
        git(repo, "commit", "-q", "--allow-empty", "-m", "X commit")
        make_design_dir(repo, "self", default_lock("self", branch="tp/X"))
        _write_sibling_lock(repo, "A", "tp/A", last_touched="2026-05-17T01:00:00Z")
        _write_sibling_lock(repo, "B", "tp/B", last_touched="2026-05-16T01:00:00Z")
        result = _run_cli(repo)
        assert_eq(result["verdict"], "single", "chained → direct parent only")
        assert_eq(len(result["candidates"]), 1, "only the leaf survives")
        assert_eq(result["candidates"][0]["design"], "A", "leaf is A (B is ancestor)")


# ── CLI tests ───────────────────────────────────────────────


def test_cli_no_siblings_returns_none_json():
    script = Path(__file__).parent / "detect_parent.py"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        make_repo(repo)
        make_design_dir(repo, "self", default_lock("self"))
        proc = subprocess.run(
            ["python3", str(script),
             "--repo", str(repo),
             "--design", "self",
             "--default-branch", "master"],
            capture_output=True, text=True,
        )
        assert_eq(proc.returncode, 0, f"CLI exits 0 (stderr: {proc.stderr})")
        payload = json.loads(proc.stdout)
        assert_eq(payload["verdict"], "none", "no siblings → verdict none")
        assert_eq(payload["candidates"], [], "candidates list is empty")
        assert_eq(payload["default_branch"], "master", "default_branch echoed back")


# ── Runner ──────────────────────────────────────────────────


if __name__ == "__main__":
    test_enumerate_returns_empty_when_no_siblings()
    test_enumerate_skips_self()
    test_enumerate_skips_missing_lock()
    test_resolve_ref_local()
    test_resolve_ref_origin_fallback()
    test_resolve_ref_missing_returns_none()
    test_is_ancestor_true()
    test_is_ancestor_false()
    test_filter_single_inflight_parent()
    test_filter_drops_merged_parent_via_origin()
    test_filter_drops_merged_parent_via_local_default_fallback()
    test_filter_grandfathered_namespace()
    test_pick_leaf_chained_returns_direct_parent()
    test_verdict_multiple_for_disjoint_parents()
    test_cli_no_siblings_returns_none_json()

    print(f"\n{'=' * 40}")
    print(f"{PASSED} passed, {FAILED} failed")
    if FAILED:
        sys.exit(1)
    print("ALL PASSED")
