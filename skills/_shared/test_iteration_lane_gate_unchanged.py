"""test_iteration_lane_gate_unchanged.py — B2: the merge gate is untouched.

Two things are pinned here, both against the REAL seam (no I/O mocks, no git
history):

  1. LOAD-BEARING + PERMANENT — the real `ci_local_stamp.pred_ci_local_stamp` still FAILs
     any head lacking a fresh, clean stamp and PASSes only for a head-matched clean stamp.
     Because the fast (iteration) lane writes NO stamp, it can NEVER satisfy this gate:
     exactly one full stamp-writing `scripts/ci-local.sh` run is still mandatory before a
     PR can land. This sub-assertion is unconditional — it holds post-merge on master and
     in a shallow consumer clone alike.

  2. BEHAVIOURAL (defensive, git-history independent) — the LANE ASYMMETRY that makes
     (1) hold: the iteration lane (fast inner loop) can NEVER write the merge-gate stamp
     (`writes_stamp` is always False), while the gate lane reports `writes_stamp=True`.
     Pinned in a hermetic target repo in TWO shapes — shipping `scripts/ci-local.sh` and
     one declaring `ci.gate_command` — and read from the seam's own resolution, so it
     survives a consumer repo and any future design that legitimately edits the
     gate-predicate files (which this design, consumer-repo-parity H1, does).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ci_local_stamp import STAMP_SCHEMA, pred_ci_local_stamp
from deterministic_gate import GateVerdict
from iteration_lane import gate_command, iteration_command

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


# --- (2) the iteration lane can never satisfy the gate — behavioural ---------
#
# The asymmetry that makes (1) hold: the iteration lane NEVER writes the merge-gate
# stamp (`writes_stamp` always False) while the gate lane writes it. Verified against
# the seam's own resolution, in a hermetic target repo, in BOTH shapes — a repo shipping
# `scripts/ci-local.sh` and a repo declaring `ci.gate_command`. Git-history independent
# (survives consumer repos / future designs that legitimately edit the gate-predicate
# files).

def _ci_local_repo(root) -> None:
    """A target repo shipping `scripts/ci-local.sh` (no config)."""
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "ci-local.sh").write_text(
        "#!/usr/bin/env bash\n"
        'set -euo pipefail\n'
        'if [ "${1:-}" = "--fast" ]; then\n'
        "  echo fast\n"
        "  exit 0\n"
        "fi\n"
        "echo full\n"
    )


def _config_repo(root) -> None:
    """A target repo declaring `ci.gate_command` (a consumer repo's shape)."""
    import json

    cfg_dir = root / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"schema_version": 1, "ci": {"gate_command": "make ci"}}, indent=2) + "\n",
        encoding="utf-8",
    )


def _assert_lane_asymmetry(repo_root) -> None:
    # The iteration lane (both granularities) must NEVER carry the merge-gate stamp.
    for gran in ("task", "phase"):
        r = iteration_command(repo_root, granularity=gran)
        assert r.writes_stamp is False, (
            f"the iteration lane ({gran}) must NEVER write the merge-gate stamp "
            f"(writes_stamp is always False) — it can never satisfy the gate"
        )
    # The gate lane is the stamp source (writes_stamp True).
    g = gate_command(repo_root)
    assert g.writes_stamp is True, (
        "the gate lane is the stamp source (writes_stamp True)"
    )
    # The iteration lane is provably NOT the gate command in either shape.
    for gran in ("task", "phase"):
        it = iteration_command(repo_root, granularity=gran)
        assert it.command != g.command, (
            "the iteration lane must be a different command than the gate lane — "
            "it can never stand in for the full stamp-writing run (B1)"
        )


def test_iteration_lane_can_never_satisfy_the_gate_with_ci_local(tmp_path):
    """A repo shipping scripts/ci-local.sh: the fast lane never writes the stamp,
    the gate lane does (unchanged behaviour)."""
    _ci_local_repo(tmp_path)
    _assert_lane_asymmetry(tmp_path)


def test_iteration_lane_can_never_satisfy_the_gate_with_declared_command(tmp_path):
    """A repo declaring ci.gate_command: the fast lane STILL never writes the stamp
    (a declared gate command does not leak into the iteration lane), the gate lane
    resolves to the wrapper and writes the stamp."""
    _config_repo(tmp_path)
    _assert_lane_asymmetry(tmp_path)
