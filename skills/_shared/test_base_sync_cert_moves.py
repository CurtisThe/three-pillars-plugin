"""The carry certifiers read an archive move as a move, not a drop (Behavior 8).

A base-sync link whose only dropped atom is an entry a side moved into its archive certifies on
the strict lane (mechanical bytes) and on the relaxed lane (a hand resolution); a plain deletion
refuses on both. Direct calls without sides keep today's verdict.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "tp-merge-from-main" / "scripts"))
import base_sync_cert  # noqa: E402
import living_doc_carry  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

KI = "three-pillars-docs/known_issues.md"
KR = "three-pillars-docs/known_issues_resolved.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
DROP = "zero-drop verifier detected a content drop"

LIVE_BASE = (
    "# Known Issues\n\n## Medium\n\n### M47: stale lock is never swept\nbody line\n\n"
    "### M50: other\n\n## History\n\n- **2026-09-01** — seed\n"
)
RESOLVED_BASE = "# R\n"
BRANCH_NOTE = "- **2026-10-01** — branch note\n"
MASTER_NOTE = "- **2026-10-01** — master note\n"
M47_RESOLVED_ENTRY = "### M47 (RESOLVED 2026-10-01): stale lock is never swept\nbody line\n\n"
M47_LIVE = "### M47: stale lock is never swept\nbody line\n\n"


@pytest.fixture(autouse=True)
def _clean_git_process_env(monkeypatch):
    """merge_back and the certifier shell out with the process env; scrub the repo-local vars."""
    for key in set(os.environ) - set(clean_git_env()):
        monkeypatch.delenv(key)
    for key, val in IDENTITY.items():
        monkeypatch.setenv(key, val)


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=clean_git_env(**IDENTITY))


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def _with_note(live: str, note: str) -> str:
    return live.replace("- **2026-09-01** — seed\n", note + "- **2026-09-01** — seed\n")


def setup(root, *, archive_copy: bool):
    """Base on master; `feat` adds a History note; master adds one too and drops M47 (with an
    archive copy in the resolved file when `archive_copy`). Returns (repo, h0)."""
    repo = root / "r"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "master")
    write(repo, KI, LIVE_BASE)
    write(repo, KR, RESOLVED_BASE)
    commit(repo, "base")

    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, KI, _with_note(LIVE_BASE, BRANCH_NOTE))
    commit(repo, "feat")

    git(repo, "checkout", "-q", "master")
    write(repo, KI, _with_note(LIVE_BASE, MASTER_NOTE).replace(M47_LIVE, ""))
    if archive_copy:
        write(repo, KR, RESOLVED_BASE + M47_RESOLVED_ENTRY)
    commit(repo, "master")
    git(repo, "update-ref", "refs/remotes/origin/master", "master")   # cond1 reads origin/<base>

    git(repo, "checkout", "-q", "feat")
    return repo, git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit_merge(repo) -> str:
    git(repo, "commit", "-q", "-m", "Merge master into feat")
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _hand_resolution(repo, text: str) -> str:
    """Start the merge, write `text` as the living doc's resolution, commit it as h1."""
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    write(repo, KI, text)
    git(repo, "add", "--", KI)
    return _commit_merge(repo)


def _mechanical_text(root) -> str:
    """What `merge_back` writes for the same conflict, from a scratch copy of the scenario."""
    repo, _h0 = setup(root / "scratch", archive_copy=True)
    merge_back(str(repo), "master")
    return (repo / KI).read_text(encoding="utf-8")


def _flip_notes(text: str) -> str:
    lines = text.splitlines(keepends=True)
    i, j = lines.index(BRANCH_NOTE), lines.index(MASTER_NOTE)
    lines[i], lines[j] = lines[j], lines[i]
    return "".join(lines)


def _conflicts(repo, h0, h1):
    git_seam = base_sync_cert._make_default_git(repo)
    parents, reason = base_sync_cert._cond1_merge_shape(git_seam, h0, h1, "master")
    assert not reason, reason
    _tree, conflicts, reason = base_sync_cert._cond2_recompute(git_seam, h0, parents[1])
    assert not reason, reason
    assert set(conflicts) == {KI}
    return git_seam, conflicts


def test_strict_lane_certifies_an_archive_move_on_mechanical_bytes(tmp_path):
    repo, h0 = setup(tmp_path, archive_copy=True)
    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    h1 = _commit_merge(repo)
    lc = base_sync_cert._certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert lc.ok, lc.reason
    carry = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert carry.ok, carry.reason


def test_relaxed_lane_carries_a_hand_resolution_of_an_archive_move(tmp_path):
    mechanical = _mechanical_text(tmp_path)
    flipped = _flip_notes(mechanical)
    assert flipped != mechanical and "M47" not in flipped
    repo, h0 = setup(tmp_path, archive_copy=True)
    h1 = _hand_resolution(repo, flipped)
    strict = base_sync_cert._certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert not strict.ok
    assert strict.reason == "resolved bytes do not match h1's committed blob"
    carry = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert carry.ok, carry.reason
    assert KI in carry.conflicted_paths


def test_a_plain_deletion_refuses_on_both_lanes(tmp_path):
    repo, h0 = setup(tmp_path, archive_copy=False)
    merged = _with_note(LIVE_BASE, MASTER_NOTE + BRANCH_NOTE).replace(M47_LIVE, "")
    h1 = _hand_resolution(repo, merged)
    strict = base_sync_cert._certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert not strict.ok and strict.reason == DROP, strict.reason
    carry = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert not carry.ok and carry.reason == DROP, carry.reason


def test_direct_calls_without_sides_keep_todays_verdict(tmp_path):
    repo, h0 = setup(tmp_path, archive_copy=True)
    merge_back(str(repo), "master")
    h1 = _commit_merge(repo)
    git_seam, conflicts = _conflicts(repo, h0, h1)
    assert base_sync_cert._cond5_resolve(git_seam, conflicts, h1) == DROP
    reason, carry_paths = living_doc_carry._relaxed_resolve(git_seam, conflicts, h1)
    assert reason == DROP and carry_paths is None
    stages = conflicts[KI]
    texts = [base_sync_cert._cat_blob_strict(git_seam, stages[n][1]) for n in (1, 2, 3)]
    assert living_doc_carry._mechanical_resolution(*texts) is None
