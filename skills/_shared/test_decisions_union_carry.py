"""The certifiers reproduce the union (basesync-three-way-verifier Task 5.4).

Spec: detailed-design.md Interfaces (`resolve_conflict_bytes(..., path=)`) and the call-site list.
The driver resolves a design-dir `decisions.md` conflict through `union_decisions` because it passes
the path to the shared byte path; the verifier side must pass the same path, or it re-runs the byte
path without the lane, gets a deferral, and refuses a link the driver legitimately resolved. This
file drives a real two-tail `decisions.md` conflict through a temp git link committed with the union
bytes and asserts the strict conjunct (`_cond5_resolve`) and the relaxed certifier
(`certify_link_carry`) both reproduce it, and that `_mechanical_resolution` / `_relaxed_resolve`
thread `path`. Strict condition 3 (`_cond3_allowlist`, known issue M20) is a separate gate and is not
exercised here. Asserts the contract, not incidental bytes (skills/_shared/test-fragility.md).
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
from decisions_union import union_decisions  # noqa: E402
from task_scope import _git_env  # noqa: E402  # shipped scrub; git_env is dev-only

LANE = "three-pillars-docs/tp-designs/x/decisions.md"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
BASE = "# Decisions\n\n### [tp-plan] first\n**Decided**: yes\n"
TAIL_O = (
    "### [tp-plan-audit] round 1 results\n"
    "| finding | verdict |\n|---|---|\n| F1 | bind |\n"
    "```python\nx = 1\n```\n"
    "- flag: --auto\n- flag: --spike\n"
    "<!-- keep: a note -->\n"
    "**Decided**: bind F1\n"
)
TAIL_T = (
    "### [tp-implement] worker flags\n"
    "- flag: --local\n"
    "```\nsh -c true\n```\n"
    "<!-- closed -->\n"
)
OURS, THEIRS = BASE + "\n" + TAIL_O, BASE + "\n" + TAIL_T
UNION = BASE + "\n" + TAIL_O + "\n" + TAIL_T
HAND = UNION + "\n### [tp-note] a hand-added entry\n**Decided**: keep both tails\n"
NOT_REPRODUCED = "resolved bytes do not match h1's committed blob"


@pytest.fixture(autouse=True)
def _clean_git_process_env(monkeypatch):
    """The certifier shells out with the process env; scrub the repo-local git variables."""
    for key in set(os.environ) - set(_git_env()):
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=_git_env(**IDENT))


def _commit(repo, text, msg):
    p = repo / LANE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", "--", LANE)
    _git(repo, "commit", "-q", "-m", msg)


def _link(root, committed: str):
    """A base-sync link whose only conflict is the two-tail `decisions.md`: `feat` appends one
    tail, `master` another. `committed` is what the merge commit h1 holds for the path.
    Returns (repo, h0, h1)."""
    repo = root / "r"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "master")
    _commit(repo, BASE, "base")
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, OURS, "feat")
    _git(repo, "checkout", "-q", "master")
    _commit(repo, THEIRS, "master")
    _git(repo, "update-ref", "refs/remotes/origin/master", "master")   # cond1 reads origin/<base>
    _git(repo, "checkout", "-q", "feat")
    h0 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    (repo / LANE).write_text(committed, encoding="utf-8")
    _git(repo, "add", "--", LANE)
    _git(repo, "commit", "-q", "-m", "Merge master into feat")
    return repo, h0, _git(repo, "rev-parse", "HEAD").stdout.strip()


def _conflicts(repo, h0, h1):
    git_seam = base_sync_cert._make_default_git(repo)
    parents, reason = base_sync_cert._cond1_merge_shape(git_seam, h0, h1, "master")
    assert not reason, reason
    _tree, conflicts, reason = base_sync_cert._cond2_recompute(git_seam, h0, parents[1])
    assert not reason, reason
    assert set(conflicts) == {LANE}      # non-vacuous: the decisions file IS the whole conflict set
    return git_seam, conflicts


def test_the_fixture_is_a_real_two_tail_conflict_with_a_union_to_reproduce():
    assert union_decisions(BASE, OURS, THEIRS) == UNION
    status, merged = base_sync_cert.resolve_conflict_bytes(base=BASE, ours=OURS, theirs=THEIRS)
    assert status != base_sync_cert.RESOLVED     # without the path, diff3 alone defers this shape
    assert merged != UNION


def test_strict_cond5_reproduces_a_union_resolved_decisions_conflict(tmp_path):
    repo, h0, h1 = _link(tmp_path, UNION)
    git_seam, conflicts = _conflicts(repo, h0, h1)
    assert base_sync_cert._cond5_resolve(git_seam, conflicts, h1, repo) == ""


def test_strict_cond5_still_refuses_bytes_that_are_not_the_union(tmp_path):
    repo, h0, h1 = _link(tmp_path, HAND)
    git_seam, conflicts = _conflicts(repo, h0, h1)
    assert base_sync_cert._cond5_resolve(git_seam, conflicts, h1, repo) == NOT_REPRODUCED


def test_relaxed_certifier_takes_the_union_as_the_mechanical_merge(tmp_path):
    repo, h0, h1 = _link(tmp_path, UNION)
    lc = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert lc.ok, lc.reason
    # Byte-exact to the zero-drop-verified mechanical merge: no hand-resolution carry (K=0).
    assert lc.conflicted_paths == ()


def test_relaxed_certifier_still_carries_a_hand_edited_decisions_file(tmp_path):
    repo, h0, h1 = _link(tmp_path, HAND)
    lc = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert lc.ok, lc.reason
    assert lc.conflicted_paths == (LANE,)      # not the union, so it rides the hand-res lane


def test_mechanical_resolution_opens_the_lane_only_with_the_path():
    assert living_doc_carry._mechanical_resolution(BASE, OURS, THEIRS, path=LANE) == UNION
    today = living_doc_carry._mechanical_resolution(BASE, OURS, THEIRS)
    assert today is None                       # diff3 alone defers this shape
    assert living_doc_carry._mechanical_resolution(BASE, OURS, THEIRS, path=None) == today


def test_relaxed_resolve_passes_its_loop_path_to_the_mechanical_resolution(tmp_path, monkeypatch):
    repo, h0, h1 = _link(tmp_path, UNION)
    git_seam, conflicts = _conflicts(repo, h0, h1)
    seen = []

    def spy(base, ours, theirs, *, archives=None, path=None):
        seen.append(path)
        return None

    monkeypatch.setattr(living_doc_carry, "_mechanical_resolution", spy)
    reason, _carry = living_doc_carry._relaxed_resolve(git_seam, conflicts, h1)
    assert reason == ""
    assert seen == [LANE]
