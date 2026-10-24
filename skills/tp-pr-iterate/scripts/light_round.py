"""light_round - the light / just-do-it Tier 7 round-1 rule (design: light-run-ceremony-diet, B2).

Round 1 of a light or just-do-it run is one `combined` finder plus the Opus
check. The `security` angle joins only when the diff touches a safety-gate path
or a trust-boundary surface, and on any detector failure (fail toward review).
Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import safety_gate  # noqa: E402
import trust_boundary  # noqa: E402

LIGHT_WEIGHTS = ("light", "just-do-it")


def needs_security(repo, pr_base, head) -> bool:
    """True when the PR touches a gate path or a trust surface; True on any failure."""
    try:
        if safety_gate.touches_gate(safety_gate.changed_paths(repo, pr_base, head)):
            return True
        return bool(trust_boundary.surfaces_for_range(repo, pr_base, head, three_dot=True))
    except Exception:
        return True
