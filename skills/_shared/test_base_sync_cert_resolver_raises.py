"""Round 18, R5 — a resolver that RAISES inside condition 5 must fail the link, never pass it.

Round 17 made the byte path raise `ConflictCountMismatch` (a `MergeFileError`) when the labelled
parse finds a different number of regions than `git merge-file` wrote, and relied on
`_certify_link_unchecked`'s catch-all to turn that into a failed link. No test drove an exception
through condition 5, so flipping the catch-all to `LinkCheck(True, ...)` survived every
base_sync_cert and auto_safe test. Both cases below run a real certified base-sync merge whose
link passes unpatched (the control), then make condition 5's resolver raise.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import auto_safe_resolution as asr  # noqa: E402
import base_sync_cert  # noqa: E402
from base_sync_cert import _certify_link_unchecked  # noqa: E402
from base_sync_repo import build_scenario, diverge_living_doc, make_certified_sync_merge  # noqa: E402

INTERNAL = "internal error during link certification"


def _certified_link(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    control = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert control.ok is True, control.reason
    return s, h0, h1


def test_a_conflict_count_mismatch_in_condition_5_fails_the_link(tmp_path, monkeypatch):
    s, h0, h1 = _certified_link(tmp_path)
    real_resolve, real_check = asr.resolve_file, asr.check_conflict_count
    raised = []

    def _parse_loses_a_region(text, force=False, labels=None):
        status, lines, results = real_resolve(text, force=force, labels=labels)
        return status, lines, results[:-1]

    def _spy(d, parsed_hunks):
        try:
            real_check(d, parsed_hunks)
        except asr.ConflictCountMismatch as exc:
            raised.append(exc)
            raise
    monkeypatch.setattr(asr, "resolve_file", _parse_loses_a_region)
    monkeypatch.setattr(asr, "check_conflict_count", _spy)

    lc = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert raised, "condition 5 must have reached the real conflict-count check and raised"
    assert lc.ok is False and lc.reason == INTERNAL, lc


def test_any_exception_from_the_condition_5_resolver_fails_the_link(tmp_path, monkeypatch):
    s, h0, h1 = _certified_link(tmp_path)

    def _raises(**_kw):
        raise RuntimeError("resolver blew up")
    monkeypatch.setattr(base_sync_cert, "resolve_conflict_bytes", _raises)
    lc = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False and lc.reason == INTERNAL, lc
