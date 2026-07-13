"""test_trace_writer.py — Tests for trace_writer module, Tasks 3.1–3.5.

Split by task:
  - TestRunIdAndLayout           (Task 3.1)
  - TestEmitAppendAndArgsRedacted (Task 3.2 — OD-8 open-path on-disk assertion)
  - TestSlotRecordRedacted       (Task 3.3 — on-disk secret-absence assertion)
  - TestClosePathRedactedAndCounter (Task 3.5 — OD-8 close-path on-disk assertion)

Task 3.4 (blob spillover) lives in test_trace_blob.py to keep this file under
the 500-line / 50k-char hard cap (no grandfather on new _shared files).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

import trace_writer


# ---------------------------------------------------------------------------
# Task 3.1: stdlib ULID run_id() + run-dir layout on __enter__
# ---------------------------------------------------------------------------

class TestRunIdAndLayout:
    """Task 3.1 — run_id() + TraceWriter creates .trace/<run-id>/ + meta.json."""

    def test_run_id_returns_string(self):
        rid = trace_writer.run_id()
        assert isinstance(rid, str)

    def test_run_id_crockford_base32_charset(self):
        # Crockford base32 uses 0-9 A-H J-N P-T V-Z (no I L O U)
        rid = trace_writer.run_id()
        assert re.match(r"^[0-9A-HJKMNP-TV-Z]+$", rid), (
            f"run_id has invalid Crockford charset: {rid!r}"
        )

    def test_run_id_length(self):
        # ULID = 26 Crockford base32 characters
        rid = trace_writer.run_id()
        assert len(rid) == 26, f"expected 26 chars, got {len(rid)}: {rid!r}"

    def test_two_successive_run_ids_are_distinct(self):
        a = trace_writer.run_id()
        # Small sleep to ensure distinct ms-timestamp component
        time.sleep(0.002)
        b = trace_writer.run_id()
        assert a != b

    def test_run_ids_are_lexically_ordered_by_time(self):
        a = trace_writer.run_id()
        time.sleep(0.002)
        b = trace_writer.run_id()
        assert a < b, f"expected {a!r} < {b!r} (lexical order == time order)"

    def test_enter_creates_trace_run_dir(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            run_dir = tmp_path / ".trace" / tw.run_id
            assert run_dir.is_dir(), f"expected run dir at {run_dir}"

    def test_enter_writes_meta_json(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            meta_path = tmp_path / ".trace" / tw.run_id / "meta.json"
            assert meta_path.exists(), f"meta.json not found at {meta_path}"

    def test_meta_json_is_valid_json(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            meta_path = tmp_path / ".trace" / tw.run_id / "meta.json"
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_meta_json_has_run_id(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            meta_path = tmp_path / ".trace" / tw.run_id / "meta.json"
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert "run_id" in data
            assert data["run_id"] == tw.run_id

    def test_meta_json_has_start_ts(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            meta_path = tmp_path / ".trace" / tw.run_id / "meta.json"
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert "start_ts" in data


# ---------------------------------------------------------------------------
# Task 3.2: emit() jsonl append + meta.json open-path redaction of args
# ---------------------------------------------------------------------------

class TestEmitAppendAndArgsRedacted:
    """Task 3.2 — emit() appends jsonl; OD-8: args redacted before meta.json write."""

    def test_trace_jsonl_created_on_enter(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            assert jsonl_path.exists()

    def test_run_start_emitted_on_enter(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            assert len(lines) >= 1
            first = json.loads(lines[0])
            assert first["event_type"] == "RUN_START"

    def test_emit_appends_one_line_per_call(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            before = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            tw.emit("SLOT_ENTER", invocation_id="slot-a#1", payload={"slot": "a"})
            after = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            assert after == before + 1

    def test_emit_multiple_appends_grow_by_one_each(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            base = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            tw.emit("SLOT_ENTER", invocation_id="slot-a#1", payload={"x": 1})
            tw.emit("DISPATCH", invocation_id="slot-a#1", payload={"y": 2})
            final = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            assert final == base + 2

    def test_emitted_lines_are_valid_json(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            tw.emit("SLOT_ENTER", invocation_id="s#1", payload={"z": 3})
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                obj = json.loads(line)
                assert isinstance(obj, dict)

    def test_emitted_event_has_correct_shape(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            tw.emit("SLOT_ENTER", invocation_id="s#1", payload={"q": 99})
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            # Last line is the SLOT_ENTER we just emitted
            evt = json.loads(lines[-1])
            assert set(evt.keys()) >= {"v", "ts", "event_type", "invocation_id", "payload"}

    # OD-8 open-path: secret injected into args must be ABSENT from meta.json on disk
    def test_od8_args_secret_absent_from_meta_json(self, tmp_path):
        """OD-8 invariant: args routed through value-level redact before meta.json write.

        The secret is placed under a NON-sensitive key ('description') so that
        the test exercises value-level redaction, not key-level blanking.
        """
        secret = "ghp_" + "X" * 36  # built at runtime to avoid scanner
        # Non-sensitive key — only value-level redaction can catch this
        args = {"task_id": "design-audit", "description": "token " + secret + " used"}
        with trace_writer.TraceWriter(tmp_path, args=args) as tw:
            meta_path = tmp_path / ".trace" / tw.run_id / "meta.json"
            raw_bytes = meta_path.read_bytes()
        # The secret value must not appear literally in the file
        assert secret.encode() not in raw_bytes, (
            "OD-8 VIOLATION: secret from args found in meta.json on disk"
        )

    def test_clean_args_present_in_meta_json(self, tmp_path):
        """Non-secret args values survive in meta.json."""
        args = {"task_id": "design-audit", "mode": "record"}
        with trace_writer.TraceWriter(tmp_path, args=args) as tw:
            meta_path = tmp_path / ".trace" / tw.run_id / "meta.json"
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "args" in data
        assert data["args"]["task_id"] == "design-audit"


# ---------------------------------------------------------------------------
# Task 3.3: write_slot_record() with redaction round-trip
# ---------------------------------------------------------------------------

class TestSlotRecordRedacted:
    """Task 3.3 — write_slot_record() creates slot file; secret absent on disk."""

    def test_slot_file_created(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "design-audit#1"
            tw.write_slot_record(inv_id, {"verdict": "pass", "tokens": 100})
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            assert slot_path.exists(), f"slot file not found at {slot_path}"

    def test_slot_file_is_valid_json(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "design-audit#1"
            tw.write_slot_record(inv_id, {"verdict": "pass"})
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            data = json.loads(slot_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_slot_file_contains_clean_fields(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-x#2"
            envelope = {"verdict": "pass", "status": "ok", "tokens": 50}
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            data = json.loads(slot_path.read_text(encoding="utf-8"))
            assert data["verdict"] == "pass"
            assert data["tokens"] == 50

    # OD-8 on-disk: secret injected into clipped envelope must be ABSENT
    def test_od8_slot_secret_absent_on_disk(self, tmp_path):
        """OD-8 invariant: slot record passes through value-level redact before disk write.

        The secret is placed under a NON-sensitive key ('summary') so that the
        test exercises value-level redaction, not key-level blanking.  A test
        that puts the token under 'api_key' only proves key-level blanking works;
        it says nothing about whether the write path calls redact() at all.
        """
        secret = "ghp_" + "Y" * 36  # runtime construction avoids scanner
        envelope = {
            "verdict": "pass",
            "status": "ok",
            # Non-sensitive key — exercises value-level redaction through write path
            "summary": "worker used token " + secret + " to complete task",
        }
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-secret#1"
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            raw_bytes = slot_path.read_bytes()
        # The secret value must not appear literally in the file
        assert secret.encode() not in raw_bytes, (
            "OD-8 VIOLATION: secret found in slot record on disk"
        )

    def test_od8_slot_bearer_token_absent_on_disk(self, tmp_path):
        """Value-level secret in envelope payload also absent on disk."""
        token = "Bearer " + "Z" * 40
        envelope = {"verdict": "pass", "auth_header": token}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-bearer#1"
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            raw_bytes = slot_path.read_bytes()
        assert token.encode() not in raw_bytes, (
            "OD-8 VIOLATION: bearer token found in slot record on disk"
        )


# ---------------------------------------------------------------------------
# Task 3.5: __exit__ finalize + close-path redaction + redactions counter
# ---------------------------------------------------------------------------

class TestClosePathRedactedAndCounter:
    """Task 3.5 — __exit__ finalizes meta.json; OD-8 close-path; redactions sum."""

    def test_meta_json_has_end_ts_after_exit(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "end_ts" in data, "meta.json missing end_ts after __exit__"

    def test_meta_json_has_exit_status_after_exit(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "exit_status" in data

    def test_meta_json_has_redactions_counter(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "redactions" in data
        assert isinstance(data["redactions"], int)

    def test_run_end_emitted_on_exit(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
            jsonl_path = tmp_path / ".trace" / rid / "trace.jsonl"
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1])
        assert last["event_type"] == "RUN_END"

    def test_clean_exit_status_ok(self, tmp_path):
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["exit_status"] == "ok"

    # OD-8 close-path: secret injected into exit_status must be ABSENT from meta.json
    def test_od8_exit_status_secret_absent_from_meta_json(self, tmp_path):
        """OD-8 invariant: exit_status routed through redact before close-path write."""
        secret = "ghp_" + "W" * 36  # runtime construction avoids scanner
        tw = trace_writer.TraceWriter(tmp_path, args={})
        tw.__enter__()
        rid = tw.run_id
        # Inject secret as the exit status string
        tw._exit_status = secret  # force override before __exit__ finalizes
        tw.__exit__(None, None, None)
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        raw_bytes = meta_path.read_bytes()
        assert secret.encode() not in raw_bytes, (
            "OD-8 VIOLATION: secret in exit_status found in meta.json on disk"
        )

    def test_od8_exception_text_absent_from_meta_json(self, tmp_path):
        """OD-8: exception text containing secret not written to meta.json."""
        secret = "ghp_" + "V" * 36  # runtime construction avoids scanner
        try:
            with trace_writer.TraceWriter(tmp_path, args={}) as tw:
                rid = tw.run_id
                raise ValueError(f"Something went wrong with token {secret}")
        except ValueError:
            pass
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        raw_bytes = meta_path.read_bytes()
        assert secret.encode() not in raw_bytes, (
            "OD-8 VIOLATION: exception text secret found in meta.json on disk"
        )

    def test_redactions_counter_nonzero_when_secrets_present(self, tmp_path):
        """redactions counter is > 0 when secrets were redacted during the run.

        Uses a NON-sensitive key so the counter reflects value-level redaction,
        not key-level blanking.
        """
        secret = "ghp_" + "U" * 36  # runtime construction avoids scanner
        # Non-sensitive key forces counter increment via value-level path
        args = {"description": "credential " + secret + " in value"}
        with trace_writer.TraceWriter(tmp_path, args=args) as tw:
            rid = tw.run_id
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["redactions"] > 0, (
            "expected redactions > 0 when secret was present in args"
        )

    def test_redactions_counter_zero_when_clean(self, tmp_path):
        """redactions counter is 0 when no secrets were seen during the run."""
        args = {"task_id": "design-audit", "mode": "record"}
        with trace_writer.TraceWriter(tmp_path, args=args) as tw:
            rid = tw.run_id
        meta_path = tmp_path / ".trace" / rid / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["redactions"] == 0, (
            f"expected 0 redactions for clean run, got {data['redactions']}"
        )
