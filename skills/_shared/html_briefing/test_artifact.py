"""Tests for html_briefing/artifact.py — per-round artifact path + git staging.

Covers Task 1.6 of promote-html-briefing plan:
  - briefing_artifact_path(decisions_dir, round_id) → path beside decisions.md
  - stage_briefing(repo, path) → git add only that path (scoped)
  - staged set is exactly the one HTML artifact (does not touch decisions.md)
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from artifact import briefing_artifact_path, stage_briefing

# Git identity env (mirrors conftest._GIT_IDENTITY_ENV — do NOT import
# the heavy _base_fixture; use a minimal fresh temp git repo per plan note)
_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo(path: Path) -> Path:
    """Init a minimal git repo at path with an empty initial commit."""
    env = {**os.environ, **_GIT_IDENTITY}
    subprocess.run(["git", "init", "-b", "master", "-q", str(path)], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        check=True, env=env, capture_output=True,
    )
    return path


def _git_status_porcelain(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# briefing_artifact_path
# ---------------------------------------------------------------------------

def test_artifact_path_beside_decisions_md(tmp_path):
    decisions_dir = tmp_path / "designs" / "my-slug"
    decisions_dir.mkdir(parents=True)
    # decisions.md lives in decisions_dir — path should be in that same dir
    path = briefing_artifact_path(decisions_dir, "r1")
    assert path.parent == decisions_dir


def test_artifact_path_deterministic_name(tmp_path):
    decisions_dir = tmp_path / "designs" / "my-slug"
    decisions_dir.mkdir(parents=True)
    path1 = briefing_artifact_path(decisions_dir, "r1")
    path2 = briefing_artifact_path(decisions_dir, "r1")
    assert path1 == path2


def test_artifact_path_includes_round_id(tmp_path):
    decisions_dir = tmp_path / "designs" / "my-slug"
    decisions_dir.mkdir(parents=True)
    path = briefing_artifact_path(decisions_dir, "round42")
    assert "round42" in path.name


def test_artifact_path_is_html(tmp_path):
    decisions_dir = tmp_path / "designs" / "my-slug"
    decisions_dir.mkdir(parents=True)
    path = briefing_artifact_path(decisions_dir, "r2")
    assert path.suffix == ".html"


def test_artifact_path_different_round_ids_differ(tmp_path):
    decisions_dir = tmp_path / "designs" / "my-slug"
    decisions_dir.mkdir(parents=True)
    path1 = briefing_artifact_path(decisions_dir, "r1")
    path2 = briefing_artifact_path(decisions_dir, "r2")
    assert path1 != path2


# ---------------------------------------------------------------------------
# stage_briefing
# ---------------------------------------------------------------------------

def test_stage_briefing_stages_exactly_one_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    decisions_dir = repo / "three-pillars-docs" / "tp-designs" / "my-slug"
    decisions_dir.mkdir(parents=True)

    # Write a decisions.md (untracked — must NOT appear staged after our call)
    decisions_md = decisions_dir / "decisions.md"
    decisions_md.write_text("# decisions\n")

    # Create the HTML artifact
    art_path = briefing_artifact_path(decisions_dir, "r1")
    art_path.write_text("<html>test</html>")

    stage_briefing(repo, art_path)

    status = _git_status_porcelain(repo)
    # Only count staged lines (index status A/M/D/R — not ?? untracked)
    staged_lines = [
        l for l in status.splitlines()
        if l and l[0] in "AMDRC" and l[1] == " "
    ]
    assert len(staged_lines) == 1, f"Expected 1 staged file, got staged:\n{staged_lines}\nfull status:\n{status}"
    # Must be 'A' (added) and point to our artifact
    assert staged_lines[0].startswith("A")
    assert art_path.name in staged_lines[0]


def test_stage_briefing_does_not_stage_decisions_md(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    decisions_dir = repo / "three-pillars-docs" / "tp-designs" / "my-slug"
    decisions_dir.mkdir(parents=True)

    decisions_md = decisions_dir / "decisions.md"
    decisions_md.write_text("# decisions\n")

    art_path = briefing_artifact_path(decisions_dir, "r1")
    art_path.write_text("<html>test</html>")

    stage_briefing(repo, art_path)

    status = _git_status_porcelain(repo)
    # decisions.md must not be staged (staged = index column A/M/D, not ??)
    staged_lines = [
        l for l in status.splitlines()
        if l and l[0] in "AMDRC" and l[1] == " "
    ]
    staged_names = " ".join(staged_lines)
    assert "decisions.md" not in staged_names


def test_stage_briefing_path_relative_to_repo(tmp_path):
    """stage_briefing must compute a repo-relative path for git add."""
    repo = _init_repo(tmp_path / "repo")
    decisions_dir = repo / "three-pillars-docs" / "tp-designs" / "slug2"
    decisions_dir.mkdir(parents=True)

    art_path = briefing_artifact_path(decisions_dir, "r3")
    art_path.write_text("<html/>")

    # Should not raise
    stage_briefing(repo, art_path)
    status = _git_status_porcelain(repo)
    assert art_path.name in status
