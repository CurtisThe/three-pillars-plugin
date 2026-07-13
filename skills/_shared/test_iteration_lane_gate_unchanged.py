"""test_iteration_lane_gate_unchanged.py — B2: the merge gate is byte-for-byte unchanged.

Two things are pinned here, both against the REAL seam (no I/O mocks):

  1. LOAD-BEARING + PERMANENT — the real `ci_local_stamp.pred_ci_local_stamp` still FAILs
     any head lacking a fresh, clean stamp and PASSes only for a head-matched clean stamp.
     Because the fast (iteration) lane writes NO stamp, it can NEVER satisfy this gate:
     exactly one full stamp-writing `scripts/ci-local.sh` run is still mandatory before a
     PR can land. This sub-assertion is unconditional — it holds post-merge on master and
     in a shallow consumer clone alike.

  2. BYTE-UNCHANGED (defensive, skippable) — this design must touch neither
     `ci_local_stamp.py` nor `gate_roster.py`. The changed-file set is derived from
     `git diff --name-only <base>...HEAD` ONLY when a base ref resolves; when none does
     (post-merge on master where the diff is empty anyway, or a shallow clone), the
     sub-assertion `pytest.skip`s rather than erroring or vacuously passing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci_local_stamp import STAMP_SCHEMA, pred_ci_local_stamp
from deterministic_gate import GateVerdict

REPO_ROOT = Path(__file__).resolve().parents[2]
_HEAD = "a" * 40
_OTHER = "b" * 40
# repo_root is irrelevant when an explicit `stamp=` is injected (hermetic seam).
_RR = str(REPO_ROOT)


def _fresh(head: str, *, dirty: bool = False) -> dict:
    return {"schema": STAMP_SCHEMA, "head_sha": head, "dirty": dirty}


# --- (1) the real predicate still gates — load-bearing, unconditional --------

def test_no_stamp_fails():
    r = pred_ci_local_stamp(_HEAD, repo_root=_RR, stamp=None)
    assert r.verdict == GateVerdict.FAIL, (
        "a head with no stamp must FAIL — the fast lane (which writes none) can never land"
    )


def test_stale_stamp_fails():
    r = pred_ci_local_stamp(_HEAD, repo_root=_RR, stamp=_fresh(_OTHER))
    assert r.verdict == GateVerdict.FAIL, "a head-mismatched (stale) stamp must FAIL (drift)"


def test_dirty_stamp_fails():
    r = pred_ci_local_stamp(_HEAD, repo_root=_RR, stamp=_fresh(_HEAD, dirty=True))
    assert r.verdict == GateVerdict.FAIL, "a dirty stamp must FAIL (tests ran on uncommitted state)"


def test_fresh_clean_stamp_passes():
    r = pred_ci_local_stamp(_HEAD, repo_root=_RR, stamp=_fresh(_HEAD))
    assert r.verdict == GateVerdict.PASS, (
        "only a head-matched, clean stamp PASSes — this is what the full ci-local.sh mints"
    )


# --- (2) the gate predicate files carry zero diff — defensive, skippable -----

def _resolve_base() -> "str | None":
    for ref in ("origin/master", "master", "origin/main", "main"):
        rc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            capture_output=True,
        ).returncode
        if rc == 0:
            return ref
    return None


def test_gate_files_untouched_by_this_design():
    base = _resolve_base()
    if base is None:
        pytest.skip("no base ref resolves (post-merge on master / shallow clone) — nothing to diff")
    changed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for guarded in ("skills/_shared/ci_local_stamp.py", "skills/_shared/gate_roster.py"):
        assert guarded not in changed, (
            f"{guarded} MUST carry zero diff from this design — the merge gate is "
            "byte-for-byte untouched (design B2 / hard constraint)"
        )
