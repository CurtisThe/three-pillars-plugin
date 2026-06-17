"""test_ci_local_stamp_cli.py — ci_local_stamp.py --write CLI tests.

Covers:
  TestWriteCli — --write invocation: success/failure exit codes, --expect-head
                 drift guard, --start-dirty flag, unwritable-file handling (Task 3.2)

See also:
  test_ci_local_stamp.py       — write_stamp/read_stamp/StampError unit tests
  test_ci_local_stamp_pred.py  — pred_ci_local_stamp predicate matrix
  test_ci_local_sh_wiring.py   — ci-local.sh shell-wiring tests + ordering anchors
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ---------------------------------------------------------------------------
# Helpers: build minimal git repos
# ---------------------------------------------------------------------------

def _git(args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo_root: Path) -> None:
    _git(["init", "-q", str(repo_root)], ".")
    _git(["config", "user.email", "t@t.test"], repo_root)
    _git(["config", "user.name", "test"], repo_root)


def _make_commit(repo_root: Path, msg: str = "commit") -> str:
    """Create a commit in the repo; return the HEAD sha."""
    (repo_root / "x.txt").write_text(msg)
    _git(["add", "-A"], repo_root)
    _git(["commit", "-qm", msg], repo_root)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Task 3.2: TestWriteCli
# ---------------------------------------------------------------------------

class TestWriteCli:
    """CLI --write path writes a stamp and exits 0; missing repo exits non-zero."""

    def test_cli_write_exits_zero_on_success(self, tmp_path):
        """python3 ci_local_stamp.py --write in a valid repo exits 0."""
        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        result = subprocess.run(
            [sys.executable, str(stamp_script), "--write"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
        )

    def test_cli_write_creates_stamp_file(self, tmp_path):
        """--write actually creates the stamp file."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        subprocess.run(
            [sys.executable, str(stamp_script), "--write"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
        )

        data = ci_local_stamp.read_stamp(repo_root)
        assert data is not None
        assert data["head_sha"] == head_sha

    @pytest.mark.skipif(os.geteuid() == 0, reason="chmod read-only is ineffective for root")
    def test_cli_write_fails_nonzero_when_stamp_unwritable(self, tmp_path):
        """--write exits non-zero when the stamp cannot be written (e.g. unwritable file).

        Pins the set -e propagation guarantee in ci-local.sh: if write_stamp fails,
        the --write CLI exits non-zero so ci-local.sh aborts and no green stamp is
        left behind on a failed run.
        """
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Write a valid stamp first to establish the stamp file, then make it
        # unreadable/unwritable so write_stamp raises an OSError.
        stamp_path = ci_local_stamp.write_stamp(repo_root)
        stamp_dir = stamp_path.parent

        # Make both the file and directory unwritable (read-only).
        stamp_path.chmod(0o444)   # file: no write
        stamp_dir.chmod(0o555)    # dir: no write (blocks create/delete)
        try:
            stamp_script = _SHARED_DIR / "ci_local_stamp.py"
            result = subprocess.run(
                [sys.executable, str(stamp_script), "--write"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0, (
                "Expected non-zero exit when stamp file/dir is unwritable, "
                f"got returncode={result.returncode}. "
                "ci-local.sh relies on this to abort on write failure."
            )
        finally:
            # Restore permissions so tmp_path cleanup can delete the directory
            stamp_dir.chmod(0o755)
            stamp_path.chmod(0o644)

    def test_cli_no_args_prints_usage(self, tmp_path):
        """No args -> prints usage info (non-zero exit)."""
        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        result = subprocess.run(
            [sys.executable, str(stamp_script)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    # --- Finding 2: --expect-head drift guard ---

    def test_cli_write_expect_head_matching_exits_zero(self, tmp_path):
        """--write --expect-head <sha> exits 0 when HEAD has not drifted."""
        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        result = subprocess.run(
            [sys.executable, str(stamp_script), "--write", "--expect-head", head_sha],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 when expect-head matches. stderr: {result.stderr}"
        )

    def test_cli_write_expect_head_drift_exits_nonzero(self, tmp_path):
        """--write --expect-head <old-sha> exits non-zero when HEAD has drifted.

        Simulates a commit landing mid-run: the stamp writer is given the SHA
        captured at run-start but HEAD has since moved to a new commit.
        The stamp must NOT be written (set -e in ci-local.sh aborts the run).
        """
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        old_sha = _make_commit(repo_root)

        # Simulate a mid-run commit that advances HEAD
        new_sha = _make_commit(repo_root, msg="mid-run commit")
        assert new_sha != old_sha, "test setup error: SHAs should differ"

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        result = subprocess.run(
            [sys.executable, str(stamp_script), "--write", "--expect-head", old_sha],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when HEAD drifted (mid-run commit detected). "
            f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
        )
        # No stamp must have been written (guard failed before write)
        stamp = ci_local_stamp.read_stamp(repo_root)
        assert stamp is None, (
            f"Stamp must NOT be written after drift detection, got: {stamp!r}"
        )

    def test_write_stamp_expect_head_matching_succeeds(self, tmp_path):
        """write_stamp(expect_head=sha) succeeds when HEAD matches."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        # Should not raise
        stamp_path = ci_local_stamp.write_stamp(repo_root, expect_head=head_sha)
        data = ci_local_stamp.read_stamp(repo_root)
        assert data is not None
        assert data["head_sha"] == head_sha

    def test_write_stamp_expect_head_drift_raises_stamp_error(self, tmp_path):
        """write_stamp(expect_head=old_sha) raises StampError when HEAD has drifted."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        old_sha = _make_commit(repo_root)
        _make_commit(repo_root, msg="mid-run commit")  # advance HEAD

        with pytest.raises(ci_local_stamp.StampError, match="drifted"):
            ci_local_stamp.write_stamp(repo_root, expect_head=old_sha)

    def test_cli_write_start_dirty_0_clean_repo_exits_zero(self, tmp_path):
        """--write --start-dirty 0 exits 0 on a clean repo (started clean, still clean)."""
        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        result = subprocess.run(
            [sys.executable, str(stamp_script), "--write", "--start-dirty", "0"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for --start-dirty 0 on clean repo. stderr: {result.stderr}"
        )

    def test_cli_write_start_dirty_1_exits_nonzero(self, tmp_path):
        """--write --start-dirty 1 exits non-zero (run started dirty; stamp refused).

        Also asserts no stamp was written (STRUCTURAL 2): moving the dirty guard after
        stamp_file.write_text would produce a false-green stamp that this check catches.
        """
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        stamp_script = _SHARED_DIR / "ci_local_stamp.py"
        result = subprocess.run(
            [sys.executable, str(stamp_script), "--write", "--start-dirty", "1"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            "Expected non-zero exit for --start-dirty 1 (started dirty). "
            f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
        )
        # No stamp must have been written (guard fires before write)
        stamp = ci_local_stamp.read_stamp(repo_root)
        assert stamp is None, (
            f"Stamp must NOT be written when --start-dirty 1 is passed, got: {stamp!r}"
        )
