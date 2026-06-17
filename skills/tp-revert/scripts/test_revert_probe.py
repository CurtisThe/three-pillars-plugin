"""Tests for revert_probe: merge_depth and resolve_target.

File cap: <=160 lines.
"""

from __future__ import annotations

import subprocess

import pytest

from _probe_fixtures import MergeRepo, first_parent_commit, land_merge, make_gh_fn
from _probe_fixtures import merge_repo  # noqa: F401  — registers pytest fixture
from revert_probe import MergeTarget, merge_depth, resolve_target


# ---------------------------------------------------------------------------
# Task 1.1: merge_depth
# ---------------------------------------------------------------------------

def test_merge_depth_zero_newest(merge_repo: MergeRepo) -> None:
    sha = land_merge(merge_repo, "feat-a", {"a.txt": "hello\n"})
    assert merge_depth(str(merge_repo.clone), sha, "master") == 0


def test_merge_depth_one_after_commit(merge_repo: MergeRepo) -> None:
    sha = land_merge(merge_repo, "feat-b", {"b.txt": "world\n"})
    first_parent_commit(merge_repo, {"extra.txt": "x\n"})
    assert merge_depth(str(merge_repo.clone), sha, "master") == 1


def test_merge_depth_n_after_n_commits(merge_repo: MergeRepo) -> None:
    sha = land_merge(merge_repo, "feat-c", {"c.txt": "c\n"})
    for i in range(3):
        first_parent_commit(merge_repo, {f"fp{i}.txt": f"{i}\n"})
    assert merge_depth(str(merge_repo.clone), sha, "master") == 3


def test_merge_depth_first_parent_only(merge_repo: MergeRepo) -> None:
    """Subsequent merge landing counts as 1 first-parent step, not 2."""
    sha = land_merge(merge_repo, "feat-d", {"d.txt": "d\n"})
    land_merge(merge_repo, "feat-e", {"e.txt": "e\n"})
    assert merge_depth(str(merge_repo.clone), sha, "master") == 1


# ---------------------------------------------------------------------------
# Task 1.2: resolve_target
# ---------------------------------------------------------------------------

def test_resolve_target_pr_merged(merge_repo: MergeRepo) -> None:
    merge_sha = land_merge(merge_repo, "tp/myslug", {"x.txt": "x\n"})
    data = {"mergeCommit": {"oid": merge_sha}, "headRefName": "tp/myslug",
            "baseRefName": "master", "state": "MERGED"}
    r = resolve_target(str(merge_repo.clone), pr=7, base="master",
                       gh_fn=make_gh_fn(data))
    assert isinstance(r, MergeTarget)
    assert r.merge_sha == merge_sha and r.pr_number == 7
    assert r.slug == "myslug" and r.error is None


def test_resolve_target_pr_non_tp_slug(merge_repo: MergeRepo) -> None:
    merge_sha = land_merge(merge_repo, "custom", {"y.txt": "y\n"})
    data = {"mergeCommit": {"oid": merge_sha}, "headRefName": "custom",
            "baseRefName": "master", "state": "MERGED"}
    r = resolve_target(str(merge_repo.clone), pr=8, base="master",
                       gh_fn=make_gh_fn(data))
    assert r.slug is None and r.error is None


def test_resolve_target_pr_unmerged(merge_repo: MergeRepo) -> None:
    data = {"mergeCommit": None, "headRefName": "tp/foo",
            "baseRefName": "master", "state": "OPEN"}
    r = resolve_target(str(merge_repo.clone), pr=9, base="master",
                       gh_fn=make_gh_fn(data))
    assert r.error is not None
    assert "merged" in r.error.lower()


def test_resolve_target_pr_open_with_merge_commit(merge_repo: MergeRepo) -> None:
    """state=OPEN + non-null mergeCommit must still return error (state gate)."""
    merge_sha = land_merge(merge_repo, "tp/openslug", {"op.txt": "op\n"})
    data = {"mergeCommit": {"oid": merge_sha}, "headRefName": "tp/openslug",
            "baseRefName": "master", "state": "OPEN"}
    r = resolve_target(str(merge_repo.clone), pr=10, base="master",
                       gh_fn=make_gh_fn(data))
    assert r.error is not None
    assert "merged" in r.error.lower()


def test_resolve_target_sha_non_merge(merge_repo: MergeRepo) -> None:
    plain_sha = first_parent_commit(merge_repo, {"z.txt": "z\n"})
    r = resolve_target(str(merge_repo.clone), sha=plain_sha, base="master")
    assert r.error is not None


