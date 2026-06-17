"""test_trace_replay.py — Tests for trace_replay module, Tasks 4.1–4.3.

Split by task:
  - TestLoadAndVersionGuard     (Task 4.1)
  - TestResolveHitMissPassthrough (Task 4.2)
  - TestDiff                    (Task 4.3)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import trace_events
import trace_replay


# ---------------------------------------------------------------------------
# Helpers — build minimal fixture trace dirs
# ---------------------------------------------------------------------------

def _write_meta(trace_dir: Path, v: str = trace_events.TRACE_SCHEMA_VERSION) -> None:
    """Write a minimal meta.json into a trace dir."""
    meta = {
        "v": v,
        "run_id": "TEST01",
        "start_ts": "2026-01-01T00:00:00Z",
        "args": {},
    }
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _write_slot(trace_dir: Path, invocation_id: str, envelope: dict) -> None:
    """Write slot-<invocation-id>.json into a trace dir."""
    slot_path = trace_dir / f"slot-{invocation_id}.json"
    slot_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")


def _make_trace_dir(tmp_path: Path, slots: dict | None = None, v: str | None = None) -> Path:
    """Create a minimal trace dir with meta.json and optional slot records.

    Args:
        tmp_path: Root temp dir (a unique subdir will be created inside).
        slots: Mapping of invocation_id -> envelope dict.
        v: Override schema version in meta.json (default = TRACE_SCHEMA_VERSION).
    """
    trace_dir = tmp_path / "trace"
    schema_v = v if v is not None else trace_events.TRACE_SCHEMA_VERSION
    _write_meta(trace_dir, v=schema_v)
    for inv_id, envelope in (slots or {}).items():
        _write_slot(trace_dir, inv_id, envelope)
    return trace_dir


# ---------------------------------------------------------------------------
# Task 4.1: load() + version guard
# ---------------------------------------------------------------------------


class TestLoadAndVersionGuard:
    """Task 4.1 — load() returns ReplayCache; TraceVersionMismatch on bad v."""

    def test_load_returns_replay_cache(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        cache = trace_replay.load(trace_dir)
        assert isinstance(cache, trace_replay.ReplayCache)

    def test_load_indexes_slot_records(self, tmp_path):
        slots = {
            "design-audit#1": {"verdict": "pass", "status": "ok", "tokens": 100},
            "plan#1": {"verdict": "minor-only", "status": "ok", "tokens": 200},
        }
        trace_dir = _make_trace_dir(tmp_path, slots=slots)
        cache = trace_replay.load(trace_dir)
        # Should have both invocation_ids indexed
        assert cache.has("design-audit#1")
        assert cache.has("plan#1")

    def test_load_reads_meta_json(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        cache = trace_replay.load(trace_dir)
        # Cache should expose metadata
        assert cache.meta["v"] == trace_events.TRACE_SCHEMA_VERSION

    def test_load_empty_slots_is_valid(self, tmp_path):
        """A trace dir with no slot records is valid (e.g., run_start only)."""
        trace_dir = _make_trace_dir(tmp_path, slots={})
        cache = trace_replay.load(trace_dir)
        assert isinstance(cache, trace_replay.ReplayCache)

    def test_load_raises_version_mismatch_on_wrong_v(self, tmp_path):
        """TraceVersionMismatch raised when meta.json.v != TRACE_SCHEMA_VERSION."""
        trace_dir = _make_trace_dir(tmp_path, v="999")
        with pytest.raises(trace_replay.TraceVersionMismatch):
            trace_replay.load(trace_dir)

    def test_version_mismatch_message_contains_version(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path, v="42")
        with pytest.raises(trace_replay.TraceVersionMismatch) as exc_info:
            trace_replay.load(trace_dir)
        msg = str(exc_info.value)
        # Should mention both the found version and the expected version
        assert "42" in msg or "version" in msg.lower()

    def test_load_reads_all_slot_files(self, tmp_path):
        """load() finds every slot-*.json in the dir."""
        slots = {
            "impl#1": {"verdict": "pass", "status": "ok"},
            "impl#2": {"verdict": "major", "status": "ok"},
            "design#1": {"verdict": "pass", "status": "ok"},
        }
        trace_dir = _make_trace_dir(tmp_path, slots=slots)
        cache = trace_replay.load(trace_dir)
        for inv_id in slots:
            assert cache.has(inv_id), f"expected {inv_id!r} in cache"

    def test_load_slot_envelope_content_preserved(self, tmp_path):
        """Envelope content round-trips through load unchanged."""
        env = {"verdict": "pass", "status": "ok", "tokens": 777, "artifact_path": "/x"}
        trace_dir = _make_trace_dir(tmp_path, slots={"slot-x#1": env})
        cache = trace_replay.load(trace_dir)
        resolved = cache.resolve("slot-x", 1, strict=False)
        assert resolved is not trace_replay.MISS
        assert resolved["verdict"] == "pass"
        assert resolved["tokens"] == 777


# ---------------------------------------------------------------------------
# Task 4.2: resolve() strict-abort default + passthrough sentinel
# ---------------------------------------------------------------------------


class TestResolveHitMissPassthrough:
    """Task 4.2 — resolve() hit; strict miss raises; strict=False returns MISS."""

    def _cache_with_slot(self, tmp_path: Path, inv_id: str, envelope: dict) -> "trace_replay.ReplayCache":
        trace_dir = _make_trace_dir(tmp_path, slots={inv_id: envelope})
        return trace_replay.load(trace_dir)

    def test_resolve_hit_returns_envelope(self, tmp_path):
        envelope = {"verdict": "pass", "status": "ok", "tokens": 42}
        cache = self._cache_with_slot(tmp_path, "design-audit#1", envelope)
        result = cache.resolve("design-audit", 1)
        assert result["verdict"] == "pass"
        assert result["tokens"] == 42

    def test_resolve_hit_attempt_distinction(self, tmp_path):
        """resolve uses slot+attempt to form invocation_id."""
        env1 = {"verdict": "pass", "status": "ok"}
        env2 = {"verdict": "major", "status": "ok"}
        trace_dir = _make_trace_dir(tmp_path, slots={
            "design#1": env1,
            "design#2": env2,
        })
        cache = trace_replay.load(trace_dir)
        r1 = cache.resolve("design", 1)
        r2 = cache.resolve("design", 2)
        assert r1["verdict"] == "pass"
        assert r2["verdict"] == "major"

    def test_resolve_miss_raises_by_default(self, tmp_path):
        """Default (strict=True): resolve on a miss raises ReplayCacheMiss."""
        trace_dir = _make_trace_dir(tmp_path, slots={})
        cache = trace_replay.load(trace_dir)
        with pytest.raises(trace_replay.ReplayCacheMiss):
            cache.resolve("nonexistent", 1)

    def test_resolve_miss_message_contains_invocation_id(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path, slots={})
        cache = trace_replay.load(trace_dir)
        with pytest.raises(trace_replay.ReplayCacheMiss) as exc_info:
            cache.resolve("my-slot", 3)
        msg = str(exc_info.value)
        assert "my-slot" in msg and "3" in msg

    def test_resolve_miss_strict_false_returns_miss_sentinel(self, tmp_path):
        """strict=False: resolve on a miss returns the MISS sentinel."""
        trace_dir = _make_trace_dir(tmp_path, slots={})
        cache = trace_replay.load(trace_dir)
        result = cache.resolve("nonexistent", 1, strict=False)
        assert result is trace_replay.MISS

    def test_resolve_miss_strict_false_does_not_raise(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path, slots={})
        cache = trace_replay.load(trace_dir)
        # Should not raise
        result = cache.resolve("missing", 99, strict=False)
        assert result is trace_replay.MISS

    def test_resolve_hit_strict_false_returns_envelope_not_sentinel(self, tmp_path):
        """strict=False on a HIT still returns the envelope, not MISS."""
        env = {"verdict": "pass", "status": "ok"}
        cache = self._cache_with_slot(tmp_path, "slot#1", env)
        result = cache.resolve("slot", 1, strict=False)
        assert result is not trace_replay.MISS
        assert result["verdict"] == "pass"

    def test_miss_sentinel_is_falsy_or_distinct(self):
        """MISS sentinel is a distinct, identifiable object."""
        # It must be identifiable via `is trace_replay.MISS`
        assert trace_replay.MISS is trace_replay.MISS  # identity check
        assert trace_replay.MISS != {"verdict": "pass"}

    def test_replay_cache_miss_error_message_format(self, tmp_path):
        """Error message format: 'replay-cache-miss {slot}#{attempt}'."""
        trace_dir = _make_trace_dir(tmp_path, slots={})
        cache = trace_replay.load(trace_dir)
        with pytest.raises(trace_replay.ReplayCacheMiss) as exc_info:
            cache.resolve("impl", 2)
        msg = str(exc_info.value)
        assert "replay-cache-miss" in msg
        assert "impl" in msg
        assert "2" in msg


# ---------------------------------------------------------------------------
# Task 4.3: diff() — empty on identical, structured on mismatch
# ---------------------------------------------------------------------------


class TestDiff:
    """Task 4.3 — diff() returns [] on match; structured diffs on mismatch."""

    def _two_dirs_identical(self, tmp_path: Path) -> tuple[Path, Path]:
        """Return two trace dirs with identical slot records."""
        slots = {
            "design-audit#1": {"verdict": "pass", "status": "ok", "artifact_path": "/x"},
            "plan#1": {"verdict": "minor-only", "status": "ok", "artifact_path": "/y"},
        }
        d1 = tmp_path / "recorded"
        d2 = tmp_path / "replay"
        _write_meta(d1)
        _write_meta(d2)
        for inv_id, env in slots.items():
            _write_slot(d1, inv_id, env)
            _write_slot(d2, inv_id, env)
        return d1, d2

    def test_diff_returns_empty_on_identical_trajectories(self, tmp_path):
        d1, d2 = self._two_dirs_identical(tmp_path)
        result = trace_replay.diff(d1, d2)
        assert result == []

    def test_diff_returns_list(self, tmp_path):
        d1, d2 = self._two_dirs_identical(tmp_path)
        result = trace_replay.diff(d1, d2)
        assert isinstance(result, list)

    def test_diff_verdict_mismatch_is_detected(self, tmp_path):
        """A changed verdict appears in the diff list."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "design-audit#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, inv_id, {"verdict": "major", "status": "ok"})
        result = trace_replay.diff(d1, d2)
        assert len(result) > 0

    def test_diff_status_mismatch_is_detected(self, tmp_path):
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "plan#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, inv_id, {"verdict": "pass", "status": "errored"})
        result = trace_replay.diff(d1, d2)
        assert len(result) > 0

    def test_diff_artifact_path_mismatch_is_detected(self, tmp_path):
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "impl#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "artifact_path": "/a"})
        _write_slot(d2, inv_id, {"verdict": "pass", "artifact_path": "/b"})
        result = trace_replay.diff(d1, d2)
        assert len(result) > 0

    def test_diff_entry_has_slot_field(self, tmp_path):
        """Each diff entry contains a 'slot' field."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "design-audit#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, inv_id, {"verdict": "major", "status": "ok"})
        result = trace_replay.diff(d1, d2)
        assert all("slot" in entry for entry in result)

    def test_diff_entry_has_field_name(self, tmp_path):
        """Each diff entry contains a 'field' identifying what diverged."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "plan#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, inv_id, {"verdict": "major", "status": "ok"})
        result = trace_replay.diff(d1, d2)
        assert all("field" in entry for entry in result)

    def test_diff_entry_has_recorded_and_replayed(self, tmp_path):
        """Each diff entry has 'recorded' and 'replayed' values."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "impl#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, inv_id, {"verdict": "major", "status": "ok"})
        result = trace_replay.diff(d1, d2)
        for entry in result:
            assert "recorded" in entry
            assert "replayed" in entry

    def test_diff_recorded_and_replayed_values_correct(self, tmp_path):
        """recorded/replayed values in diff match source data."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "design-audit#1"
        _write_slot(d1, inv_id, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, inv_id, {"verdict": "major", "status": "ok"})
        result = trace_replay.diff(d1, d2)
        verdict_diffs = [e for e in result if e.get("field") == "verdict"]
        assert len(verdict_diffs) == 1
        assert verdict_diffs[0]["recorded"] == "pass"
        assert verdict_diffs[0]["replayed"] == "major"

    def test_diff_no_false_positives_on_match(self, tmp_path):
        """Fields that match don't appear in the diff."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        inv_id = "plan#1"
        env = {"verdict": "pass", "status": "ok", "artifact_path": "/same"}
        _write_slot(d1, inv_id, env)
        _write_slot(d2, inv_id, env)
        result = trace_replay.diff(d1, d2)
        assert result == []

    def test_diff_multiple_slots_all_match(self, tmp_path):
        d1, d2 = self._two_dirs_identical(tmp_path)
        result = trace_replay.diff(d1, d2)
        assert result == []

    def test_diff_only_one_slot_differs(self, tmp_path):
        """Only the diverged slot appears in the diff."""
        d1 = tmp_path / "rec"
        d2 = tmp_path / "rep"
        _write_meta(d1)
        _write_meta(d2)
        slots_match = {
            "plan#1": {"verdict": "pass", "status": "ok"},
        }
        slot_diff = "impl#1"
        for inv_id, env in slots_match.items():
            _write_slot(d1, inv_id, env)
            _write_slot(d2, inv_id, env)
        _write_slot(d1, slot_diff, {"verdict": "pass", "status": "ok"})
        _write_slot(d2, slot_diff, {"verdict": "major", "status": "ok"})
        result = trace_replay.diff(d1, d2)
        slots_in_diff = {e["slot"] for e in result}
        assert slot_diff in slots_in_diff
        assert "plan#1" not in slots_in_diff
