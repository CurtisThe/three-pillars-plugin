"""Tests for gc_candidate_branches.py — classifier core (Phase 1, B1–B6).

Covers:
  Task 1.1: enumerate_candidate_refs — per-surface rows + namespace guard (B1)
  Task 1.2: classify_candidates — MERGED / age / UNKNOWN partitions, 14d boundary
            (B2 / B3 / B5)
  Task 1.3: live-candidate exclusion (arg + worktree seams) + fail-closed (B4 / B6)

Run with: python -m pytest skills/_shared/test_gc_candidate_branches.py -n0 -q
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import gc_candidate_branches as gcb  # noqa: E402
import pr_state as ps  # noqa: E402

# ---------------------------------------------------------------------------
# Git fixtures — a REAL origin repo (separate from the work repo) so that a
# remote delete never touches a local ref. Mirrors test_sweep_candidates.py's
# self-origin push+fetch, but with a distinct origin so surfaces are isolated.
# ---------------------------------------------------------------------------

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@test.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@test.com",
    "HOME": os.environ.get("HOME", os.path.expanduser("~")),
    "PATH": os.environ.get("PATH", ""),
}


def _git(cwd: Path, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=_GIT_ENV,
    )


def make_origin_and_work(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare `origin` repo and a `work` repo with `origin` as remote."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "master")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "master")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "README").write_text("hello\n")
    _git(work, "add", "README")
    _git(work, "commit", "-m", "init")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "origin", "master")
    return origin, work


def add_local_candidate(work: Path, branch: str) -> None:
    """Create a local candidate branch at HEAD (no worktree)."""
    _git(work, "branch", branch)


def push_candidate(work: Path, branch: str) -> None:
    """Push a branch to origin and refresh the tracking cache (fetch)."""
    _git(work, "push", "origin", branch)
    _git(work, "fetch", "origin")


def make_remote_only(work: Path, branch: str) -> None:
    """Make `branch` exist ONLY on the remote surface: push, fetch, drop local."""
    add_local_candidate(work, branch)
    push_candidate(work, branch)
    _git(work, "branch", "-D", branch)  # tracking ref survives → remote-only


def tip_unixtime(work: Path, branch: str) -> int:
    """Committer-date unixtime of a local branch tip."""
    out = _git(work, "show", "-s", "--format=%ct", branch).stdout.strip()
    return int(out)


def add_tp_worktree(tmp_path: Path, work: Path, slug: str) -> Path:
    """Create a tp/{slug} branch with an attached worktree (in-flight signal)."""
    _git(work, "branch", f"tp/{slug}")
    wt = tmp_path / "wt" / slug
    wt.parent.mkdir(exist_ok=True)
    _git(work, "worktree", "add", str(wt), f"tp/{slug}")
    return wt


# ---------------------------------------------------------------------------
# Task 1.1 — B1: enumerate both surfaces, per-surface rows, namespace guard
# ---------------------------------------------------------------------------


def test_enumerate_per_surface_and_namespace_guard(tmp_path):
    """A both-surfaces ref yields TWO rows (one per surface); a remote-only ref
    yields one; non-candidate / malformed refs are ignored."""
    origin, work = make_origin_and_work(tmp_path)

    # candidate/a/single: exists BOTH locally and on origin
    add_local_candidate(work, "candidate/a/single")
    push_candidate(work, "candidate/a/single")

    # candidate/b/single2: remote-only
    make_remote_only(work, "candidate/b/single2")

    # non-candidate branch — must be ignored
    add_local_candidate(work, "tp/x")

    # malformed candidate shapes — must be ignored (extra segment / bad charset)
    add_local_candidate(work, "candidate/c/one/two")
    add_local_candidate(work, "candidate/BadSlug/single")

    refs = gcb.enumerate_candidate_refs(work)
    seen = {(r.branch, r.surface) for r in refs}

    assert ("candidate/a/single", "local") in seen
    assert ("candidate/a/single", "remote") in seen
    assert ("candidate/b/single2", "remote") in seen
    # remote-only b has no local row
    assert ("candidate/b/single2", "local") not in seen

    branches = {r.branch for r in refs}
    assert "tp/x" not in branches
    assert "candidate/c/one/two" not in branches
    assert "candidate/BadSlug/single" not in branches

    # slug/cand_id parsed
    a_local = next(r for r in refs if r.branch == "candidate/a/single" and r.surface == "local")
    assert a_local.slug == "a"
    assert a_local.cand_id == "single"


def test_enumerate_slug_scope(tmp_path):
    """slug= filters enumeration to one design."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    add_local_candidate(work, "candidate/b/single")

    refs = gcb.enumerate_candidate_refs(work, slug="a")
    slugs = {r.slug for r in refs}
    assert slugs == {"a"}


