"""test_trace_canary.py — Record→replay round-trip canary (Task 6.4).

Builds a tiny recorded trace dir via TraceWriter, drives a replay through
ReplayCache.resolve into a second TraceWriter dir (no live calls), and
asserts diff(recorded_dir, replay_dir) == [] — the green canary state.
Also asserts a deliberately mutated verdict makes diff non-empty (tripwire).

Split from test_trace_replay.py (375 lines) to keep both files under the
500-line hard cap; the canary is a cohesive integration scenario that sits
naturally in its own module.
"""

from __future__ import annotations

import json
from pathlib import Path

import trace_events
import trace_replay
import trace_writer as tw


# ---------------------------------------------------------------------------
# Helpers — build a realistic recorded trace dir via TraceWriter
# ---------------------------------------------------------------------------


def _build_recorded_trace(design_dir: Path, slots: list[dict]) -> Path:
    """Write a recorded trace dir using TraceWriter.

    Args:
        design_dir: Parent directory for the trace (TraceWriter creates
                    design_dir/.trace/<run-id>/).
        slots: List of dicts with keys: slot, attempt, envelope.
               Each slot's envelope is written via write_slot_record.

    Returns:
        The run directory (design_dir/.trace/<run-id>/).
    """
    writer = tw.TraceWriter(design_dir, args={"mode": "record", "slug": "canary-test"})
    with writer:
        for slot_spec in slots:
            slot_name = slot_spec["slot"]
            attempt = slot_spec["attempt"]
            envelope = slot_spec["envelope"]
            inv_id = trace_events.invocation_id(slot_name, attempt)
            writer.emit(
                trace_events.SLOT_ENTER,
                invocation_id=inv_id,
                payload={"slot": slot_name},
            )
            writer.emit(
                trace_events.DISPATCH,
                invocation_id=inv_id,
                payload={"slot": slot_name, "attempt": attempt},
            )
            writer.write_slot_record(inv_id, envelope)
            writer.emit(
                trace_events.RETURN,
                invocation_id=inv_id,
                payload={
                    "status": envelope.get("status"),
                    "verdict": envelope.get("verdict"),
                },
            )
            writer.emit(
                trace_events.SLOT_EXIT,
                invocation_id=inv_id,
                payload={},
            )
    return writer._run_dir


def _drive_replay(recorded_dir: Path, design_dir: Path) -> Path:
    """Drive a replay through ReplayCache.resolve into a new TraceWriter dir.

    No live model/MCP/git/gh calls — pure cache reads.

    Args:
        recorded_dir: The recorded trace run directory to replay.
        design_dir:   Parent directory for the replay trace output.

    Returns:
        The replay run directory (design_dir/.trace/<replay-run-id>/).
    """
    cache = trace_replay.load(recorded_dir)
    replay_writer = tw.TraceWriter(
        design_dir, args={"mode": "replay", "recorded": str(recorded_dir)}
    )
    with replay_writer:
        for inv_id, envelope in cache._slots.items():
            # Parse slot name and attempt from invocation_id (format: "slot#attempt")
            slot_name, attempt_str = inv_id.rsplit("#", 1)
            attempt = int(attempt_str)
            replay_writer.emit(
                trace_events.SLOT_ENTER,
                invocation_id=inv_id,
                payload={"slot": slot_name},
            )
            # resolve() — no live call; strict=True (default)
            resolved = cache.resolve(slot_name, attempt)
            replay_writer.write_slot_record(inv_id, resolved)
            replay_writer.emit(
                trace_events.RETURN,
                invocation_id=inv_id,
                payload={
                    "status": resolved.get("status"),
                    "verdict": resolved.get("verdict"),
                },
            )
            replay_writer.emit(
                trace_events.SLOT_EXIT,
                invocation_id=inv_id,
                payload={},
            )
    return replay_writer._run_dir


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_CANARY_SLOTS = [
    {
        "slot": "design-audit",
        "attempt": 1,
        "envelope": {"verdict": "pass", "status": "ok", "artifact_path": "/x/design.md"},
    },
    {
        "slot": "plan",
        "attempt": 1,
        "envelope": {"verdict": "minor-only", "status": "ok", "artifact_path": "/x/plan.md"},
    },
    {
        "slot": "phase-implement",
        "attempt": 1,
        "envelope": {"verdict": "pass", "status": "ok", "artifact_path": "/x/src.py"},
    },
]


