"""test_ci_local_stamp.py — write_stamp / read_stamp / StampError unit tests.

Covers:
  TestWriteReadStamp  — write_stamp/read_stamp/StampError core behaviour (Task 3.1)

See also:
  test_ci_local_stamp_pred.py  — pred_ci_local_stamp matrix + evaluate_gate seam
  test_ci_local_stamp_cli.py   — --write CLI tests (expect-head, start-dirty, exit codes)
  test_ci_local_sh_wiring.py   — ci-local.sh shell-wiring tests + ordering anchors
"""
from __future__ import annotations

import json
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
# Task 3.1: TestWriteReadStamp
# ---------------------------------------------------------------------------

class TestWriteReadStamp:
    """write_stamp / read_stamp / StampError behave correctly."""

    def test_write_stamp_creates_file_under_gitdir(self, tmp_path):
        """write_stamp returns a path under the git dir, not in the working tree."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        stamp_path = ci_local_stamp.write_stamp(repo_root)

        # Must be under the git dir
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_dir_abs = (repo_root / git_dir).resolve()
        assert stamp_path.resolve().is_relative_to(git_dir_abs), (
            f"stamp at {stamp_path} is not under git dir {git_dir_abs}"
        )

    def test_write_stamp_not_in_git_status(self, tmp_path):
        """The stamp file does not appear in git status output."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        ci_local_stamp.write_stamp(repo_root)

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert status == "", f"Unexpected git status output: {status!r}"

    def test_write_stamp_schema_and_fields(self, tmp_path):
        """Stamp has schema=1, head_sha, created_at, dirty fields."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        stamp_path = ci_local_stamp.write_stamp(repo_root)
        data = json.loads(stamp_path.read_text(encoding="utf-8"))

        assert data["schema"] == 1
        assert data["head_sha"] == head_sha
        assert "created_at" in data
        assert "dirty" in data

    def test_write_stamp_dirty_false_in_clean_repo(self, tmp_path):
        """dirty=False in a clean repo."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        stamp_path = ci_local_stamp.write_stamp(repo_root)
        data = json.loads(stamp_path.read_text(encoding="utf-8"))
        assert data["dirty"] is False

    def test_write_stamp_dirty_true_with_uncommitted_edit(self, tmp_path):
        """dirty=True when there is an uncommitted edit."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Make an uncommitted edit
        (repo_root / "x.txt").write_text("dirty!")

        stamp_path = ci_local_stamp.write_stamp(repo_root)
        data = json.loads(stamp_path.read_text(encoding="utf-8"))
        assert data["dirty"] is True

    def test_write_stamp_linked_worktree(self, tmp_path):
        """In a linked worktree, stamp resolves to the per-checkout worktrees dir."""
        import ci_local_stamp

        repo_root = tmp_path / "main_repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        linked = tmp_path / "linked_wt"
        _git(["worktree", "add", "-b", "wt-branch", str(linked)], repo_root)

        stamp_path = ci_local_stamp.write_stamp(linked)

        # The stamp should land under the linked worktree's gitdir
        wt_git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=linked,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        wt_git_dir_abs = (linked / wt_git_dir).resolve()
        assert stamp_path.resolve().is_relative_to(wt_git_dir_abs), (
            f"stamp at {stamp_path} is not under linked worktree git dir {wt_git_dir_abs}"
        )
        # Must NOT be relative to the main gitdir
        main_git_dir = (repo_root / ".git").resolve()
        # The per-worktree gitdir is inside the main gitdir, so verify it's specifically
        # under .git/worktrees/
        assert "worktrees" in str(stamp_path.resolve()), (
            f"linked worktree stamp should be under .git/worktrees/, got {stamp_path}"
        )

    def test_read_stamp_returns_dict(self, tmp_path):
        """read_stamp returns the dict written by write_stamp."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        ci_local_stamp.write_stamp(repo_root)
        data = ci_local_stamp.read_stamp(repo_root)

        assert data is not None
        assert data["head_sha"] == head_sha
        assert data["schema"] == 1

    def test_read_stamp_absent_returns_none(self, tmp_path):
        """read_stamp returns None when no stamp exists."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        result = ci_local_stamp.read_stamp(repo_root)
        assert result is None

    def test_read_stamp_broken_raises_stamp_error(self, tmp_path):
        """read_stamp raises StampError on unparseable JSON."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Write a valid stamp first, then corrupt it
        stamp_path = ci_local_stamp.write_stamp(repo_root)
        stamp_path.write_text("not valid json {{{")

        with pytest.raises(ci_local_stamp.StampError):
            ci_local_stamp.read_stamp(repo_root)

    # --- Finding 1: _is_dirty fail-closed ---

    def test_is_dirty_git_failure_raises(self, tmp_path, monkeypatch):
        """_is_dirty failing git status raises (fail-closed: check=True posture).

        Simulates git status failing (e.g. corrupt repo, git not on PATH).
        write_stamp must raise rather than silently recording dirty=False on a
        tree whose cleanliness was never proven.

        The fake honors the check= kwarg so the test discriminates the fix:
          - check=True  → raises CalledProcessError (the production path that
                           must propagate; this is what we assert)
          - check=False → returns a CompletedProcess with returncode=128

        Without this distinction the test passes even if check=True is reverted
        to check=False, masking regressions.
        """
        import subprocess
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Monkeypatch subprocess.run so the git status --porcelain call honours
        # the check= kwarg: raise only when check is truthy (matching real posture).
        original_run = subprocess.run

        def failing_run(args, **kwargs):
            if isinstance(args, list) and "status" in args and "--porcelain" in args:
                if kwargs.get("check"):
                    raise subprocess.CalledProcessError(128, args, "", "fatal: not a git repo")
                # check=False path: return a failed-but-unchecked CompletedProcess
                return subprocess.CompletedProcess(args, returncode=128, stdout="", stderr="")
            return original_run(args, **kwargs)

        monkeypatch.setattr(subprocess, "run", failing_run)

        with pytest.raises((subprocess.CalledProcessError, ci_local_stamp.StampError)):
            ci_local_stamp.write_stamp(repo_root)

    # --- Structural 1: dirty-state drift guard ---

    def test_write_stamp_started_dirty_raises(self, tmp_path):
        """write_stamp(expect_start_dirty=True) raises StampError (run started dirty).

        Uses a genuinely DIRTY repo so the started-dirty branch is independently
        pinned: deleting the 'if expect_start_dirty: raise' branch in write_stamp
        would allow this test to proceed to the disagreement branch, which also
        raises — but on a genuinely dirty tree expect_start_dirty=True means the
        write-time dirty check AGREES (both dirty), so the disagreement branch would
        NOT fire.  The state-setup discrimination (agree vs disagree) is the real
        pin; the match anchors on the started-dirty wording to confirm the correct
        branch fired (the disagreement message says "dirty state changed", not
        "started with uncommitted").
        Also asserts no stamp was written (STRUCTURAL 2).
        """
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Make the repo genuinely dirty so the tree state mirrors expect_start_dirty=True.
        # This means the disagreement branch (dirty != expect_start_dirty) does NOT fire;
        # only the explicit started-dirty refusal fires.
        (repo_root / "x.txt").write_text("dirty!")

        with pytest.raises(
            ci_local_stamp.StampError,
            match=r"(?i)started with uncommitted",
        ):
            ci_local_stamp.write_stamp(repo_root, expect_start_dirty=True)

        # No stamp must have been written (STRUCTURAL 2: guard fires before write)
        assert ci_local_stamp.read_stamp(repo_root) is None, (
            "write_stamp must NOT write a stamp when expect_start_dirty=True"
        )

    def test_write_stamp_clean_to_clean_succeeds(self, tmp_path):
        """write_stamp(expect_start_dirty=False) succeeds on a clean repo."""
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        stamp_path = ci_local_stamp.write_stamp(repo_root, expect_start_dirty=False)
        data = json.loads(stamp_path.read_text(encoding="utf-8"))
        assert data["dirty"] is False
        assert data["head_sha"] == head_sha

    def test_write_stamp_state_disagreement_raises(self, tmp_path, monkeypatch):
        """write_stamp raises when dirty state disagrees between run start and write time.

        Simulates a stash/revert mid-run: expect_start_dirty=False (started clean)
        but the monkeypatched _is_dirty returns True at write time.
        """
        import ci_local_stamp

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Simulate dirty=True at write time despite starting clean
        monkeypatch.setattr(ci_local_stamp, "_is_dirty", lambda root: True)

        with pytest.raises(ci_local_stamp.StampError, match="dirty state changed"):
            ci_local_stamp.write_stamp(repo_root, expect_start_dirty=False)

        # No stamp must have been written (STRUCTURAL 2: guard fires before write)
        assert ci_local_stamp.read_stamp(repo_root) is None, (
            "write_stamp must NOT write a stamp when dirty state disagreement detected"
        )

    # --- Finding 3: read_stamp validates JSON content is a dict ---

    @pytest.mark.parametrize("content,label", [
        ("null", "null"),
        ("[]", "array"),
        ('"x"', "string"),
        ("42", "integer"),
    ])
    def test_read_stamp_non_dict_json_raises_stamp_error(self, tmp_path, content, label):
        """read_stamp raises StampError when stamp JSON is valid but not a dict.

        Covers: literal null (parses to None), array, string, integer.
        pred_ci_local_stamp must return INDETERMINATE for these, not AttributeError.
        """
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        _make_commit(repo_root)

        # Establish the stamp file path, then overwrite with non-dict JSON
        stamp_path = ci_local_stamp.write_stamp(repo_root)
        stamp_path.write_text(content)

        with pytest.raises(ci_local_stamp.StampError, match="JSON object"):
            ci_local_stamp.read_stamp(repo_root)

    @pytest.mark.parametrize("content", ["null", "[]", '"x"'])
    def test_pred_ci_local_stamp_corrupt_content_returns_indeterminate(
        self, tmp_path, monkeypatch, content
    ):
        """pred_ci_local_stamp returns INDETERMINATE when stamp JSON is non-dict.

        Confirms the StampError from read_stamp is caught and mapped to INDETERMINATE,
        not leaked as an AttributeError or escaped as PASS.
        """
        import ci_local_stamp
        from deterministic_gate import GateVerdict

        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        head_sha = _make_commit(repo_root)

        # Establish the stamp file path, then overwrite with non-dict JSON
        stamp_path = ci_local_stamp.write_stamp(repo_root)
        stamp_path.write_text(content)

        # Use live read path (no stamp= kwarg) so read_stamp is exercised
        result = ci_local_stamp.pred_ci_local_stamp(head_sha, repo_root=str(repo_root))
        assert result.verdict == GateVerdict.INDETERMINATE, (
            f"Expected INDETERMINATE for corrupt stamp content {content!r}, "
            f"got {result.verdict} (detail: {result.detail!r})"
        )
        # Detail should mention corrupt/stamp/error
        detail_lower = result.detail.lower()
        assert any(kw in detail_lower for kw in ("corrupt", "stamp", "error", "read")), (
            f"INDETERMINATE detail should hint at stamp read error, got: {result.detail!r}"
        )
