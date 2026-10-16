"""Git-fixture tests for `living_doc_carry.certify_link_carry` — happy path + broadening
(Phase 2, task 2.3).

Each fixture builds a real 2-parent base-sync merge via `build_scenario` + `diverge_living_doc`
/ a preamble-conflict helper + `force_merge_commit` (a hand-typed, non-reproducible
resolution). `certify_link_carry` / `_certify_link_unchecked` carry NO oracle guard (the public
`certify_link`/`find_certified_anchor` own it — exercised in Phase 3), so these direct calls
need no oracle seating; the K assertions prove each fixture reaches and passes relaxed-cond5, so
every certify/refuse is non-vacuous. The fail-closed attack pins live in
`test_base_sync_cert_handres_attacks.py`; the M3 documented-residual cases in `_residual.py`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from base_sync_cert import _certify_link_unchecked  # noqa: E402
from living_doc_carry import _mechanical_resolution, certify_link_carry  # noqa: E402
from base_sync_repo import (  # noqa: E402
    build_scenario,
    diverge_living_doc,
    force_merge_commit,
)

_MERGE_SCRIPTS = os.path.join(os.path.dirname(__file__), os.pardir, "tp-merge-from-main", "scripts")
if _MERGE_SCRIPTS not in sys.path:
    sys.path.insert(0, _MERGE_SCRIPTS)
import verify as _verify  # noqa: E402

KI = "three-pillars-docs/known_issues.md"

# A hand resolution that keeps EVERY atom from both sides, in the reverse of the order the
# deterministic keep-both emits (theirs' base-side entry first) — so it byte-differs from the
# mechanical merge yet is zero-drop clean.
_HAND_KEEP_ALL = (
    "# Fixture Living Doc\n\n"
    "### Z0: seed entry\n"
    "seed body line.\n"
    "- **2026-01-01** — base-side change\n"
    "- **2026-01-02** — design-side change\n"
)

_H = [("2026-07-09", "newest entry"), ("2026-06-15", "older entry")]


def _pre_doc(date: str, *, history=_H, extra: str = "") -> str:
    bullets = "".join(f"- **{d}** — {t}\n" for d, t in history)
    return (f"# Doc\n*Last updated: {date} — see [History](#history).*\n\n{extra}"
            f"## History\n\n{bullets}")


def _preamble_conflict(s, path, *, base_doc, origin_doc, design_doc) -> str:
    """Establish `base_doc` as the merge base of a conflict on `path`, then diverge the base
    branch to `origin_doc` and the design branch to `design_doc`. Returns h0 (design tip)."""
    (s.origin_dir / path).parent.mkdir(parents=True, exist_ok=True)
    (s.origin_dir / path).write_text(base_doc, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", "base: seed preamble doc")
    s.git("fetch", "--quiet", "origin", s.base_ref)
    s.git("merge", "--quiet", "--ff-only", f"origin/{s.base_ref}")
    (s.origin_dir / path).write_text(origin_doc, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", "base: diverge preamble")
    (s.repo_dir / path).write_text(design_doc, encoding="utf-8")
    s.git("add", "--", path)
    s.git("commit", "--quiet", "-m", "design: diverge preamble")
    return s.head()


# ---- (a) hand-res on an AUTO-SAFE living doc: strict refuses cond5, relaxed carries K=1 ----


def test_certify_link_carry_handres_known_issues_certifies_k1(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = force_merge_commit(s, {KI: _HAND_KEEP_ALL})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == (KI,)   # K=1: the one hand-res carry file

    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is False
    assert strict.reason == "resolved bytes do not match h1's committed blob"


# ---- (b) broader living doc NOT in AUTO_SAFE_PATHS: strict fails cond3, relaxed carries K=1 --


def test_certify_link_carry_broadening_design_md_certifies_k1(tmp_path):
    design_md = "three-pillars-docs/tp-designs/x/design.md"
    s = build_scenario(tmp_path, living_doc_path=design_md)
    diverge_living_doc(s, path=design_md)
    h0 = s.head()
    h1 = force_merge_commit(s, {design_md: _HAND_KEEP_ALL})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == (design_md,)   # K=1, the broader carry-set doc

    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is False
    assert strict.reason == "non-AUTO-SAFE conflict path"   # cond3, which the relaxed path skips


# ---- (c) preamble date-only divergence: mechanical byte-exact continue, K=0 (zero relaxation) --


def test_certify_link_carry_preamble_date_only_certifies_k0(tmp_path):
    """A date-only divergence is the mechanical `last-updated-preamble` now: the resolver keeps the
    later side's line, so the carry lane's History-date upgrade is no longer reached for it
    (`living_doc_carry.py` is unchanged) and strict cond5 reproduces the resolution itself."""
    path = "three-pillars-docs/architecture.md"
    base_doc = _pre_doc("2026-06-01")
    origin_doc = _pre_doc("2026-06-02")
    design_doc = _pre_doc("2026-06-03")
    h0 = _preamble_conflict(s := build_scenario(tmp_path), path,
                            base_doc=base_doc, origin_doc=origin_doc, design_doc=design_doc)

    # The mechanical resolution: the later side's line. ours = design side, theirs = base side
    # (the cert's stage2/stage3 orientation).
    mech = _mechanical_resolution(base_doc, design_doc, origin_doc)
    assert mech == _pre_doc("2026-06-03")   # the later side's line, no History-derived date

    h1 = force_merge_commit(s, {path: mech})
    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == ()   # K=0: committed == the zero-drop-verified mechanical merge

    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is True, strict.reason   # strict cond5 reproduces the AUTO-SAFE resolution


# ---- (d) richer preamble divergence: mechanical defers, hand-res carries K=1 ----


def test_certify_link_carry_richer_preamble_handres_k1(tmp_path):
    path = "three-pillars-docs/architecture.md"
    hnew = ("2026-07-20", "base advance")
    base_doc = _pre_doc("2026-06-01")
    origin_doc = _pre_doc("2026-06-02", history=[hnew, *_H])   # base prepended a History entry
    # trailing text after the closing `*` puts the region outside `LAST_UPDATED`: still `preamble`
    design_doc = _pre_doc("2026-06-03").replace(".*\n", ".* A trailing note.\n", 1)
    human = _pre_doc("2026-07-20", history=[hnew, *_H])         # keeps every atom, union History
    h0 = _preamble_conflict(s := build_scenario(tmp_path), path,
                            base_doc=base_doc, origin_doc=origin_doc, design_doc=design_doc)

    assert _mechanical_resolution(base_doc, design_doc, origin_doc) is None   # richer → defers
    r = _verify.verify(design_doc, origin_doc, human, base=None, mechanical_applied=False)
    assert r.ok is True, r.dropped   # the hand resolution is zero-drop clean

    h1 = force_merge_commit(s, {path: human})
    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == (path,)   # K=1, carried via the hand-res branch
