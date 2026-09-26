"""Adversarial harness -- single-link attacks 1-3 (SHIP GATE cases 1, 2, 3) against the
certified no-op-chain primitive (plan.md Phase 4, tasks 4.1-4.3). Attack 4 (squash / rebase /
amend head-moves, case 4) continues in `test_base_sync_cert_attacks2.py` (split per the
plan's named escape hatch to stay under the 300-line soft cap).

Every fixture here is a SOUNDNESS pin: if a crafted attack fails to refuse (or a happy chain
fails to certify), that is a bug in `base_sync_cert.py`/`base_sync_oracle.py`, never in the
test. The independent-oracle precondition is satisfied EXPLICITLY via the case-14
seat-on-base shape (`_seat_oracle_on_base`) so every refusal below is non-vacuous -- each
fixture reaches (and fails at) the specific RME condition under test, not the oracle guard.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402

_MERGE_SCRIPTS = os.path.join(os.path.dirname(__file__), os.pardir, "tp-merge-from-main", "scripts")
if _MERGE_SCRIPTS not in sys.path:
    sys.path.insert(0, _MERGE_SCRIPTS)
import verify as _verify  # noqa: E402

from base_sync_cert import certify_link, find_certified_anchor  # noqa: E402
from base_sync_repo import (  # noqa: E402
    LIVING_DOC_PATH,
    build_scenario,
    craft_merge_with_parents,
    diverge_base_only,
    diverge_living_doc,
    force_merge_commit,
    make_certified_sync_merge,
    tamper_smuggle_edit,
)

# Task 7.4 (attack 5, SHIP GATE): both gate consumers + review_proof's digest regexes.
_PR_ITERATE_SCRIPTS = os.path.join(os.path.dirname(__file__), os.pardir,
                                   "tp-pr-iterate", "scripts")
if _PR_ITERATE_SCRIPTS not in sys.path:
    sys.path.insert(0, _PR_ITERATE_SCRIPTS)

import review_proof  # noqa: E402
import proof_predicate  # noqa: E402
import human_approval  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402


def _tree_of(scenario, commit_sha: str) -> str:
    r = subprocess.run(["git", "-C", str(scenario.repo_dir), "rev-parse", f"{commit_sha}^{{tree}}"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _seat_oracle_on_base(s, monkeypatch) -> None:
    """Case-14 shape (`test_base_sync_cert_oracle_soundness.py::
    test_fixture14_legitimate_seat_on_base_accepts`): check `repo_dir` out onto a
    freshly-fetched origin/<base> and point the oracle's own code-dir resolution at it -- the
    normal post-base-sync seat topology. These fixtures pin RME-condition / chain behavior,
    not the oracle itself, so satisfying it is done EXPLICITLY rather than left to incidental
    ancestor-of-the-real-checkout luck."""
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


# ============================================================
# Task 4.1: Attack 1 [case 1] -- smuggled hunk in a NON-conflicted region
# ============================================================


def test_attack1_smuggled_hunk_in_non_conflicted_region_refuses(tmp_path, monkeypatch):
    """A base-sync merge whose committed tree adds a semantic hunk in a NON-conflicted
    region of an AUTO-SAFE file -- `diverge_base_only` never puts LIVING_DOC_PATH in
    conflict (K=empty, a clean auto-merge), so the ENTIRE file is 'outside K': ANY smuggled
    edit there byte-differs from the recomputed T -> condition 4 fails; no carry."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tampered = tamper_smuggle_edit(s, h1, LIVING_DOC_PATH, "SMUGGLED SEMANTIC HUNK\n")
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, tampered, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "change outside the conflicted region (condition 4)"

    result = find_certified_anchor(str(s.repo_dir), tampered, {h0}, base_ref=s.base_ref)
    assert result.certified is False
    assert result.anchor is None


# ============================================================
# Task 4.2: Attack 2 [case 2] -- smuggled semantic resolution of a conflicted hunk
# ============================================================


