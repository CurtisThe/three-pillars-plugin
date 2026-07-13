"""Tests for verify_merged.py — dual-source merge verifier.

Tests cover:
  Task 2.1: archive-primary signal (git show origin/{base}:...)
  Task 2.2: gh pr view corroboration (fail-open)
  Task 2.3: verdict combination + JSON output
  Task 2.4: main(argv) CLI — flags + always-exit-0 + fail-open

Run with: pytest skills/tp-post-merge/scripts/test_verify_merged.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

from verify_merged import check_archive_on_base, check_gh_merged, compute_verdict, main


# ---------------------------------------------------------------------------
# Git fixture helpers
# ---------------------------------------------------------------------------

def _init_git_repo(path: Path) -> None:
    """Initialize a non-bare git repo with one commit."""
    subprocess.run(["git", "init", "-b", "master", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True)
    # Initial commit
    readme = path / "README.md"
    readme.write_text("init")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True)


def _add_archive_to_base(repo_path: Path, design_name: str) -> None:
    """Commit the design archive on the repo's CURRENT branch (HEAD), simulating
    the completion commit. The caller controls which branch is checked out (the
    base for an on-base archive; the design branch for the on-design-branch-only
    negative case) — this helper does not switch branches."""
    archive_dir = repo_path / "three-pillars-docs" / "completed-tp-designs" / design_name
    archive_dir.mkdir(parents=True, exist_ok=True)
    design_md = archive_dir / "design.md"
    design_md.write_text(f"# {design_name} design")
    subprocess.run(["git", "-C", str(repo_path), "add", str(design_md)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", f"Complete design: {design_name}"],
        check=True, capture_output=True
    )


def _make_stub_gh(tmp_dir: Path, state: str = "MERGED", fail: bool = False) -> Path:
    """Create a stub gh executable that returns a given PR state."""
    stub_path = tmp_dir / "gh"
    if fail:
        stub_path.write_text("#!/bin/sh\nexit 1\n")
    else:
        stub_path.write_text(
            f'#!/bin/sh\necho \'{{"state": "{state}", "baseRefName": "master"}}\'\n'
        )
    stub_path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return stub_path


# ---------------------------------------------------------------------------
# Task 2.1: archive-primary signal
# ---------------------------------------------------------------------------

class TestArchivePrimarySignal:
    def test_archive_present_on_base_is_merged(self, tmp_path: Path) -> None:
        """Archive present on origin/{base} ⇒ merged=True via=archive."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _add_archive_to_base(repo, "my-design")  # commits on master (current HEAD)

        # Set up origin pointing to itself
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin"],
            check=True, capture_output=True
        )

        result = check_archive_on_base(str(repo), "my-design", "master")
        assert result is True

    def test_archive_absent_not_merged(self, tmp_path: Path) -> None:
        """Archive absent on origin/{base} ⇒ False."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin"],
            check=True, capture_output=True
        )

        result = check_archive_on_base(str(repo), "my-design", "master")
        assert result is False

    def test_archive_on_design_branch_only_is_not_merged(self, tmp_path: Path) -> None:
        """Merge gate: archive present on the design branch (and HEAD) but NOT
        on base ⇒ False.

        Before the PR merges, the completion commit (which writes the archive)
        lives only on tp/{name}. The verifier must NOT treat HEAD / the design
        branch as proof of merge, or teardown would run on an unmerged PR.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Cut the design branch and commit the archive there only — base
        # (master) never receives it.
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "tp/my-design"],
            check=True, capture_output=True
        )
        _add_archive_to_base(repo, "my-design")  # commits on tp/my-design (current HEAD)

        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin"],
            check=True, capture_output=True
        )

        # HEAD is tp/my-design and DOES carry the archive — but master does not.
        result = check_archive_on_base(str(repo), "my-design", "master")
        assert result is False, (
            "archive on the design branch HEAD must NOT count as merged — "
            "that would break the inviolable merge gate"
        )


# ---------------------------------------------------------------------------
# Task 2.2: gh corroboration (fail-open)
# ---------------------------------------------------------------------------

class TestGhCorroboration:
    def test_gh_merged_corroborates(self, tmp_path: Path) -> None:
        """gh returning state=MERGED ⇒ corroboration=True."""
        stub = _make_stub_gh(tmp_path, state="MERGED")
        result = check_gh_merged("my-design", gh_cmd=str(stub))
        assert result is True

    def test_gh_open_not_corroborated(self, tmp_path: Path) -> None:
        """gh returning state=OPEN ⇒ corroboration=False."""
        stub = _make_stub_gh(tmp_path, state="OPEN")
        result = check_gh_merged("my-design", gh_cmd=str(stub))
        assert result is False

    def test_gh_missing_skipped_no_error(self) -> None:
        """gh not on PATH ⇒ corroboration=False, no exception."""
        # Use a non-existent path
        result = check_gh_merged("my-design", gh_cmd="/nonexistent/gh")
        assert result is False

    def test_gh_failure_skipped_no_error(self, tmp_path: Path) -> None:
        """gh exits non-zero ⇒ corroboration=False, no exception."""
        stub = _make_stub_gh(tmp_path, fail=True)
        result = check_gh_merged("my-design", gh_cmd=str(stub))
        assert result is False


# ---------------------------------------------------------------------------
# Task 2.3: verdict combination + JSON output
# ---------------------------------------------------------------------------