def test_resolve_target_sha_unreachable(merge_repo: MergeRepo) -> None:
    """Two-parent sha not on origin/master first-parent -> error.

    Built as a merge commit on a side branch never merged/pushed to master.
    Preconditions (2-parent + not-reachable) are asserted inside the fixture.
    """
    clone = merge_repo.clone
    g = lambda *a: subprocess.run(["git", "-C", str(clone)] + list(a),
                                  check=True, capture_output=True)
    # side branch: feat-a merged into side (never touches master)
    g("checkout", "-b", "side-a")
    (clone / "sa.txt").write_text("a\n"); g("add", "sa.txt")
    g("commit", "-m", "side a")
    g("checkout", "-b", "side-b", "master")
    (clone / "sb.txt").write_text("b\n"); g("add", "sb.txt")
    g("commit", "-m", "side b")
    g("checkout", "side-a")
    g("merge", "--no-ff", "side-b", "-m", "Merge side-b into side-a")
    two_parent_sha = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip()

    # precondition: 2 parents
    p = subprocess.run(
        ["git", "-C", str(clone), "rev-parse",
         two_parent_sha + "^1", two_parent_sha + "^2"],
        capture_output=True
    )
    assert p.returncode == 0, "fixture must produce a 2-parent commit"

    # precondition: not reachable from origin/master first-parent
    rch = subprocess.run(
        ["git", "-C", str(clone), "merge-base", "--is-ancestor",
         two_parent_sha, "origin/master"],
        capture_output=True
    )
    assert rch.returncode != 0, "fixture sha must not be on origin/master"

    r = resolve_target(str(clone), sha=two_parent_sha, base="master")
    assert r.error is not None


def test_resolve_target_sha_valid(merge_repo: MergeRepo) -> None:
    merge_sha = land_merge(merge_repo, "tp/validslug", {"v.txt": "v\n"})
    r = resolve_target(str(merge_repo.clone), sha=merge_sha, base="master")
    assert isinstance(r, MergeTarget)
    assert r.merge_sha == merge_sha and r.pr_number is None and r.error is None


def test_resolve_target_sha_abbreviated(merge_repo: MergeRepo) -> None:
    """12-char abbreviated sha of a valid landing resolves to full sha, error=None."""
    merge_sha = land_merge(merge_repo, "tp/abbrevslug", {"ab.txt": "ab\n"})
    abbrev = merge_sha[:12]
    r = resolve_target(str(merge_repo.clone), sha=abbrev, base="master")
    assert r.error is None, f"abbreviated sha should resolve; got error: {r.error}"
    assert r.merge_sha == merge_sha, (
        f"full sha should be returned; got {r.merge_sha!r}")
    assert r.pr_number is None


def test_resolve_target_sha_garbage(merge_repo: MergeRepo) -> None:
    """Garbage sha returns error field set, exits 0 (no exception raised)."""
    r = resolve_target(str(merge_repo.clone), sha="deadbeefdeadbeef", base="master")
    assert r.error is not None
    assert "unknown object" in r.error


def test_resolve_target_sha_base_typo(merge_repo: MergeRepo) -> None:
    """Unresolvable --base (typo) returns error field, does not raise."""
    merge_sha = land_merge(merge_repo, "tp/typo-base", {"tb.txt": "tb\n"})
    r = resolve_target(str(merge_repo.clone), sha=merge_sha, base="not-a-branch")
    assert r.error is not None, "bad base ref should produce error field"


def test_resolve_target_sha_inner_merge(merge_repo: MergeRepo) -> None:
    """Inner merge reachable from origin/master via second-parent only is rejected.

    Graph:
      master: A -- merge(feat-outer) --(fp)--> master HEAD
      feat-outer branch: feat-outer-commit -- merge(inner-feat) [inner merge]
      inner-feat branch: inner-feat-commit

    The inner merge commit IS reachable from origin/master (via second-parent of
    the outer merge) but is NOT on the first-parent chain. resolve_target must
    return error, pinning the --first-parent specificity.

    MUTATION-VERIFY: temporarily remove --first-parent from the fps rev-list call
    in resolve_target; this test FAILS (inner merge becomes reachable, returns
    error=None). Restore --first-parent; test is GREEN again.
    """
    clone = merge_repo.clone
    g = lambda *a: subprocess.run(
        ["git", "-C", str(clone)] + list(a),
        check=True, capture_output=True, text=True
    )

    # Build inner-feat branch off master
    g("checkout", "-b", "inner-feat")
    (clone / "inner.txt").write_text("inner\n")
    g("add", "inner.txt")
    g("commit", "-m", "feat: inner")

    # Build feat-outer branch off master, then merge inner-feat into it
    g("checkout", "-b", "feat-outer", "master")
    (clone / "outer.txt").write_text("outer\n")
    g("add", "outer.txt")
    g("commit", "-m", "feat: outer")
    g("merge", "--no-ff", "inner-feat", "-m", "Merge inner-feat into feat-outer")
    inner_merge_sha = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Now land feat-outer into master (outer merge is on first-parent chain)
    g("checkout", "master")
    g("merge", "--no-ff", "feat-outer", "-m", "Merge feat-outer into master")
    g("push", "origin", "master")

    # Verify preconditions
    # inner_merge_sha has 2 parents
    p = subprocess.run(
        ["git", "-C", str(clone), "rev-parse",
         inner_merge_sha + "^1", inner_merge_sha + "^2"],
        capture_output=True,
    )
    assert p.returncode == 0, "inner merge must have 2 parents"

    # inner_merge_sha is reachable from origin/master (via 2nd-parent path)
    reachable = subprocess.run(
        ["git", "-C", str(clone), "merge-base", "--is-ancestor",
         inner_merge_sha, "origin/master"],
        capture_output=True,
    )
    assert reachable.returncode == 0, (
        "inner merge must be reachable from origin/master (via 2nd-parent)")

    r = resolve_target(str(clone), sha=inner_merge_sha, base="master")
    assert r.error is not None, (
        "inner merge reachable only via second-parent must be rejected"
    )