def test_attack2_hand_resolution_byte_inequality_yet_verify_clean(tmp_path, monkeypatch):
    """A conflicted AUTO-SAFE hunk hand-resolved to bytes the deterministic resolver does NOT
    reproduce -> condition 5 fails on the hash-object byte-inequality check. The hand
    resolution keeps every content atom from BOTH sides (in theirs-then-ours order, the reverse
    of the resolver's keep-both), so `verify.verify(ours, theirs, merged)` is independently CLEAN --
    both are asserted, isolating byte-equality as the load-bearing discriminator (a fixture
    that only tripped the verify backstop would never exercise it). This is also the
    primitive-level core of attack 8b (a tampered resolver output never byte-reproduces the
    honest resolver's)."""
    s = build_scenario(tmp_path)
    diverge_living_doc(s)   # base: "- **2026-01-01** — base-side change"; design: "... 2026-01-02 ..."
    h0 = s.head()
    p2 = s.origin_head()
    ours_txt = s.git("show", f"{h0}:{LIVING_DOC_PATH}", check=True).stdout
    theirs_txt = s.origin_git("show", f"{p2}:{LIVING_DOC_PATH}", check=True).stdout

    # Same two entries the honest resolver would keep, deliberately reordered -- verify() is
    # order-independent (a set of log signatures), so every atom from ours/theirs still survives.
    hand_resolved = (
        "# Fixture Living Doc\n\n"
        "### Z0: seed entry\n"
        "seed body line.\n"
        "- **2026-01-01** — base-side change\n"
        "- **2026-01-02** — design-side change\n"
    )
    r = _verify.verify(ours_txt, theirs_txt, hand_resolved, mechanical_applied=True)
    assert r.ok is True, r.dropped

    tampered = force_merge_commit(s, {LIVING_DOC_PATH: hand_resolved})
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, tampered, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "resolved bytes do not match h1's committed blob"


# ============================================================
# Task 4.3: Attack 3 [case 3] -- crafted merge, second parent off-base
# ============================================================


def test_attack3_second_parent_off_base_refuses(tmp_path, monkeypatch):
    """A crafted 2-parent merge whose second parent is NOT reachable from origin/<base> ->
    condition 1 fails ('second parent not on base branch')."""
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tree = _tree_of(s, h1)
    off_base = h1   # design-branch tip: never reachable from origin/<base>
    crafted = craft_merge_with_parents(s, tree, [h0, off_base])
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, crafted, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "second parent not on base branch"

    result = find_certified_anchor(str(s.repo_dir), crafted, {h0}, base_ref=s.base_ref)
    assert result.certified is False
    assert result.anchor is None


# ============================================================
# Task 7.4: Attack 5 [case 5, SHIP GATE] -- comment non-authority on BOTH consumers
# ============================================================

_CARRY_CONFIG = {
    "review": {"approval_survives_safe_base_sync": True, "base_sync_carry_max_chain": 5},
}


def _digest_body(head):
    meta = {
        "base": "base000", "head": head, "files_changed": 2,
        "insertions": 3, "deletions": 1, "degraded": False, "reason": None,
    }
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _cert_comment_body(pre_sha: str, post_sha: str) -> str:
    """The `basesync-cert.v1` producer-breadcrumb format (detailed-design.md's
    Producer breadcrumb section) -- audit-only, ZERO gate authority. Inlined literally
    (Phase 8's `cert_comment.py` owns the real formatter; this test needs only the
    exact SHAPE, to prove neither regex can ever mistake it for a proof digest)."""
    return (
        f"<sub>basesync-cert.v1: pre `{pre_sha}` · post `{post_sha}` · "
        "allowlist v1 · classes [design-inventory-row-merge]</sub>"
    )


def _approved_review(commit_id, login="alice"):
    return {
        "user": {"login": login, "type": "User"},
        "state": "APPROVED",
        "submitted_at": "2026-06-08T14:00:00Z",
        "commit_id": commit_id,
    }


