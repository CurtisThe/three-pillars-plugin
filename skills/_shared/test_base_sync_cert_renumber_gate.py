"""Round 20 — the certifier never certifies an `id-renumber-collision` as a mechanical merge.

`base_sync_cert._cond5_resolve` keeps no class allowlist of its own (condition 3 is a PATH
allowlist): it re-runs the shared byte path, `auto_safe_resolution.resolve_conflict_bytes`, whose
`resolve.resolve_hunk` honours `classify.GATED`. So the gate reaches the certifier with no
certifier-side change, and this pins that on a real 2-parent merge: a link whose ONLY conflict is a
renumber collision, committed with the exact bytes the un-gated resolver produces, fails strict
certification, and the relaxed carry lane can only carry it as a HAND-resolution (K = the file).

Without the gate the same link certifies strictly (the control below), i.e. this test fails if
`id-renumber-collision` leaves `classify.GATED`.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402
from base_sync_cert import _certify_link_unchecked  # noqa: E402
from base_sync_repo import build_scenario, diverge_living_doc, force_merge_commit  # noqa: E402
from living_doc_carry import certify_link_carry  # noqa: E402

import resolve  # noqa: E402 — on sys.path via auto_safe_resolution's shim

KI = "three-pillars-docs/known_issues.md"
RENUMBER = "id-renumber-collision"


def _renumber_link(tmp_path, monkeypatch):
    """Both sides append a `### L67:` entry to known_issues.md; commit the merge with the bytes the
    UN-gated resolver would have produced (theirs' — the base branch's — entry renumbered L68)."""
    s = build_scenario(tmp_path)
    base = (s.repo_dir / KI).read_text(encoding="utf-8")        # the merge base's blob
    diverge_living_doc(s, base_line="\n### L67: base-side entry\nbase body\n",
                       design_line="\n### L67: design-side entry\ndesign body\n")
    h0 = s.head()
    ours = s.git("show", f"{h0}:{KI}").stdout
    theirs = s.origin_git("show", f"{s.origin_head()}:{KI}").stdout
    assert resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)[0] != RESOLVED
    with monkeypatch.context() as m:
        m.setattr(resolve, "GATED", resolve.GATED - {RENUMBER})
        status, ungated = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and "### L68: base-side entry" in ungated, ungated
    return s, h0, force_merge_commit(s, {KI: ungated})


def test_a_renumber_only_link_does_not_certify_as_mechanical(tmp_path, monkeypatch):
    s, h0, h1 = _renumber_link(tmp_path, monkeypatch)
    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is False
    assert strict.reason == "resolver could not deterministically reproduce a resolution"
    assert strict.conflicted_paths == (KI,)
    carry = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert carry.ok is True and carry.conflicted_paths == (KI,), carry   # a hand-res, not mechanical


def test_control_with_the_gate_lifted_the_same_link_certifies_strictly(tmp_path, monkeypatch):
    s, h0, h1 = _renumber_link(tmp_path, monkeypatch)
    monkeypatch.setattr(resolve, "GATED", resolve.GATED - {RENUMBER})
    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is True, strict.reason
    assert certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref).conflicted_paths == ()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