class TestVerdictCombination:
    def test_via_both_when_both_positive(self) -> None:
        verdict = compute_verdict(archive=True, gh=True, base="master")
        assert verdict["merged"] is True
        assert verdict["via"] == "both"

    def test_via_archive_when_only_archive(self) -> None:
        verdict = compute_verdict(archive=True, gh=False, base="master")
        assert verdict["merged"] is True
        assert verdict["via"] == "archive"

    def test_via_pr_when_only_gh(self) -> None:
        verdict = compute_verdict(archive=False, gh=True, base="master")
        assert verdict["merged"] is True
        assert verdict["via"] == "pr"

    def test_via_none_when_both_negative(self) -> None:
        verdict = compute_verdict(archive=False, gh=False, base="master")
        assert verdict["merged"] is False
        assert verdict["via"] == "none"

    def test_json_shape(self) -> None:
        verdict = compute_verdict(archive=True, gh=False, base="master")
        assert "merged" in verdict
        assert "via" in verdict
        assert "base" in verdict
        assert verdict["base"] == "master"
        assert isinstance(verdict["merged"], bool)
        assert verdict["via"] in ("archive", "pr", "both", "none")


# ---------------------------------------------------------------------------
# Task 2.4: main(argv) CLI — flags + always-exit-0 + fail-open
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_flags(self, tmp_path: Path) -> None:
        """main() with valid args returns 0 and prints JSON."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _add_archive_to_base(repo, "my-design")

        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin"],
            check=True, capture_output=True
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--repo", str(repo), "--design", "my-design", "--base", "master", "--json"])
        output = buf.getvalue()

        assert rc == 0
        data = json.loads(output)
        assert "merged" in data
        assert data["merged"] is True

    def test_cli_without_json_flag_prints_non_json(self, tmp_path: Path) -> None:
        """Without --json, main() prints a human-readable line, not JSON.

        Guards that the --json flag actually controls output format (it was
        once a no-op that always printed JSON).
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        _add_archive_to_base(repo, "my-design")

        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin"],
            check=True, capture_output=True
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--repo", str(repo), "--design", "my-design", "--base", "master"])
        output = buf.getvalue().strip()

        assert rc == 0
        # Not JSON, and carries the verdict in key=value form.
        with pytest.raises(json.JSONDecodeError):
            json.loads(output)
        assert "merged=True" in output

    def test_always_exit_zero(self, tmp_path: Path) -> None:
        """main() always returns 0 even on bad input."""
        # non-existent repo
        rc = main(["--repo", "/nonexistent/path", "--design", "foo", "--base", "master", "--json"])
        assert rc == 0

    def test_fail_open_offline_no_traceback(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Offline / bad args: returns 0 with no traceback, just valid JSON."""
        rc = main([
            "--repo", str(tmp_path),
            "--design", "nonexistent-design",
            "--base", "master",
            "--json",
            "--gh-cmd", "/nonexistent/gh",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        assert "Traceback" not in captured.out
        assert "Traceback" not in captured.err
        # Should still produce valid JSON
        data = json.loads(captured.out)
        assert data["merged"] is False

    def test_argparse_misuse_still_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        """CLI misuse (missing required --design) must not let argparse's
        SystemExit escape the always-exit-0 fail-open contract: returns 0 with
        a safe merged=false verdict (refuse-teardown-on-doubt)."""
        rc = main(["--base", "master", "--json"])  # no --design → argparse error
        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["merged"] is False
        assert data["via"] == "none"

    def test_invalid_design_slug_is_rejected_fail_safe(self, capsys: pytest.CaptureFixture) -> None:
        """A `--design` outside [a-z0-9-]+ (path traversal / injection) is
        rejected at the boundary: merged=false, exit 0, value never interpolated."""
        for bad in ["../etc/passwd", "foo/bar", "foo bar", "Foo", "a;b"]:
            rc = main(["--design", bad, "--base", "master", "--json"])
            captured = capsys.readouterr()
            assert rc == 0, f"{bad!r} should still exit 0"
            data = json.loads(captured.out)
            assert data["merged"] is False, f"{bad!r} must report merged=false"
            assert data["via"] == "none"

    def test_argparse_misuse_without_json_is_human_readable(self, capsys: pytest.CaptureFixture) -> None:
        """The fail-open fallback honors the output contract: no --json ⇒
        human-readable line, not JSON (regression guard for _print_fallback)."""
        rc = main(["--base", "master"])  # no --design, no --json
        captured = capsys.readouterr()
        assert rc == 0
        out = captured.out.strip()
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)
        assert "merged=False" in out
        assert "via=none" in out

    def test_gh_corroboration_honors_repo(self, tmp_path: Path) -> None:
        """check_gh_merged runs gh with cwd=repo so corroboration consults the
        intended repo, not the caller's current working directory."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        # Stub gh writes its cwd to a sentinel file so we can assert it ran in `repo`.
        stub = tmp_path / "gh"
        sentinel = tmp_path / "gh_cwd.txt"
        stub.write_text(
            "#!/bin/sh\n"
            f"pwd > '{sentinel}'\n"
            'echo \'{"state": "MERGED", "baseRefName": "master"}\'\n'
        )
        stub.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        result = check_gh_merged("my-design", gh_cmd=str(stub), repo=str(repo))
        assert result is True
        assert sentinel.read_text(encoding="utf-8").strip() == str(repo.resolve())