def test_attack5_forged_wrong_author_deleted_cert_comment_verdict_invariant(
    tmp_path, monkeypatch,
):
    """A forged / wrong-author / deleted `basesync-cert.v1` comment must NEVER change
    the gate verdict -- the comment is structurally not an input (anchor discovery is
    the pure git walk). Asserted through BOTH consumer entry points."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    _seat_oracle_on_base(s, monkeypatch)

    pr_url = "https://github.com/o/r/pull/5"
    runners = {
        "self_login_fn": lambda: "ci-bot",
        "head_fn": lambda _u: {"headRefOid": h1, "commits": []},
        "reviews_fn": lambda _u: [_approved_review(h0)],
        "carry_repo_root": str(s.repo_dir),
        "derive_base_ref_fn": lambda _u: s.base_ref,
    }

    # Consumer 1 (approved_on_head_result) has NO comment-reading channel at all in
    # its signature -- a cert comment structurally CANNOT reach it, by construction.
    import inspect
    assert "comments_fn" not in inspect.signature(
        human_approval.approved_on_head_result
    ).parameters

    expected_carry_detail = (
        f"approval carried across 1 certified base-sync merge(s) (anchor {h0[:7]})"
    )
    consumer1_before = human_approval.approved_on_head_result(
        pr_url, runners=runners, config=_CARRY_CONFIG,
    )
    assert consumer1_before == (True, expected_carry_detail)

    # Consumer 2 (pred_review_proof_on_head) DOES read comments -- exercise all three
    # cert-comment states, each alongside the SAME real trusted proof digest anchored
    # at h0, and confirm the verdict + detail is byte-identical across all three.
    real_digest = {"author": "ci-bot", "body": _digest_body(h0)}
    forged_comment = {"author": "ci-bot", "body": _cert_comment_body("0" * 40, h1)}
    wrong_author_comment = {"author": "some-random-user", "body": _cert_comment_body(h0, h1)}

    states = {
        "forged": [real_digest, forged_comment],
        "wrong_author": [real_digest, wrong_author_comment],
        "deleted": [real_digest],   # the cert comment is simply absent
    }
    results = {}
    for name, comments in states.items():
        results[name] = proof_predicate.pred_review_proof_on_head(
            pr_url, h1,
            comments_fn=lambda _u, c=comments: c,
            self_login_fn=lambda: "ci-bot",
            config=_CARRY_CONFIG,
            repo_root=str(s.repo_dir),
            derive_base_ref_fn=lambda _u: s.base_ref,
        )

    verdict_detail_pairs = {name: (r.verdict, r.detail) for name, r in results.items()}
    assert len(set(verdict_detail_pairs.values())) == 1, verdict_detail_pairs
    assert results["forged"].verdict == GateVerdict.PASS
    assert "proof comment carried across 1 certified base-sync merge(s)" in (
        results["forged"].detail
    )

    # Consumer 1 re-evaluated -- unaffected by the fact that ANY cert comment exists.
    consumer1_after = human_approval.approved_on_head_result(
        pr_url, runners=runners, config=_CARRY_CONFIG,
    )
    assert consumer1_after == consumer1_before


def test_attack5_regex_disjointness_cert_comment_vs_proof_digest():
    """A `basesync-cert.v1:` body can NEVER match `review_proof._DIGEST_HEAD_RE` (or
    `_DEGRADED_RE`), and a real proof digest never looks like the cert envelope -- the
    two formats are lexically disjoint by construction."""
    cert_body = _cert_comment_body("a" * 40, "b" * 40)
    for line in cert_body.splitlines():
        assert review_proof._DIGEST_HEAD_RE.search(line) is None
        assert review_proof._DEGRADED_RE.search(line) is None

    digest_body = _digest_body("c" * 40)
    assert "basesync-cert.v1" not in digest_body


# ============================================================
# Task 1.4: cond 5 fails the link on an UNVERIFIABLE shape
# ============================================================

_BASE_TXT = ("*Last updated: 2026-05-01*\n\n# Known issues\n\n| ID | Name | Severity |\n"
             "| --- | --- | --- |\n| L1 |  | high |\n")
_OURS_TXT = _BASE_TXT + "| L4 |  | low |\n"
_THEIRS_TXT = _BASE_TXT + "| L5 |  | med |\n"


def _blob_seam(blobs: dict, h1_oid: str):
    """A `run_git` seam serving canned plumbing output, so cond 5 can be driven with no repo on
    disk (the same seam shape the other cond-5 fixtures use)."""
    def _git(args):
        if args[0] == "ls-tree":
            return 0, f"100644 blob {h1_oid}\t{LIVING_DOC_PATH}\n", ""
        if args[0] == "cat-file":
            return 0, blobs[args[2]], ""
        raise AssertionError(f"unexpected plumbing call: {args}")
    return _git


def test_unverifiable_fails_cond5():
    """A conflict the resolver DOES resolve mechanically but the verifier parses zero atoms
    from must fail condition 5 with its OWN distinct reason — not "" (a pass), and not the
    existing drop reason. `LinkCheck.ok` then goes False and the approval-carry conjunct fails.

    The blobs are a table whose Name cell is empty on every row: `classify.INV_ROW` keys on the ID
    cell alone, so `design-inventory-row-merge` still resolves mechanically, while `verify.ROW`
    signs the Name cell and yields no atom at all. (Before round 20 the fixture was an entry whose
    title had moved off its `### L<n>:` heading — an `id-renumber-collision`, a class now gated,
    which defers before any verifier runs.)
    """
    from auto_safe_resolution import RESOLVED as _R
    from auto_safe_resolution import resolve_conflict_bytes_detail
    from base_sync_cert import _cond5_resolve

    # Precondition: the resolver really does apply a mechanical resolution here...
    status, merged, mechanical = resolve_conflict_bytes_detail(
        base=_BASE_TXT, ours=_OURS_TXT, theirs=_THEIRS_TXT)
    assert status == _R and mechanical is True
    # ...and the verifier finds NOTHING to check — the silent-pass class this design closes.
    r = _verify.verify(_OURS_TXT, _THEIRS_TXT, merged, mechanical_applied=True)
    assert r.verdict == _verify.UNVERIFIABLE and r.pre_atoms == 0

    blobs = {"1" * 40: _BASE_TXT, "2" * 40: _OURS_TXT, "3" * 40: _THEIRS_TXT}
    conflicts = {LIVING_DOC_PATH: {1: ("100644", "1" * 40),
                                   2: ("100644", "2" * 40),
                                   3: ("100644", "3" * 40)}}
    reason = _cond5_resolve(_blob_seam(blobs, "a" * 40), conflicts, "h1")
    assert reason == "zero-drop verifier could not verify this file's shape"
    assert reason != ""                                             # never a silent pass
    assert reason != "zero-drop verifier detected a content drop"   # distinct from a real drop


def test_a_resolved_merge_the_verifier_finds_a_drop_in_fails_cond5_even_when_h1_matches():
    """Round 25: cond 5's zero-drop conjunct, reached. The row merge resolves mechanically and takes
    theirs' renamed Name cell for D1, so ours' `alpha` row atom is gone and `verify` reports
    DROPS_DETECTED. h1's blob IS the merged bytes, so the byte-match conjunct after it would pass:
    only the zero-drop conjunct can fail the link here."""
    import hashlib

    from auto_safe_resolution import RESOLVED as _R
    from auto_safe_resolution import resolve_conflict_bytes_detail
    from base_sync_cert import _cond5_resolve

    base = "# Roadmap\n\n| ID | Design | Status |\n| --- | --- | --- |\n| D1 | alpha | Complete |\n"
    ours = base + "| D2 | beta | In progress |\n"
    theirs = base.replace("| alpha |", "| alpha-renamed |") + "| D3 | gamma | In progress |\n"
    status, merged, mechanical = resolve_conflict_bytes_detail(base=base, ours=ours, theirs=theirs)
    assert status == _R and mechanical is True
    r = _verify.verify(ours, theirs, merged, mechanical_applied=True)
    assert r.verdict == _verify.DROPS_DETECTED and r.dropped == [("row", "alpha")]

    data = merged.encode("utf-8")
    merged_oid = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    blobs = {"1" * 40: base, "2" * 40: ours, "3" * 40: theirs}
    conflicts = {LIVING_DOC_PATH: {s: ("100644", str(s) * 40) for s in (1, 2, 3)}}
    assert _cond5_resolve(_blob_seam(blobs, merged_oid), conflicts, "h1") == \
        "zero-drop verifier detected a content drop"
