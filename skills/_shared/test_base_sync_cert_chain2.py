"""Adversarial harness -- attack 10 [case 10]: stale-ref after a rewritten base history and a
broken remote (plan.md Phase 5, task 5.5). Split from `test_base_sync_cert_chain.py` per the
plan's named escape hatch.

Pins 3.2's mandatory-fetch ordering: FRESH-DATA precedes everything else in
`oracle_independent`, so a broken remote refuses via the stale-base reason even though a
PRIOR evaluation (before the break) legitimately certified -- there is no fallback to a
locally-cached `origin/<base>` ref once fetch itself fails.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
from base_sync_cert import find_certified_anchor  # noqa: E402
from base_sync_oracle import _FETCH_REFUSE  # noqa: E402
from base_sync_repo import (  # noqa: E402
    break_remote,
    build_scenario,
    diverge_base_only,
    make_certified_sync_merge,
    rewrite_origin_base,
)


def _seat_oracle_on_base(s, monkeypatch) -> None:
    """Case-14 shape -- see `test_base_sync_cert_attacks.py::_seat_oracle_on_base`."""
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


def test_attack10_base_rewrite_plus_broken_remote_refuses_stale(tmp_path, monkeypatch):
    """A first evaluation legitimately certifies. Then origin's base history gets rewritten
    (amend) AND the remote breaks (fetch now fails) between evaluations. The SECOND
    evaluation must refuse with the stale-base reason -- NEVER certify reachability against
    the now-stale, locally-cached `origin/<base>` ref."""
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    _seat_oracle_on_base(s, monkeypatch)

    first = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref)
    assert first.certified is True, first.reason

    rewrite_origin_base(s)
    break_remote(s)

    second = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref)
    assert second.certified is False
    assert second.reason == _FETCH_REFUSE