def test_enumerate_empty_committerdate_is_carried(tmp_path):
    """A ref row always carries a tip_unixtime token (numeric for real commits)."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    refs = gcb.enumerate_candidate_refs(work)
    row = next(r for r in refs if r.surface == "local")
    assert row.tip_unixtime.isdigit()


# ---------------------------------------------------------------------------
# Task 1.2 — B2 / B3 / B5: classification partitions + 14-day boundary
# ---------------------------------------------------------------------------


def _fake_pr(state: str):
    def _f(branch, cwd=None):
        return ps.PrVerdict(state=state, merged_at=None, evidence={})
    return _f


def test_classify_partitions(tmp_path, monkeypatch):
    """B2 (MERGED→deletable), B3 (age→deletable regardless of parent), and the
    two B5 negatives (UNKNOWN, OPEN → left-untouched)."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/merged-young/single")
    add_local_candidate(work, "candidate/old-abandoned/single")
    add_local_candidate(work, "candidate/unknown-young/single")
    add_local_candidate(work, "candidate/open-young/single")

    t = tip_unixtime(work, "candidate/old-abandoned/single")

    # --- B2: young + parent MERGED → deletable, axis=merge ---
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))
    rows = gcb.classify_candidates(work, slug="merged-young", now=t)
    row = rows[0]
    assert row.action == "deletable"
    assert row.evidence["axis"] == "merge"
    assert row.evidence["parent"] == "tp/merged-young"
    assert row.evidence["pr_state"] == "MERGED"

    # --- B3: >14d old + parent CLOSED → deletable on AGE (merge axis not reached) ---
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("CLOSED"))
    rows = gcb.classify_candidates(work, slug="old-abandoned", now=t + 15 * 86400)
    row = rows[0]
    assert row.action == "deletable"
    assert row.evidence["axis"] == "age"
    assert row.evidence["reason"] == "age>14d"

    # --- B5 negative: young + parent UNKNOWN → left-untouched ---
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("UNKNOWN"))
    rows = gcb.classify_candidates(work, slug="unknown-young", now=t)
    assert rows[0].action == "left-untouched"
    assert rows[0].evidence["pr_state"] == "UNKNOWN"

    # --- B5 negative: young + parent OPEN → left-untouched ---
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("OPEN"))
    rows = gcb.classify_candidates(work, slug="open-young", now=t)
    assert rows[0].action == "left-untouched"
    assert rows[0].evidence["pr_state"] == "OPEN"


def test_age_boundary_exact_14d(tmp_path, monkeypatch):
    """The 14-day boundary is strict `>`: t+14d exactly is NOT deletable,
    t+14d+1s IS deletable (pins > vs >=). No GIT_COMMITTER_DATE needed."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/boundary/single")
    # Parent not MERGED so only the age axis can make it deletable.
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("NO_PR"))
    t = tip_unixtime(work, "candidate/boundary/single")

    rows = gcb.classify_candidates(work, slug="boundary", now=t + 14 * 86400)
    assert rows[0].action == "left-untouched", "exactly 14d must NOT be deletable"

    rows = gcb.classify_candidates(work, slug="boundary", now=t + 14 * 86400 + 1)
    assert rows[0].action == "deletable"
    assert rows[0].evidence["axis"] == "age"


def test_empty_committerdate_is_age_unknown(monkeypatch):
    """Empty committerdate ⇒ age-unknown ⇒ never deletable-on-age (fail-safe).
    With parent not MERGED the row falls through to left-untouched."""
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("UNKNOWN"))

    def fake_enum(repo, *, slug=None):
        return [gcb.CandidateRef(
            branch="candidate/x/single", slug="x", cand_id="single",
            surface="local", tip_unixtime="")]

    monkeypatch.setattr(gcb, "enumerate_candidate_refs", fake_enum)
    # now huge — if empty date were read as 0, age would be enormous (false pos).
    rows = gcb.classify_candidates(Path("."), now=9_999_999_999)
    assert rows[0].action == "left-untouched"


def test_unknown_is_never_merged(tmp_path, monkeypatch):
    """UNKNOWN parent PR-state is never treated as MERGED (evidence discipline)."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/u/single")
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("UNKNOWN"))
    t = tip_unixtime(work, "candidate/u/single")
    rows = gcb.classify_candidates(work, slug="u", now=t)
    assert all(r.action != "deletable" for r in rows)


