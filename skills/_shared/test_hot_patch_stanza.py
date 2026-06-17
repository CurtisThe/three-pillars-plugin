"""test_hot_patch_stanza.py — arm-(b) wiring via the default CLI stanza path.

Item 16: verify that the default stanza mode (no --check-sha) enforces arm (b)
on every merged trailered commit, so an exclusion/diff-cap violation surfaces
when the helper is called the way framework-check.sh calls it (no --check-sha).

Tests here require full git fixture repos with merge commits.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


def _base_repo(tmp_path: Path, env: dict) -> Path:
    """Create a minimal git repo with one init commit on master."""
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
    return repo


def _merged_trailered_commit(
    repo: Path,
    files: dict,
    env: dict,
    commit_date: str = "2026-06-15T10:00:00Z",
) -> str:
    """Create a side branch with a trailered commit, merge it into master, return SHA."""
    side_env = dict(env)
    side_env["GIT_COMMITTER_DATE"] = commit_date
    side_env["GIT_AUTHOR_DATE"] = commit_date

    branch = "hot-patch/stanza-test"
    subprocess.run(["git", "checkout", "-b", branch],
                   cwd=str(repo), check=True, capture_output=True, env=env)

    for relpath, content in files.items():
        fpath = repo / relpath
        fpath.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            fpath.write_bytes(content)
        else:
            fpath.write_text(content)
        subprocess.run(["git", "add", relpath], cwd=str(repo), check=True)

    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: stanza test",
         "-m", "Hotfix: stanza test"],
        cwd=str(repo), check=True, capture_output=True, env=side_env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    subprocess.run(["git", "checkout", "master"],
                   cwd=str(repo), check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "merge", "--no-ff", branch, "-m", f"Merge {branch}"],
        cwd=str(repo), check=True, capture_output=True, env=side_env,
    )
    return sha


@pytest.fixture
def git_env():
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)
    return env


# ---------------------------------------------------------------------------
# Arm (b) via default stanza path
# ---------------------------------------------------------------------------

def test_arm_b_exclusion_via_stanza_path(tmp_path, git_env):
    """Default CLI mode enforces arm (b): merged trailered commit touching an
    excluded file exits 1 with VIOLATION exclusion."""
    repo = _base_repo(tmp_path, git_env)

    # Provision ledger file so arm (a) passes (only arm (b) should fire)
    ledger_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    ledger_dir.mkdir(parents=True)
    ledger_path = ledger_dir / "hot-patches.md"

    sha = _merged_trailered_commit(
        repo,
        {"framework-check.sh": "#!/bin/bash\n# tampered\n"},
        git_env,
    )

    # Write ledger entry to silence arm (a)
    ledger_path.write_text(
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        f"- {sha} | 2026-06-15 | trigger: stanza test | broke: x | fix: y "
        "| touched: framework-check.sh\n"
    )

    result = subprocess.run(
        ["python3", str(REPO_ROOT / "skills/_shared/hot_patch_check.py"),
         "--repo-root", str(repo),
         "--now", "2099-01-01T00:00:00Z"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, (
        f"Stanza path must exit 1 on exclusion violation; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "VIOLATION" in combined, f"Must emit VIOLATION; got {combined!r}"
    assert "exclusion" in combined, f"Must cite exclusion; got {combined!r}"


def test_arm_b_diff_cap_via_stanza_path(tmp_path, git_env):
    """Default CLI mode enforces arm (b): merged trailered commit exceeding diff
    cap exits 1 with VIOLATION diff-cap."""
    repo = _base_repo(tmp_path, git_env)

    ledger_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    ledger_dir.mkdir(parents=True)
    ledger_path = ledger_dir / "hot-patches.md"

    # 200-line file → 200 adds → exceeds 150 cap
    big_content = "\n".join(f"line{i}" for i in range(200)) + "\n"
    sha = _merged_trailered_commit(
        repo,
        {"skills/tp-guide/SKILL.md": big_content},
        git_env,
    )

    ledger_path.write_text(
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        f"- {sha} | 2026-06-15 | trigger: cap test | broke: x | fix: y "
        "| touched: skills/tp-guide/SKILL.md\n"
    )

    result = subprocess.run(
        ["python3", str(REPO_ROOT / "skills/_shared/hot_patch_check.py"),
         "--repo-root", str(repo),
         "--now", "2099-01-01T00:00:00Z"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, (
        f"Stanza path must exit 1 on diff-cap violation; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "diff-cap" in result.stdout + result.stderr, "Must cite diff-cap"