# ---------------------------------------------------------------------------
# Task 6.4: Record→replay round-trip canary
# ---------------------------------------------------------------------------


class TestRoundtripCanary:
    """Task 6.4 — round-trip canary: diff(recorded, replay) == [] on clean run;
    mutated verdict makes diff non-empty (tripwire).
    """

    def test_roundtrip_canary(self, tmp_path):
        """Green canary: replay is faithful to the recording — diff returns []."""
        recorded_dir = _build_recorded_trace(tmp_path / "rec", _CANARY_SLOTS)
        replay_dir = _drive_replay(recorded_dir, tmp_path / "rep")
        result = trace_replay.diff(recorded_dir, replay_dir)
        assert result == [], (
            f"Round-trip canary failed — diff is non-empty: {result!r}"
        )

    def test_roundtrip_canary_tripwire(self, tmp_path):
        """Tripwire: mutating a recorded slot verdict makes diff non-empty."""
        recorded_dir = _build_recorded_trace(tmp_path / "rec", _CANARY_SLOTS)
        replay_dir = _drive_replay(recorded_dir, tmp_path / "rep")

        # Deliberately mutate one slot verdict in the REPLAY dir
        inv_id = trace_events.invocation_id("design-audit", 1)
        slot_path = replay_dir / f"slot-{inv_id}.json"
        envelope = json.loads(slot_path.read_text(encoding="utf-8"))
        envelope["verdict"] = "major"  # was "pass"
        slot_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")

        # Now diff should be non-empty — the tripwire fires
        result = trace_replay.diff(recorded_dir, replay_dir)
        assert len(result) > 0, (
            "Tripwire did not fire: diff returned [] even after verdict mutation"
        )

    def test_roundtrip_all_slots_present(self, tmp_path):
        """All recorded slots appear in the replay trace."""
        recorded_dir = _build_recorded_trace(tmp_path / "rec", _CANARY_SLOTS)
        replay_dir = _drive_replay(recorded_dir, tmp_path / "rep")
        replay_cache = trace_replay.load(replay_dir)
        for spec in _CANARY_SLOTS:
            inv_id = trace_events.invocation_id(spec["slot"], spec["attempt"])
            assert replay_cache.has(inv_id), (
                f"Slot {inv_id!r} missing from replay trace"
            )

    def test_roundtrip_resolve_returns_correct_envelope(self, tmp_path):
        """Each resolved envelope matches the original recorded slot data."""
        recorded_dir = _build_recorded_trace(tmp_path / "rec", _CANARY_SLOTS)
        cache = trace_replay.load(recorded_dir)
        for spec in _CANARY_SLOTS:
            resolved = cache.resolve(spec["slot"], spec["attempt"])
            assert resolved["verdict"] == spec["envelope"]["verdict"]
            assert resolved["status"] == spec["envelope"]["status"]

    def test_roundtrip_replay_dir_is_distinct(self, tmp_path):
        """The replay trace runs into a different dir than the original."""
        recorded_dir = _build_recorded_trace(tmp_path / "rec", _CANARY_SLOTS)
        replay_dir = _drive_replay(recorded_dir, tmp_path / "rep")
        assert recorded_dir != replay_dir

    def test_roundtrip_single_slot(self, tmp_path):
        """Canary works with a single slot — minimal case."""
        slots = [{"slot": "design", "attempt": 1,
                  "envelope": {"verdict": "pass", "status": "ok"}}]
        recorded_dir = _build_recorded_trace(tmp_path / "rec", slots)
        replay_dir = _drive_replay(recorded_dir, tmp_path / "rep")
        result = trace_replay.diff(recorded_dir, replay_dir)
        assert result == []

    def test_roundtrip_canary_meta_json_present(self, tmp_path):
        """Both recorded and replay dirs have a valid meta.json."""
        recorded_dir = _build_recorded_trace(tmp_path / "rec", _CANARY_SLOTS)
        replay_dir = _drive_replay(recorded_dir, tmp_path / "rep")
        for d in (recorded_dir, replay_dir):
            meta_path = d / "meta.json"
            assert meta_path.exists(), f"meta.json missing in {d}"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta["v"] == trace_events.TRACE_SCHEMA_VERSION
