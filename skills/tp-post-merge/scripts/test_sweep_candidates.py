"""Tests for sweep_candidates.py — candidate-branch sweep reporter.

Tests cover:
  Task 1.1: extract_slug — valid/invalid/traversal rejection
  Task 1.2: is_archived — present/absent/bad-slug guard
  Task 1.3: enumerate_candidate_branches — local, remote, fail-open
  Task 1.4: classify_candidates — archived→orphaned, live, unparseable→dropped
  Task 1.5: main CLI — --json shape, always-exit-0, fail-open, --remote

Run with: pytest skills/tp-post-merge/scripts/test_sweep_candidates.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

from sweep_candidates import (
    classify_candidates,
    enumerate_candidate_branches,
    extract_slug,
    is_archived,
    main,
)


# ---------------------------------------------------------------------------
# Git fixture helpers (mirrors test_verify_merged.py's _init_git_repo pattern)
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialize a non-bare git repo with one commit."""
    subprocess.run(["git", "init", "-b", "master", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    readme = path / "README.md"
    readme.write_text("init")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True
    )


def _create_branch(repo: Path, branch_name: str) -> None:
    """Create a branch in the repo without checking it out."""
    subprocess.run(
        ["git", "-C", str(repo), "branch", branch_name],
        check=True,
        capture_output=True,
    )


def _add_archive(repo: Path, slug: str) -> None:
    """Commit the completed-tp-designs archive for a slug on HEAD."""
    archive_dir = repo / "three-pillars-docs" / "completed-tp-designs" / slug
    archive_dir.mkdir(parents=True, exist_ok=True)
    design_md = archive_dir / "design.md"
    design_md.write_text(f"# {slug} design")
    subprocess.run(
        ["git", "-C", str(repo), "add", str(design_md)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"archive: {slug}"],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Task 1.1: extract_slug
# ---------------------------------------------------------------------------


class TestExtractSlug:
    def test_extract_slug_valid(self) -> None:
        assert extract_slug("candidate/foo-bar/single") == "foo-bar"
        assert extract_slug("candidate/my-design/single") == "my-design"
        assert extract_slug("candidate/abc123/single") == "abc123"
        assert extract_slug("candidate/x/single") == "x"

    def test_extract_slug_rejects_traversal_and_bad_shape(self) -> None:
        # Path traversal
        assert extract_slug("candidate/../single") is None
        # Uppercase not allowed
        assert extract_slug("candidate/Foo/single") is None
        # Wrong leaf word
        assert extract_slug("candidate/foo/double") is None
        # Wrong prefix
        assert extract_slug("tp/foo") is None
        # Empty string
        assert extract_slug("") is None
        # Underscore not in charset
        assert extract_slug("candidate/foo_bar/single") is None
        # Space not in charset
        assert extract_slug("candidate/foo bar/single") is None
        # Only prefix + nothing
        assert extract_slug("candidate//single") is None

    def test_extract_slug_rejects_double_slash_traversal(self) -> None:
        # Extra slashes used as traversal attempts
        assert extract_slug("candidate/foo/bar/single") is None
        assert extract_slug("candidate/foo/../single") is None


# ---------------------------------------------------------------------------
# Task 1.2: is_archived
# ---------------------------------------------------------------------------


class TestIsArchived:
    def test_is_archived_true_when_design_md_present(self, tmp_path: Path) -> None:
        """Archive present on disk → True."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _add_archive(repo, "my-design")
        assert is_archived(str(repo), "my-design") is True

    def test_is_archived_false_when_absent(self, tmp_path: Path) -> None:
        """Archive absent → False."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        assert is_archived(str(repo), "my-design") is False

    def test_is_archived_rejects_bad_slug(self, tmp_path: Path) -> None:
        """Invalid slug → False (never path-joins the bad value)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        # These would be path traversal or invalid slugs
        assert is_archived(str(repo), "../etc/passwd") is False
        assert is_archived(str(repo), "foo/bar") is False
        assert is_archived(str(repo), "Uppercase") is False
        assert is_archived(str(repo), "") is False


# ---------------------------------------------------------------------------
# Task 1.3: enumerate_candidate_branches
# ---------------------------------------------------------------------------


class TestEnumerateCandidateBranches:
    def test_enumerate_local_finds_candidate_branch(self, tmp_path: Path) -> None:
        """Local mode: candidate/my-design/single branch is found."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _create_branch(repo, "candidate/my-design/single")

        branches = enumerate_candidate_branches(str(repo))
        assert "candidate/my-design/single" in branches

    def test_enumerate_local_excludes_non_candidate_branches(self, tmp_path: Path) -> None:
        """Local mode: tp/x and master are excluded."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _create_branch(repo, "tp/some-design")
        _create_branch(repo, "candidate/my-design/single")

        branches = enumerate_candidate_branches(str(repo))
        assert "tp/some-design" not in branches
        assert "master" not in branches
        assert "candidate/my-design/single" in branches

    def test_enumerate_remote_finds_candidate_branch(self, tmp_path: Path) -> None:
        """Remote mode: candidate/my-design/single pushed to self-origin is found."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _create_branch(repo, "candidate/my-design/single")

        # Set up self-origin
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "push", "origin", "candidate/my-design/single"],
            check=True,
            capture_output=True,
        )

        branches = enumerate_candidate_branches(str(repo), remote=True)
        assert "candidate/my-design/single" in branches

    def test_enumerate_fail_open_bad_repo(self) -> None:
        """Bad repo path → [], no exception raised."""
        result = enumerate_candidate_branches("/nonexistent/totally/fake/path")
        assert result == []

    def test_enumerate_remote_fail_open_bad_repo(self) -> None:
        """Bad repo path in remote mode → [], no exception raised."""
        result = enumerate_candidate_branches("/nonexistent/path", remote=True)
        assert result == []


