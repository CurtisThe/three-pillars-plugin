"""trace_replay.py — Replay reader for the orchestrator record-replay system.

Public API:
  TraceVersionMismatch : Exception
      Raised by load() when meta.json.v != TRACE_SCHEMA_VERSION.

  ReplayCacheMiss : Exception
      Raised by ReplayCache.resolve() on a miss in strict mode (default).

  MISS : sentinel
      Returned by ReplayCache.resolve(strict=False) on a cache miss.

  class ReplayCache
      Indexed slot records. Constructed by load().

      has(invocation_id: str) -> bool
          Return True if the invocation_id is in the index.

      resolve(slot: str, attempt: int, strict: bool = True) -> dict
          Return the recorded clipped envelope for (slot, attempt).
          On miss: raise ReplayCacheMiss (strict=True, default) or
                   return MISS sentinel (strict=False).

      meta : dict
          The parsed meta.json for the trace run.

  load(trace_dir: Path) -> ReplayCache
      Read meta.json + all slot-*.json, index by invocation_id.
      Raises TraceVersionMismatch if meta.json.v != TRACE_SCHEMA_VERSION.

  diff(recorded_dir: Path, replay_dir: Path) -> list[dict]
      Compare two trace dirs slot-by-slot.
      Returns [] when all verdict/status/artifact-path fields match.
      Returns a list of {slot, field, recorded, replayed} dicts per mismatch.

Stdlib-only, no I/O beyond reading trace dirs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import trace_events

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TraceVersionMismatch(Exception):
    """Raised when meta.json.v does not match TRACE_SCHEMA_VERSION."""


class ReplayCacheMiss(Exception):
    """Raised by ReplayCache.resolve() on a strict miss."""


# ---------------------------------------------------------------------------
# MISS sentinel
# ---------------------------------------------------------------------------


class _MissSentinel:
    """Singleton sentinel returned by resolve(strict=False) on a miss."""

    _instance: "_MissSentinel | None" = None

    def __new__(cls) -> "_MissSentinel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISS"

    def __bool__(self) -> bool:
        return False


MISS: _MissSentinel = _MissSentinel()

# ---------------------------------------------------------------------------
# ReplayCache
# ---------------------------------------------------------------------------


class ReplayCache:
    """In-memory index of recorded slot envelopes, keyed by invocation_id."""

    def __init__(self, meta: dict[str, Any], slots: dict[str, dict]) -> None:
        self._meta = meta
        self._slots = slots  # {invocation_id: envelope}

    @property
    def meta(self) -> dict[str, Any]:
        """The parsed meta.json for this trace run."""
        return self._meta

    def has(self, invocation_id: str) -> bool:
        """Return True if invocation_id is in the index."""
        return invocation_id in self._slots

    def resolve(
        self,
        slot: str,
        attempt: int,
        strict: bool = True,
    ) -> dict[str, Any] | _MissSentinel:
        """Return the recorded clipped envelope for (slot, attempt).

        Args:
            slot:    The slot name (e.g. "design-audit").
            attempt: The attempt number (e.g. 1).
            strict:  If True (default), raise ReplayCacheMiss on a miss.
                     If False, return the MISS sentinel instead.

        Returns:
            The recorded clipped envelope dict, or MISS sentinel.

        Raises:
            ReplayCacheMiss: On a miss when strict=True (default).
        """
        inv_id = trace_events.invocation_id(slot, attempt)
        if inv_id in self._slots:
            return self._slots[inv_id]
        if strict:
            raise ReplayCacheMiss(
                f"replay-cache-miss {slot}#{attempt}"
            )
        return MISS


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


def load(trace_dir: Path) -> ReplayCache:
    """Read a trace dir and return a ReplayCache indexed by invocation_id.

    Args:
        trace_dir: Path to the trace run directory (contains meta.json +
                   slot-*.json files).

    Returns:
        A ReplayCache ready for resolve() calls.

    Raises:
        TraceVersionMismatch: If meta.json.v != TRACE_SCHEMA_VERSION.
        FileNotFoundError: If meta.json is missing.
    """
    trace_dir = Path(trace_dir)
    meta_path = trace_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Version guard
    if meta.get("v") != trace_events.TRACE_SCHEMA_VERSION:
        found = meta.get("v")
        expected = trace_events.TRACE_SCHEMA_VERSION
        raise TraceVersionMismatch(
            f"schema version mismatch: found {found!r}, "
            f"expected {expected!r} (TRACE_SCHEMA_VERSION)"
        )

    # Read all slot-*.json files
    slots: dict[str, dict] = {}
    for slot_file in sorted(trace_dir.glob("slot-*.json")):
        # Extract invocation_id from filename: "slot-<invocation-id>.json"
        # The invocation_id is the part after "slot-" and before ".json".
        stem = slot_file.stem  # e.g. "slot-design-audit#1"
        inv_id = stem[len("slot-"):]  # strip "slot-" prefix
        envelope = json.loads(slot_file.read_text(encoding="utf-8"))
        slots[inv_id] = envelope

    return ReplayCache(meta=meta, slots=slots)


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------

# Fields compared slot-by-slot; absence of a field is treated as None.
_DIFF_FIELDS = ("verdict", "status", "artifact_path")


def diff(recorded_dir: Path, replay_dir: Path) -> list[dict[str, Any]]:
    """Compare two trace dirs slot-by-slot on verdict/status/artifact-path.

    Args:
        recorded_dir: Path to the recorded trace directory.
        replay_dir:   Path to the replayed trace directory.

    Returns:
        [] when all compared fields match across all shared slots.
        A list of dicts (slot, field, recorded, replayed) per mismatch.
    """
    recorded_cache = load(Path(recorded_dir))
    replay_cache = load(Path(replay_dir))

    diffs: list[dict[str, Any]] = []

    # Compare slots present in the recorded cache against the replay cache.
    # Slots only in replay (not in recorded) are ignored per spec — the
    # canary asserts diff == [] for a round-trip, so both sides share the
    # same invocation_ids in the happy path.
    for inv_id, rec_env in recorded_cache._slots.items():
        rep_env = replay_cache._slots.get(inv_id)
        if rep_env is None:
            # Slot in recorded but absent in replay — treat all fields as missing.
            for field in _DIFF_FIELDS:
                rec_val = rec_env.get(field)
                if rec_val is not None:
                    diffs.append({
                        "slot": inv_id,
                        "field": field,
                        "recorded": rec_val,
                        "replayed": None,
                    })
            continue

        # Compare each tracked field
        for field in _DIFF_FIELDS:
            rec_val = rec_env.get(field)
            rep_val = rep_env.get(field)
            if rec_val != rep_val:
                diffs.append({
                    "slot": inv_id,
                    "field": field,
                    "recorded": rec_val,
                    "replayed": rep_val,
                })

    return diffs
