"""The carry certifiers pass the merge base to the verifier: a one-side retitle certifies.

Spec: basesync-three-way-verifier detailed-design.md, Test Strategy (Certifiers). The strict lane
(`base_sync_cert._cond5_resolve`) and both `living_doc_carry` lanes reach `verify_with_moves`,
which now hands the base to `verify`. Master (`theirs`) retitling an entry in place while the
branch leaves it alone is not a drop, so a link that merges master in certifies on mechanical
bytes and on a hand resolution. The real #196a shape is rebuilt in a throwaway repo: the retitle
lands in a region git merges cleanly, and both sides append a different keyed entry at one spot.
A retitle that did not survive into the committed text still refuses on both lanes.
"""
import hashlib
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
import verify  # noqa: E402
from auto_safe_resolution import RESOLVED, resolve_conflict_bytes_detail  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

KI = "three-pillars-docs/known_issues.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
DROP = "zero-drop verifier detected a content drop"
BYTES = "resolved bytes do not match h1's committed blob"

OLD_TITLE = "### M44: nested stop is refused\n"
NEW_TITLE = "### M44: stop is refused by the harness\n"
A_ATOM = ("entry", "nested stop is refused")
BRANCH_ENTRY = "### M60: branch issue\nbranch body.\n\n"
MASTER_ENTRY = "### M61: master issue\nmaster body.\n\n"
TAIL = "## History\n\n- **2026-09-01** — seed\n"
LIVE_BASE = ("# Known Issues\n\n## Medium\n\n" + OLD_TITLE + "A body.\n\n"
             "### M50: first filler\nfiller body.\n\n### M51: second filler\nfiller body.\n\n"
             + TAIL)
MASTER_TEXT = LIVE_BASE.replace(OLD_TITLE, NEW_TITLE).replace(TAIL, MASTER_ENTRY + TAIL)
BRANCH_TEXT = LIVE_BASE.replace(TAIL, BRANCH_ENTRY + TAIL)
MERGED_TEXT = LIVE_BASE.replace(OLD_TITLE, NEW_TITLE).replace(TAIL, BRANCH_ENTRY + MASTER_ENTRY + TAIL)


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


def write(repo, text):
    p = repo / KI
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def setup(root):
    """Base on master; `feat` appends a keyed entry; master retitles M44 in place and appends its
    own keyed entry at the same spot. Returns (repo, h0) with `feat` checked out."""
    repo = root / "r"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "master")
    write(repo, LIVE_BASE)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, BRANCH_TEXT)
    commit(repo, "feat")
    git(repo, "checkout", "-q", "master")
    write(repo, MASTER_TEXT)
    commit(repo, "master")
    git(repo, "update-ref", "refs/remotes/origin/master", "master")   # cond1 reads origin/<base>
    git(repo, "checkout", "-q", "feat")
    return repo, git(repo, "rev-parse", "HEAD").stdout.strip()


def commit_merge(repo) -> str:
    git(repo, "commit", "-q", "-m", "Merge master into feat")
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def hand_resolution(repo, text) -> str:
    """Start the merge, write `text` as the living doc's resolution, commit it as h1."""
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    write(repo, text)
    git(repo, "add", "--", KI)
    return commit_merge(repo)


def conflicts_of(repo, h0, h1):
    seam = base_sync_cert._make_default_git(repo)
    parents, reason = base_sync_cert._cond1_merge_shape(seam, h0, h1, "master")
    assert not reason, reason
    _tree, conflicts, reason = base_sync_cert._cond2_recompute(seam, h0, parents[1])
    assert not reason, reason
    assert set(conflicts) == {KI}
    return seam, conflicts


