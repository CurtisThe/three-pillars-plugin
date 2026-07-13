"""Phase 1 Task 1.1 — verify cleanup-pending is in the collaboration.md phase enum.

Run with: pytest skills/tp-post-merge/scripts/test_collaboration_phase_enum.py -q
"""

from __future__ import annotations

import re
from pathlib import Path


COLLAB_MD = Path(__file__).resolve().parents[2] / "_shared" / "collaboration.md"

# The lock.json schema renders the phase field as a pipe-delimited enum, e.g.
#   "phase": "design|detail|plan|...|cleanup-pending",
_PHASE_ENUM_RE = re.compile(r'"phase"\s*:\s*"([^"]*)"')


def test_cleanup_pending_in_enum() -> None:
    text = COLLAB_MD.read_text(encoding="utf-8")
    matches = _PHASE_ENUM_RE.findall(text)
    assert matches, (
        "skills/_shared/collaboration.md must document the lock.json \"phase\" enum"
    )
    # Assert cleanup-pending is one of the pipe-delimited ENUM VALUES — not merely
    # mentioned in prose elsewhere in the file (which would be a false positive).
    enum_values = {v.strip() for m in matches for v in m.split("|")}
    assert "cleanup-pending" in enum_values, (
        "skills/_shared/collaboration.md must include 'cleanup-pending' as a value in "
        f"the lock.json phase enum (found enum values: {sorted(enum_values)})"
    )


def test_distinct_audit_tokens_in_enum() -> None:
    text = COLLAB_MD.read_text(encoding="utf-8")
    matches = _PHASE_ENUM_RE.findall(text)
    assert matches, (
        "skills/_shared/collaboration.md must document the lock.json \"phase\" enum"
    )
    enum_values = {v.strip() for m in matches for v in m.split("|")}
    distinct_audit_tokens = {
        "design-audit",
        "plan-audit",
        "implementation-audit",
        "spike-plan-audit",
        "spike-results",
    }
    missing = distinct_audit_tokens - enum_values
    assert not missing, (
        "skills/_shared/collaboration.md must include the distinct audit-phase "
        f"tokens as values in the lock.json phase enum (missing: {sorted(missing)}; "
        f"found enum values: {sorted(enum_values)})"
    )
    # The bare `audit` token must still be present — retained as a deprecated
    # legacy alias for one release (no active site emits it anymore).
    assert "audit" in enum_values, (
        "skills/_shared/collaboration.md must retain 'audit' as a deprecated "
        f"legacy alias in the lock.json phase enum (found enum values: {sorted(enum_values)})"
    )
