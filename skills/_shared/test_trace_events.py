"""test_trace_events.py — Tests for trace_events module.

Split by task:
  - test_constants_frozen    (Task 2.1)
  - test_invocation_id       (Task 2.2)
  - test_event_builder       (Task 2.3)
"""

import re
from datetime import timezone

import trace_events


# ---------------------------------------------------------------------------
# Task 2.1: Schema version + frozen event-type constants
# ---------------------------------------------------------------------------

class TestConstantsFrozen:
    """Task 2.1 — TRACE_SCHEMA_VERSION and 8 event-type constants are exact."""

    def test_schema_version_is_one(self):
        assert trace_events.TRACE_SCHEMA_VERSION == "1"

    # Each test anchors the wire literal so a rename trips the test.

    def test_run_start_literal(self):
        assert trace_events.RUN_START == "RUN_START"

    def test_run_end_literal(self):
        assert trace_events.RUN_END == "RUN_END"

    def test_slot_enter_literal(self):
        assert trace_events.SLOT_ENTER == "SLOT_ENTER"

    def test_slot_exit_literal(self):
        assert trace_events.SLOT_EXIT == "SLOT_EXIT"

    def test_dispatch_literal(self):
        assert trace_events.DISPATCH == "DISPATCH"

    def test_return_literal(self):
        assert trace_events.RETURN == "RETURN"

    def test_tool_call_literal(self):
        assert trace_events.TOOL_CALL == "TOOL_CALL"

    def test_tool_return_literal(self):
        assert trace_events.TOOL_RETURN == "TOOL_RETURN"

    def test_all_eight_constants_present(self):
        expected = {
            "RUN_START", "RUN_END", "SLOT_ENTER", "SLOT_EXIT",
            "DISPATCH", "RETURN", "TOOL_CALL", "TOOL_RETURN",
        }
        actual = {
            trace_events.RUN_START,
            trace_events.RUN_END,
            trace_events.SLOT_ENTER,
            trace_events.SLOT_EXIT,
            trace_events.DISPATCH,
            trace_events.RETURN,
            trace_events.TOOL_CALL,
            trace_events.TOOL_RETURN,
        }
        assert actual == expected

    def test_constants_are_strings(self):
        for const in (
            trace_events.RUN_START, trace_events.RUN_END,
            trace_events.SLOT_ENTER, trace_events.SLOT_EXIT,
            trace_events.DISPATCH, trace_events.RETURN,
            trace_events.TOOL_CALL, trace_events.TOOL_RETURN,
        ):
            assert isinstance(const, str)

    def test_version_is_string(self):
        assert isinstance(trace_events.TRACE_SCHEMA_VERSION, str)


# ---------------------------------------------------------------------------
# Task 2.2: invocation_id determinism + attempt distinction
# ---------------------------------------------------------------------------

class TestInvocationId:
    """Task 2.2 — invocation_id is deterministic and attempt-distinguishing."""

    def test_basic_format(self):
        assert trace_events.invocation_id("design-audit", 2) == "design-audit#2"

    def test_attempt_zero(self):
        assert trace_events.invocation_id("slot-name", 0) == "slot-name#0"

    def test_attempt_one(self):
        assert trace_events.invocation_id("design-audit", 1) == "design-audit#1"

    def test_deterministic_across_calls(self):
        first = trace_events.invocation_id("design-audit", 2)
        second = trace_events.invocation_id("design-audit", 2)
        assert first == second

    def test_different_attempts_are_distinct(self):
        id1 = trace_events.invocation_id("design-audit", 1)
        id2 = trace_events.invocation_id("design-audit", 2)
        assert id1 != id2

    def test_different_slots_are_distinct(self):
        id1 = trace_events.invocation_id("slot-a", 1)
        id2 = trace_events.invocation_id("slot-b", 1)
        assert id1 != id2

    def test_returns_string(self):
        result = trace_events.invocation_id("any-slot", 3)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Task 2.3: event() builder shape + version/timestamp stamp
# ---------------------------------------------------------------------------

class TestEventBuilder:
    """Task 2.3 — event() returns the correct dict shape."""

    def _make_event(self, **kwargs):
        defaults = dict(
            event_type=trace_events.RETURN,
            invocation_id="design-audit#1",
            payload={"tokens": 100, "status": "ok"},
        )
        defaults.update(kwargs)
        return trace_events.event(**defaults)

    def test_returns_dict(self):
        evt = self._make_event()
        assert isinstance(evt, dict)

    def test_has_version_key(self):
        evt = self._make_event()
        assert "v" in evt

    def test_has_ts_key(self):
        evt = self._make_event()
        assert "ts" in evt

    def test_has_event_type_key(self):
        evt = self._make_event()
        assert "event_type" in evt

    def test_has_invocation_id_key(self):
        evt = self._make_event()
        assert "invocation_id" in evt

    def test_has_payload_key(self):
        evt = self._make_event()
        assert "payload" in evt

    def test_version_equals_schema_version(self):
        evt = self._make_event()
        assert evt["v"] == trace_events.TRACE_SCHEMA_VERSION

    def test_event_type_is_preserved(self):
        evt = self._make_event(event_type=trace_events.SLOT_ENTER)
        assert evt["event_type"] == trace_events.SLOT_ENTER

    def test_invocation_id_is_preserved(self):
        evt = self._make_event(invocation_id="my-slot#3")
        assert evt["invocation_id"] == "my-slot#3"

    def test_payload_is_preserved(self):
        payload = {"tokens": 42, "status": "done"}
        evt = self._make_event(payload=payload)
        assert evt["payload"] == payload

    def test_explicit_ts_is_honored(self):
        fixed_ts = "2024-01-15T12:00:00Z"
        evt = self._make_event(ts=fixed_ts)
        assert evt["ts"] == fixed_ts

    def test_default_ts_is_iso8601_utc_z(self):
        evt = self._make_event()
        ts = evt["ts"]
        # Must end with Z and have a T separator
        assert ts.endswith("Z"), f"ts must end with Z, got: {ts}"
        assert "T" in ts, f"ts must contain T separator, got: {ts}"
        # Parseable as ISO-8601 UTC
        # e.g. "2024-01-15T12:00:00.123456Z"
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            ts,
        ), f"ts does not look like ISO-8601: {ts}"

    def test_default_ts_is_a_string(self):
        evt = self._make_event()
        assert isinstance(evt["ts"], str)

    def test_invocation_id_none_allowed(self):
        evt = trace_events.event(
            event_type=trace_events.RUN_START,
            invocation_id=None,
            payload={},
        )
        assert evt["invocation_id"] is None

    def test_exact_keys(self):
        evt = self._make_event()
        assert set(evt.keys()) == {"v", "ts", "event_type", "invocation_id", "payload"}
