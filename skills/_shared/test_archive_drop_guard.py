"""test_archive_drop_guard.py — the drop guard decides by content, not `git diff`.

Post-converge fix F4 of archive-slimming, PR #177 round 4. `uncommitted_drops`
checks each drop's index blob against HEAD's blobs and its working-tree content
against the index — by `git diff` for a normal entry (so a CRLF blob under
`text=auto`, which `git hash-object` alone would normalise, is not refused when
clean), by content hash for an `--assume-unchanged` / `--skip-worktree` entry
that `git diff` skips. A drop already deleted from the worktree, or changed only
in mode, whose blob equals HEAD's is removed. A drop staged as new with no
committed version is refused with a remedy that can clear it (`git rm
--cached`). (Pure staged rename, staged and unstaged edits:
test_archive_allowlist_uncommitted.py.)

Run with: python3 -m pytest skills/_shared/test_archive_drop_guard.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from archive_allowlist import UncommittedDropError, apply, plan_prune
from archive_drop_guard import uncommitted_drops

LIVE = "three-pillars-docs/tp-designs/x"
DD = "three-pillars-docs/completed-tp-designs/x"
NOTES = DD + "/demos/notes.txt"


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c",
                           "user.email=f@t", *args], capture_output=True,
                          text=True, check=check, env=_env())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed design with one drop candidate, `git mv`'d (design-complete 6c)."""
    _git(tmp_path, "init", "-q", "-b", "master")
    d = tmp_path / LIVE
    (d / "demos").mkdir(parents=True)
    (d / "design.md").write_text("d\n", encoding="utf-8")
    (d / "demos" / "notes.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / DD).parent.mkdir(parents=True)
    _git(tmp_path, "mv", LIVE, DD)
    return tmp_path


def _removed(root: Path) -> bool:
    return _git(root, "ls-files", "--", DD).stdout.split() == [DD + "/design.md"]


def test_assume_unchanged_edit_is_refused(repo):
    _git(repo, "update-index", "--assume-unchanged", "--", NOTES)
    (repo / NOTES).write_text("v1\nHIDDEN WIP\n", encoding="utf-8")
    assert _git(repo, "diff", "--name-only").stdout == ""  # git diff cannot see it
    assert uncommitted_drops([NOTES], repo) == [NOTES]
    with pytest.raises(UncommittedDropError):
        apply(plan_prune(DD, repo), repo)
    assert (repo / NOTES).read_text(encoding="utf-8") == "v1\nHIDDEN WIP\n"
    assert not _removed(repo)


def test_drop_deleted_from_worktree_with_head_blob_is_removed(repo):
    (repo / NOTES).unlink()
    assert uncommitted_drops([NOTES], repo) == []
    apply(plan_prune(DD, repo), repo)
    assert _removed(repo)


def test_mode_only_change_with_head_blob_is_removed(repo):
    os.chmod(repo / NOTES, 0o744)  # owner exec bit: the only mode bit git tracks
    assert _git(repo, "diff", "--name-only").stdout.strip() == NOTES  # git diff flags it
    assert uncommitted_drops([NOTES], repo) == []
    apply(plan_prune(DD, repo), repo)
    assert _removed(repo) and not (repo / NOTES).exists()


def test_staged_edit_then_worktree_delete_is_refused(repo):
    (repo / NOTES).write_text("v1\nSTAGED WIP\n", encoding="utf-8")
    _git(repo, "add", "--", NOTES)
    (repo / NOTES).unlink()  # the index still holds content no commit has
    assert uncommitted_drops([NOTES], repo) == [NOTES]


def test_skip_worktree_edit_is_refused(repo):
    _git(repo, "update-index", "--skip-worktree", "--", NOTES)
    (repo / NOTES).write_text("v1\nHIDDEN WIP\n", encoding="utf-8")
    assert _git(repo, "diff", "--name-only").stdout == ""
    assert uncommitted_drops([NOTES], repo) == [NOTES]


@pytest.fixture
def crlf_repo(tmp_path: Path) -> Path:
    """The drop was committed with CRLF before `* text=auto` was set: `git add`
    keeps the CRLF blob (has_crlf_in_index) while `git hash-object` alone
    normalises it, so the two disagree on a clean file."""
    repo = tmp_path
    _git(repo, "init", "-q", "-b", "master")
    (repo / LIVE / "demos").mkdir(parents=True)
    (repo / LIVE / "design.md").write_text("d\n", encoding="utf-8")
    (repo / LIVE / "demos" / "notes.txt").write_bytes(b"v1\r\nv2\r\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "crlf")
    (repo / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / DD).parent.mkdir(parents=True)
    _git(repo, "mv", LIVE, DD)
    index_blob = _git(repo, "ls-files", "-s", "--", NOTES).stdout.split()[1]
    if _git(repo, "hash-object", "--", NOTES).stdout.strip() == index_blob:
        pytest.skip("this git normalises hash-object against the index")
    return repo


def test_clean_crlf_drop_under_text_auto_is_removed(crlf_repo):
    assert _git(crlf_repo, "diff", "--name-only").stdout == ""
    assert uncommitted_drops([NOTES], crlf_repo) == []
    apply(plan_prune(DD, crlf_repo), crlf_repo)
    assert _removed(crlf_repo)


def test_edited_crlf_drop_under_text_auto_is_refused(crlf_repo):
    (crlf_repo / NOTES).write_bytes(b"v1\r\nv2\r\nWIP\r\n")
    assert uncommitted_drops([NOTES], crlf_repo) == [NOTES]
    with pytest.raises(UncommittedDropError):
        apply(plan_prune(DD, crlf_repo), crlf_repo)
    assert not _removed(crlf_repo)


def test_never_committed_drop_gets_a_remedy_that_clears_it(repo):
    new = DD + "/demos/new.txt"
    (repo / new).write_text("staged, never committed\n", encoding="utf-8")
    _git(repo, "add", "--", new)
    plan = plan_prune(DD, repo)
    assert plan.drop == [new, NOTES]
    with pytest.raises(UncommittedDropError) as exc:
        apply(plan, repo)
    assert exc.value.paths == [new] and exc.value.never_committed == [new]
    assert "git rm --cached" in str(exc.value)
    assert not _git(repo, "cat-file", "-e", "HEAD:" + new, check=False).returncode == 0

    _git(repo, "rm", "-q", "--cached", "--", new)  # the remedy, for that path only
    plan = plan_prune(DD, repo)
    assert plan.drop == [NOTES] and new in plan.keep  # untracked: kept, not dropped
    apply(plan, repo)
    assert _removed(repo) and (repo / new).read_text(encoding="utf-8").startswith("staged")