# ---------------------------------------------------------------------------
# Task 1.3 — B4 (live exclusion, two isolated seams) + B6 (fail-closed)
# ---------------------------------------------------------------------------


def test_live_via_arg_only(tmp_path, monkeypatch):
    """Seam 1: a candidate that is MERGED AND >14d old but named in `live`
    classifies protected — the live check beats BOTH disjuncts. Empty worktree
    set, so the arg seam is exercised in isolation."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/livearg/single")
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))
    t = tip_unixtime(work, "candidate/livearg/single")

    rows = gcb.classify_candidates(
        work, slug="livearg",
        live={("livearg", "single")},
        now=t + 100 * 86400,  # very old base — age axis would fire if not live
    )
    assert rows, "expected at least one row"
    for r in rows:
        assert r.action == "protected"
        assert r.evidence["reason"] == "live-candidate"


def test_live_via_worktree_only(tmp_path, monkeypatch):
    """Seam 2: empty `live` arg, but parent tp/{slug} has an attached worktree →
    protected. Isolated from seam 1 so a dead seam cannot hide behind the other.
    The candidate is MERGED + old so WITHOUT the worktree it would be deletable."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/livewt/single")
    add_tp_worktree(tmp_path, work, "livewt")
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))
    t = tip_unixtime(work, "candidate/livewt/single")

    rows = gcb.classify_candidates(
        work, slug="livewt", live=frozenset(), now=t + 100 * 86400,
    )
    assert rows
    for r in rows:
        assert r.action == "protected", (
            "parent tp/livewt has a live worktree → candidate must be protected"
        )
        assert r.evidence["reason"] == "live-candidate"


def test_live_arg_protects_both_surfaces(tmp_path, monkeypatch):
    """A live (slug,cand_id) protects BOTH the local and remote rows."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/both/single")
    push_candidate(work, "candidate/both/single")
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))
    t = tip_unixtime(work, "candidate/both/single")

    rows = gcb.classify_candidates(
        work, slug="both", live={("both", "single")}, now=t + 100 * 86400,
    )
    surfaces = {r.surface for r in rows}
    assert surfaces == {"local", "remote"}
    assert all(r.action == "protected" for r in rows)


def test_enumeration_failure_fail_closed(tmp_path, monkeypatch):
    """B6: for-each-ref failure ⇒ classify_candidates RAISES (nothing deleted)."""
    origin, work = make_origin_and_work(tmp_path)

    def boom(repo):
        raise RuntimeError("git for-each-ref failed (simulated)")

    monkeypatch.setattr(gcb, "_for_each_ref", boom)
    with pytest.raises(RuntimeError):
        gcb.classify_candidates(work)


def test_worktree_scan_failure_fail_closed(tmp_path, monkeypatch):
    """B6: worktree-scan failure ⇒ classify_candidates RAISES (fail-closed) so a
    live candidate can never slip through when the exclusion input is unresolvable."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/z/single")

    def boom(repo):
        raise RuntimeError("git worktree list failed (simulated)")

    monkeypatch.setattr(gcb, "_live_worktree_slugs", boom)
    with pytest.raises(RuntimeError):
        gcb.classify_candidates(work)


def test_enumeration_failure_on_non_repo_raises(tmp_path):
    """A real (non-mocked) for-each-ref failure on a non-git dir raises."""
    with pytest.raises(RuntimeError):
        gcb.enumerate_candidate_refs(tmp_path)
