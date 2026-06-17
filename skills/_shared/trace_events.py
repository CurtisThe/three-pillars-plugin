"""trace_events.py — Versioned event vocabulary for the trace system.

Public API:
  TRACE_SCHEMA_VERSION : str
      Schema version string, bumped only on a breaking event/id change.

  Event-type constants (8 total):
      RUN_START, RUN_END, SLOT_ENTER, SLOT_EXIT,
      DISPATCH, RETURN, TOOL_CALL, TOOL_RETURN

  invocation_id(slot: str, attempt: int) -> str
      Deterministic f"{slot}#{attempt}" (e.g. "design-audit#2").

  event(event_type, *, invocation_id=None, payload, ts=None) -> dict
      Build {"v", "ts", "event_type", "invocation_id", "payload"}.
      ts defaults to datetime.now(timezone.utc) as ISO-8601 with Z suffix.

Pure constants + builders — no I/O, stdlib-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

TRACE_SCHEMA_VERSION: str = "1"

# ---------------------------------------------------------------------------
# Event-type constants — wire literals; tests anchor these exact strings
# ---------------------------------------------------------------------------

RUN_START: str = "RUN_START"
RUN_END: str = "RUN_END"
SLOT_ENTER: str = "SLOT_ENTER"
SLOT_EXIT: str = "SLOT_EXIT"
DISPATCH: str = "DISPATCH"
RETURN: str = "RETURN"
TOOL_CALL: str = "TOOL_CALL"
TOOL_RETURN: str = "TOOL_RETURN"

# ---------------------------------------------------------------------------
# invocation_id
# ---------------------------------------------------------------------------


def invocation_id(slot: str, attempt: int) -> str:
    """Return a deterministic invocation id: f"{slot}#{attempt}".

    Examples:
        invocation_id("design-audit", 2) -> "design-audit#2"
        invocation_id("design-audit", 1) -> "design-audit#1"
    """
    return f"{slot}#{attempt}"


# ---------------------------------------------------------------------------
# event() builder
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def event(
    event_type: str,
    *,
    invocation_id: str | None = None,  # noqa: F811 — shadows the function above
    payload: dict[str, Any],
    ts: str | None = None,
) -> dict[str, Any]:
    """Build a trace event dict.

    Args:
        event_type:     One of the 8 event-type constants.
        invocation_id:  The slot#attempt identifier (or None for run-level).
        payload:        Caller-supplied content dict.
        ts:             ISO-8601 UTC timestamp; defaults to now().

    Returns:
        {"v", "ts", "event_type", "invocation_id", "payload"}
    """
    return {
        "v": TRACE_SCHEMA_VERSION,
        "ts": ts if ts is not None else _utc_now_iso(),
        "event_type": event_type,
        "invocation_id": invocation_id,
        "payload": payload,
    }
