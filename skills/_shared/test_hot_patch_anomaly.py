"""test_hot_patch_anomaly.py — check_anomaly post-baseline scan tests.

Covers Task 1.3 (Behavior 5: anomaly detection) from the hot-patch-protocol design.
Ledger and coverage tests live in test_hot_patch_ledger.py (split by responsibility).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


@pytest.fixture
def anomaly_repo(tmp_path):
    """Git repo with one commit BEFORE the baseline (must always be silent)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)

    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=str(repo),
                   check=True, capture_output=True)

    before_env = dict(env)
    before_env["GIT_COMMITTER_DATE"] = "2026-06-10T00:00:00Z"
    before_env["GIT_AUTHOR_DATE"] = "2026-06-10T00:00:00Z"
    (repo / "skills").mkdir()
    (repo / "skills" / "old.py").write_text("# old\n")
    subprocess.run(["git", "add", "skills/old.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "old framework change"],
        cwd=str(repo), check=True, capture_output=True, env=before_env,
    )

    return {"repo": repo, "env": env}


def test_anomaly_pre_baseline_silent(anomaly_repo):
    """Commits dated before the baseline never flag as anomalies (Behavior 5)."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    result = check_anomaly(repo=str(repo))
    assert result == [], f"Pre-baseline commits must be silent; got {result}"


def test_anomaly_post_baseline_non_merge_flagged(anomaly_repo):
    """A non-merge commit touching framework paths after baseline is flagged."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    (repo / "skills" / "new.py").write_text("# new\n")
    subprocess.run(["git", "add", "skills/new.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "post-baseline framework change"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )

    result = check_anomaly(repo=str(repo))
    assert len(result) >= 1, "Post-baseline non-merge touching skills/ must be flagged"


def test_anomaly_post_baseline_merge_silent(anomaly_repo):
    """A merge commit on first-parent after baseline is silent (PR merges are OK)."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    subprocess.run(["git", "checkout", "-b", "feat"], cwd=str(repo),
                   check=True, capture_output=True, env=env)
    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    (repo / "skills" / "feat.py").write_text("# feat\n")
    subprocess.run(["git", "add", "skills/feat.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: add feature"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )
    subprocess.run(["git", "checkout", "master"], cwd=str(repo),
                   check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "merge", "--no-ff", "feat", "-m", "Merge feat"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )

    result = check_anomaly(repo=str(repo))
    assert result == [], f"Merge commits must be silent; got {result}"


def test_anomaly_docs_only_silent(anomaly_repo):
    """Commits touching only three-pillars-docs/** are silent (orchestration carve-out)."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    docs_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    docs_dir.mkdir(parents=True)
    (docs_dir / "hot-patches.md").write_text("# Hot-patch ledger — append-only\n")
    subprocess.run(["git", "add", "three-pillars-docs/"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "docs: update orchestration ledger"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )

    result = check_anomaly(repo=str(repo))
    assert result == [], f"Docs-only commits must be silent; got {result}"


def test_anomaly_degraded_clone_warns_not_fails(tmp_path):
    """When neither master nor origin/master resolves, anomaly check warns+returns []."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True,
                   capture_output=True)
    with pytest.warns(UserWarning, match="anomaly scan skipped"):
        result = check_anomaly(repo=str(repo))
    assert result == [], f"Degraded clone must return empty list; got {result}"


def test_anomaly_framework_check_sh_flagged(anomaly_repo):
    """A non-merge commit touching framework-check.sh after baseline is flagged."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    (repo / "framework-check.sh").write_text("#!/bin/bash\necho hi\n")
    subprocess.run(["git", "add", "framework-check.sh"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "patch: edit framework-check.sh directly"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )

    result = check_anomaly(repo=str(repo))
    assert len(result) >= 1, "framework-check.sh edit after baseline must be flagged"


def test_anomaly_dot_three_pillars_flagged(anomaly_repo):
    """A non-merge commit touching .three-pillars/ after baseline is flagged."""
    from skills._shared.hot_patch_check import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    (repo / ".three-pillars").mkdir(exist_ok=True)
    (repo / ".three-pillars" / "config.json").write_text("{}\n")
    subprocess.run(["git", "add", ".three-pillars/config.json"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "patch: edit .three-pillars config"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )

    result = check_anomaly(repo=str(repo))
    assert len(result) >= 1, ".three-pillars/ edit after baseline must be flagged"


# ---------------------------------------------------------------------------
# HEAD-only scan: trailered commit on an UNMERGED side branch (item 16)
# ---------------------------------------------------------------------------

def test_head_only_scan_unmerged_trailered_branch_no_ledger_obligation(anomaly_repo):
    """A trailered hot-patch commit on an unmerged side branch never incurs a ledger
    obligation — _trailered_commits_on_head scans HEAD (master) only, not --all."""
    from skills._shared.hot_patch_ledger import (  # noqa: PLC0415
        _trailered_commits_on_head,
    )

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])
    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"

    # Create a side branch with a trailered commit (never merged to master)
    subprocess.run(["git", "checkout", "-b", "hot-patch/test"],
                   cwd=str(repo), check=True, capture_output=True, env=env)
    (repo / "unmerged_fix.py").write_text("# unmerged\n")
    subprocess.run(["git", "add", "unmerged_fix.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: unmerged fix",
         "-m", "Hotfix: unmerged"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )
    # Return to master without merging
    subprocess.run(["git", "checkout", "master"],
                   cwd=str(repo), check=True, capture_output=True, env=env)

    # The unmerged side-branch commit must NOT appear in the trailered list
    trailered = _trailered_commits_on_head(str(repo))
    assert trailered == [], (
        f"Trailered commit on unmerged branch must not appear in HEAD scan; got {trailered}"
    )


# ---------------------------------------------------------------------------
# Fail-closed plumbing pins (fix #6: structural)
# ---------------------------------------------------------------------------

def _repo_with_bogus_master(tmp_path: Path, env: dict) -> Path:
    """Create a real git repo, then corrupt the master ref to a bogus SHA.

    After this, rev-parse master succeeds (ref resolves via packed-refs) but
    git log / git show fail (SHA doesn't exist in the object store).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=str(repo),
                   check=True, capture_output=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    # Pack refs, then overwrite the packed-refs file with a bogus SHA for master.
    # git rev-parse --verify master resolves the packed ref (exit 0) but
    # git log fails because deadbeef... doesn't exist in the object store.
    subprocess.run(["git", "pack-refs", "--all"], cwd=str(repo), check=True,
                   capture_output=True)
    bogus_sha = "deadbeef" * 5  # 40-char hex string
    packed_refs = repo / ".git" / "packed-refs"
    packed_refs.write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n"
        f"{bogus_sha} refs/heads/master\n"
    )
    return repo


def test_trailered_commits_raises_on_git_log_failure(tmp_path):
    """_trailered_commits_on_head raises RuntimeError when git log fails."""
    from skills._shared.hot_patch_ledger import _trailered_commits_on_head  # noqa: PLC0415

    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)
    repo = _repo_with_bogus_master(tmp_path, env)

    with pytest.raises(RuntimeError, match="git log failed"):
        _trailered_commits_on_head(str(repo))


def test_check_anomaly_raises_on_git_log_failure(tmp_path):
    """check_anomaly raises RuntimeError when git log fails (fail-closed)."""
    from skills._shared.hot_patch_ledger import check_anomaly  # noqa: PLC0415

    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)
    repo = _repo_with_bogus_master(tmp_path, env)

    with pytest.raises(RuntimeError, match="git log"):
        check_anomaly(str(repo))


def test_date_unreadable_violation(tmp_path):
    """check_ledger_coverage emits date-unreadable VIOLATION when _commit_date_utc
    returns None (e.g., after git log plumbing failure for that SHA)."""
    from unittest.mock import patch  # noqa: PLC0415
    from skills._shared import hot_patch_ledger  # noqa: PLC0415

    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=str(repo),
                   check=True, capture_output=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "--trailer", "hot-patch: date test", "-m", "Hotfix: date"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )

    # Patch _commit_date_utc to return None for any SHA
    with patch.object(hot_patch_ledger, "_commit_date_utc", return_value=None):
        violations = hot_patch_ledger.check_ledger_coverage(
            repo=str(repo),
            ledger_text="# Hot-patch ledger — append-only\n\n<!-- entries below -->\n",
            now_iso="2099-01-01T00:00:00Z",
        )
    assert any("date-unreadable" in v for v in violations), (
        f"Must emit date-unreadable VIOLATION when _commit_date_utc returns None; "
        f"got {violations}"
    )


# ---------------------------------------------------------------------------
# Arm-b: pre-baseline trailered commits ARE swept (fix #12: minor)
# ---------------------------------------------------------------------------

def test_arm_b_sweeps_pre_baseline_trailered_commit(anomaly_repo):
    """A trailered commit dated BEFORE the baseline is still scanned by arm (b).

    Only arm (c) is baseline-scoped; arms (a)/(b) scan the full trailered
    commit history. This pins the fail-closed direction.
    """
    from skills._shared.hot_patch_ledger import _trailered_commits_on_head  # noqa: PLC0415
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    # Pre-baseline date — before the BASELINE constant
    pre_env = dict(env)
    pre_env["GIT_COMMITTER_DATE"] = "2026-06-01T00:00:00Z"
    pre_env["GIT_AUTHOR_DATE"] = "2026-06-01T00:00:00Z"

    # Trailered commit touching an excluded file (framework-check.sh), dated pre-baseline
    (repo / "framework-check.sh").write_text("#!/bin/bash\n# pre-baseline tamper\n")
    subprocess.run(["git", "add", "framework-check.sh"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: pre-baseline sweep test",
         "-m", "Hotfix: pre-baseline"],
        cwd=str(repo), check=True, capture_output=True, env=pre_env,
    )
    pre_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    # The pre-baseline trailered commit must appear in the arm (b) scan
    trailered = _trailered_commits_on_head(str(repo))
    assert pre_sha in trailered, (
        f"Pre-baseline trailered commit must appear in full-history arm (b) scan; "
        f"trailered={trailered}"
    )
    # And arm (b) exclusion check must fire on it
    violations = check_exclusions(sha=pre_sha, repo=str(repo))
    assert len(violations) >= 1, (
        f"Arm (b) must flag pre-baseline trailered commit touching excluded file; "
        f"got {violations}"
    )


# ---------------------------------------------------------------------------
# --since-as-filter regression: backdated commit does not hide earlier history
# (fix #4: structural)
# ---------------------------------------------------------------------------

def test_since_as_filter_backdated_does_not_hide_post_baseline(anomaly_repo):
    """A backdated (pre-baseline) commit does not truncate the anomaly scan.

    History shape: post-baseline A <- backdated pre-baseline B <- post-baseline C
    Both A and C must be flagged despite B appearing to break the chain.
    (This is the regression case that --since alone fails but --since-as-filter passes.)
    """
    from skills._shared.hot_patch_ledger import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])

    # Commit C: post-baseline framework change
    after_c_env = dict(env)
    after_c_env["GIT_COMMITTER_DATE"] = "2026-06-20T00:00:00Z"
    after_c_env["GIT_AUTHOR_DATE"] = "2026-06-20T00:00:00Z"
    (repo / "skills" / "c.py").write_text("# C\n")
    subprocess.run(["git", "add", "skills/c.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "C: post-baseline"],
        cwd=str(repo), check=True, capture_output=True, env=after_c_env,
    )

    # Commit B: backdated to pre-baseline (GIT_COMMITTER_DATE in the past)
    back_env = dict(env)
    back_env["GIT_COMMITTER_DATE"] = "2026-06-01T00:00:00Z"
    back_env["GIT_AUTHOR_DATE"] = "2026-06-01T00:00:00Z"
    (repo / "skills" / "b.py").write_text("# B\n")
    subprocess.run(["git", "add", "skills/b.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "B: backdated"],
        cwd=str(repo), check=True, capture_output=True, env=back_env,
    )

    # Commit A: post-baseline framework change (committed BEFORE B in log, but after)
    after_a_env = dict(env)
    after_a_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_a_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    (repo / "skills" / "a.py").write_text("# A\n")
    subprocess.run(["git", "add", "skills/a.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "A: post-baseline"],
        cwd=str(repo), check=True, capture_output=True, env=after_a_env,
    )

    violations = check_anomaly(repo=str(repo))
    # A and C must both be flagged (two post-baseline framework-touching commits)
    assert len(violations) >= 2, (
        f"Both post-baseline commits (A and C) must be flagged even with backdated B; "
        f"got {len(violations)} violation(s): {violations}"
    )


# ---------------------------------------------------------------------------
# Fix 1: core.quotepath=false — non-ASCII paths prefix-match correctly
# ---------------------------------------------------------------------------

def test_quotepath_non_ascii_flagged_by_check_anomaly(anomaly_repo):
    """check_anomaly flags a post-baseline commit touching a non-ASCII-named file."""
    from skills._shared.hot_patch_ledger import check_anomaly  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])
    after_env = dict(env)
    after_env["GIT_COMMITTER_DATE"] = "2026-06-15T00:00:00Z"
    after_env["GIT_AUTHOR_DATE"] = "2026-06-15T00:00:00Z"
    (repo / "skills" / "caché.py").write_text("# non-ascii\n")
    subprocess.run(["git", "add", "skills/caché.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "post-baseline non-ascii path"],
        cwd=str(repo), check=True, capture_output=True, env=after_env,
    )
    violations = check_anomaly(repo=str(repo))
    assert len(violations) >= 1, (
        "Non-ASCII path under skills/ must be flagged by check_anomaly"
    )


def test_quotepath_non_ascii_flagged_by_check_exclusions(anomaly_repo):
    """check_exclusions catches a trailered commit touching a non-ASCII .three-pillars/ path."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    env = dict(anomaly_repo["env"])
    (repo / ".three-pillars").mkdir(exist_ok=True)
    (repo / ".three-pillars" / "café.txt").write_text("non-ascii\n")
    subprocess.run(["git", "add", ".three-pillars/café.txt"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "--trailer", "hot-patch: non-ascii test",
         "-m", "Hotfix: non-ascii exclusion"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, (
        "Non-ASCII path under .three-pillars/ must be caught by check_exclusions"
    )


# ---------------------------------------------------------------------------
# Fix 3: _commit_files_for_anomaly fail-closed (check=True pin)
# ---------------------------------------------------------------------------

def test_commit_files_for_anomaly_raises_on_bad_sha(anomaly_repo):
    """_commit_files_for_anomaly raises CalledProcessError on a bad SHA (fail-closed).

    Mutation-verify: removing check=True would cause it to silently return []
    instead of raising, hiding anomalous commits from the scan.
    """
    from skills._shared.hot_patch_ledger import _commit_files_for_anomaly  # noqa: PLC0415
    import subprocess as sp  # noqa: PLC0415

    repo = anomaly_repo["repo"]
    with pytest.raises(sp.CalledProcessError):
        _commit_files_for_anomaly("deadbeef" * 5, str(repo))
