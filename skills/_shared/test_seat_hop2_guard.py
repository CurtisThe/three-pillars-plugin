"""test_seat_hop2_guard.py — SKILL.md pin tests for the [N3] dispatch-from-seat
hop-2 existence guard (plugin-mode-parity Task 3.8 expansion).

Catalog N3: `skills/tp-merge/SKILL.md` and `skills/tp-merge-from-main/SKILL.md`
both dispatch-from-seat via a two-hop resolution (`seat_resolve.sh --where`,
then `resolve_root.sh --skill-dir "$SEAT"/skills/...`). Hop 2 assumes the seat
(the base checkout) CONTAINS the framework code — true only in the dev repo
(the framework repo is its own seat). On a consumer repo the seat is the
consumer's own base checkout (or `NONE`), so
`"$SEAT"/skills/_shared/resolve_root.sh` does not exist and hop 2 fails loud,
leaving the agent to improvise a recovery.

Fix (D7 SEAT pattern, per the catalog's own fix snippet): existence-guard
hop 2 so an absent/NONE seat falls back to the naive `$TP_ROOT` automatically
(documented-safe: the independent-oracle guard still fails CLOSED, only the
base-sync approval-carry capability is lost — see each SKILL.md's own note).

Run with: pytest skills/_shared/test_seat_hop2_guard.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_SITES = [
    ("skills/tp-merge/SKILL.md", "skills/tp-merge"),
    ("skills/tp-merge-from-main/SKILL.md", "skills/tp-merge-from-main"),
]


@pytest.mark.parametrize("relpath,skill_dir", _SITES)
def test_hop2_is_existence_guarded(relpath, skill_dir):
    """Hop 2's resolve_root.sh call must be gated on '-f \"$SEAT\"/skills/_shared/resolve_root.sh'."""
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert '-f "$SEAT"/skills/_shared/resolve_root.sh' in text, (
        f"{relpath}: hop 2 must be existence-guarded "
        '(`[ -f "$SEAT"/skills/_shared/resolve_root.sh ]`) before dereferencing it'
    )


@pytest.mark.parametrize("relpath,skill_dir", _SITES)
def test_hop2_falls_back_to_tp_root(relpath, skill_dir):
    """The guard's else branch must fall back to the naive $TP_ROOT (documented-safe path)."""
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert 'TP_SEAT_ROOT="$TP_ROOT"' in text, (
        f"{relpath}: the existence-guard's fallback must set TP_SEAT_ROOT=\"$TP_ROOT\""
    )


@pytest.mark.parametrize("relpath,skill_dir", _SITES)
def test_hop2_guard_also_checks_none_seat(relpath, skill_dir):
    """The guard must also treat seat_resolve.sh's 'NONE' sentinel as a fallback trigger."""
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert '"$SEAT" != "NONE"' in text, (
        f"{relpath}: the existence guard must also check for the seat_resolve.sh 'NONE' sentinel"
    )


@pytest.mark.parametrize("relpath,skill_dir", _SITES)
def test_hop2_call_is_inside_the_guard_conditional(relpath, skill_dir):
    """The resolve_root.sh dereference must appear AFTER the existence-guard's 'if', not before it."""
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    guard_idx = text.find('-f "$SEAT"/skills/_shared/resolve_root.sh')
    deref_idx = text.find(f'resolve_root.sh --skill-dir "$SEAT"/{skill_dir}')
    assert guard_idx != -1 and deref_idx != -1, (
        f"{relpath}: expected both the guard test and the hop-2 dereference to be present"
    )
    assert guard_idx < deref_idx, (
        f"{relpath}: the existence-guard test must precede the hop-2 dereference "
        "(the dereference must be gated ON the guard, not the other way around)"
    )