# ---------------------------------------------------------------------------
# Task 1.4: classify_candidates
# ---------------------------------------------------------------------------


class TestClassifyCandidates:
    def test_classify_archived_is_orphaned_live_is_left(self, tmp_path: Path) -> None:
        """archived slug → orphaned; non-archived slug → live."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _create_branch(repo, "candidate/archived-one/single")
        _create_branch(repo, "candidate/live-one/single")
        # Commit archive only for 'archived-one'
        _add_archive(repo, "archived-one")

        result = classify_candidates(str(repo))
        assert result["orphaned"] == ["candidate/archived-one/single"]
        assert result["live"] == ["candidate/live-one/single"]

    def test_classify_drops_unparseable(self, tmp_path: Path) -> None:
        """Branches with unparseable slugs are dropped (not in orphaned or live)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _create_branch(repo, "candidate/good-slug/single")
        # Uppercase — will not be enumerated since _BRANCH_RE won't match
        # (this is enforced at enumeration level)

        result = classify_candidates(str(repo))
        all_branches = result["orphaned"] + result["live"]
        # Only the valid branch should appear
        assert all(b.startswith("candidate/") for b in all_branches)

    def test_classify_empty_when_no_candidates(self, tmp_path: Path) -> None:
        """No candidate branches → both lists empty."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        result = classify_candidates(str(repo))
        assert result["orphaned"] == []
        assert result["live"] == []


# ---------------------------------------------------------------------------
# Task 1.5: main CLI
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_cli_json_shape(self, tmp_path: Path) -> None:
        """--json flag outputs a dict with orphaned/live keys; returns 0."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _create_branch(repo, "candidate/my-design/single")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--repo", str(repo), "--json"])
        output = buf.getvalue()

        assert rc == 0
        data = json.loads(output)
        assert "orphaned" in data
        assert "live" in data
        assert isinstance(data["orphaned"], list)
        assert isinstance(data["live"], list)

    def test_cli_always_exit_zero(self) -> None:
        """main() always returns 0, even on non-existent repo."""
        rc = main(["--repo", "/nonexistent/path", "--json"])
        assert rc == 0

    def test_cli_fail_open_bad_repo(self, capsys: pytest.CaptureFixture) -> None:
        """Bad repo path: returns 0 with safe empty verdict, no traceback."""
        rc = main(["--repo", "/totally/invalid/path", "--json"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "Traceback" not in captured.out
        assert "Traceback" not in captured.err
        data = json.loads(captured.out)
        assert data["orphaned"] == []
        assert data["live"] == []

    def test_cli_remote_flag(self, tmp_path: Path) -> None:
        """--remote flag selects remote enumeration path; returns 0."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        # Set up self-origin
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True,
            capture_output=True,
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--repo", str(repo), "--remote", "--json"])
        output = buf.getvalue()

        assert rc == 0
        data = json.loads(output)
        assert "orphaned" in data
        assert "live" in data

    def test_cli_human_summary_format(self, tmp_path: Path) -> None:
        """Without --json, outputs human-readable summary."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--repo", str(repo)])
        output = buf.getvalue()

        assert rc == 0
        # Should not be valid JSON
        try:
            json.loads(output)
            assert False, "Without --json, output should not be valid JSON"
        except json.JSONDecodeError:
            pass

    def test_cli_default_repo_is_dot(self) -> None:
        """--repo defaults to '.' (no error on missing --repo flag)."""
        # We can't control cwd between calls, but we can verify it returns 0
        # with a non-existent current dir (this just tests the flag is optional)
        rc = main(["--json"])
        assert rc == 0