def test_the_setup_is_a_real_conflict_the_two_way_check_calls_a_drop(tmp_path):
    repo, _h0 = setup(tmp_path)
    merge = git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    assert merge.returncode != 0 and git(repo, "ls-files", "-u").stdout
    base, ours, theirs = (git(repo, "show", f":{n}:{KI}").stdout for n in (1, 2, 3))
    git(repo, "merge", "--abort")
    assert (base, ours, theirs) == (LIVE_BASE, BRANCH_TEXT, MASTER_TEXT)
    status, merged, mechanical = resolve_conflict_bytes_detail(
        base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and mechanical is True and merged == MERGED_TEXT
    two_way = verify.verify(ours, theirs, merged, base=None, mechanical_applied=True)
    assert two_way.verdict == verify.DROPS_DETECTED and two_way.dropped == [A_ATOM]
    three_way = verify.verify(ours, theirs, merged, base=base, mechanical_applied=True)
    assert three_way.verdict == verify.VERIFIED and three_way.excused == [A_ATOM]


def test_a_mechanical_merge_with_a_one_side_retitle_certifies_on_both_lanes(tmp_path):
    repo, h0 = setup(tmp_path)
    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    h1 = commit_merge(repo)
    assert (repo / KI).read_text(encoding="utf-8") == MERGED_TEXT
    seam, conflicts = conflicts_of(repo, h0, h1)
    assert base_sync_cert._cond5_resolve(seam, conflicts, h1) == ""
    strict = base_sync_cert._certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert strict.ok, strict.reason
    carry = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert carry.ok, carry.reason


def test_a_hand_resolution_that_keeps_masters_retitle_carries(tmp_path):
    repo, h0 = setup(tmp_path)
    swapped = MERGED_TEXT.replace(BRANCH_ENTRY + MASTER_ENTRY, MASTER_ENTRY + BRANCH_ENTRY)
    assert swapped != MERGED_TEXT
    h1 = hand_resolution(repo, swapped)
    strict = base_sync_cert._certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert not strict.ok and strict.reason == BYTES
    carry = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert carry.ok, carry.reason
    assert KI in carry.conflicted_paths


def test_a_hand_resolution_that_loses_masters_retitle_refuses(tmp_path):
    repo, h0 = setup(tmp_path)
    h1 = hand_resolution(repo, MERGED_TEXT.replace(NEW_TITLE, OLD_TITLE))
    carry = living_doc_carry.certify_link_carry(repo, h0, h1, base_ref="master")
    assert not carry.ok and carry.reason == DROP, carry.reason


# --- the strict certifier on canned blobs (no repo): a sibling rename and a real drop ----------

HEAD = "# Roadmap\n\n| ID | Design | Status |\n| --- | --- | --- |\n"
D1 = "| D1 | alpha | Complete |\n"
D4 = "| D4 | delta | Complete |\n"
RO_BASE = HEAD + D1 + D4
RO_OURS = RO_BASE + "| D2 | beta | In progress |\n"
D3 = "| D3 | gamma | In progress |\n"
RO_THEIRS_RENAME = RO_BASE.replace("| alpha |", "| alpha-renamed |") + D3
RO_THEIRS_DELETE = RO_BASE.replace(D1, "") + D3


def blob_seam(blobs, h1_oid):
    """A `run_git` seam serving canned plumbing output, so cond 5 runs with no repo on disk."""
    def _git(args):
        if args[0] == "ls-tree":
            return 0, f"100644 blob {h1_oid}\t{KI}\n", ""
        if args[0] == "cat-file":
            return 0, blobs[args[2]], ""
        raise AssertionError(f"unexpected plumbing call: {args}")
    return _git


def cond5(base, ours, theirs):
    """`_cond5_resolve`'s reason for a link whose h1 blob is exactly the mechanical merge."""
    status, merged, _mech = resolve_conflict_bytes_detail(
        base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED
    data = merged.encode("utf-8")
    oid = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    blobs = {"1" * 40: base, "2" * 40: ours, "3" * 40: theirs}
    conflicts = {KI: {s: ("100644", str(s) * 40) for s in (1, 2, 3)}}
    return base_sync_cert._cond5_resolve(blob_seam(blobs, oid), conflicts, "h1")


def test_a_one_side_row_rename_passes_cond5():
    assert cond5(RO_BASE, RO_OURS, RO_THEIRS_RENAME) == ""


def test_a_one_side_row_deletion_still_fails_cond5():
    assert cond5(RO_BASE, RO_OURS, RO_THEIRS_DELETE) == DROP
