"""test_trace_writer_embedded.py — OD-8 embedded-token tests for TraceWriter.

Regression tests for the OD-8 leak: credential tokens embedded inside
non-sensitive string values (summary, notes, etc.) must NOT reach disk via
emit() or write_slot_record().

Kept separate from test_trace_writer.py to honour the 500-line / 50k-char
hard cap.
"""

from __future__ import annotations

import json
from pathlib import Path

import trace_writer


class TestEmitEmbeddedTokenAbsentOnDisk:
    """OD-8: embedded credential token in emit() payload must not reach disk."""

    def test_od8_emit_ghp_in_summary_absent_from_trace_jsonl(self, tmp_path):
        """ghp_ token inside a summary field must be absent from trace.jsonl."""
        token = "ghp_" + "x" * 36  # build at runtime to avoid gitleaks hook
        payload = {"summary": "worker used token " + token + " to push"}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            tw.emit("SLOT_EXIT", invocation_id="slot-a#1", payload=payload)
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            raw_bytes = jsonl_path.read_bytes()
        assert token.encode() not in raw_bytes, (
            "OD-8 VIOLATION: embedded ghp_ token found in trace.jsonl via emit()"
        )

    def test_od8_emit_sk_in_notes_absent_from_trace_jsonl(self, tmp_path):
        """sk- token inside a notes field must be absent from trace.jsonl."""
        token = "sk-" + "a" * 48
        payload = {"notes": "api key " + token + " was used"}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            tw.emit("DISPATCH", invocation_id="slot-b#2", payload=payload)
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            raw_bytes = jsonl_path.read_bytes()
        assert token.encode() not in raw_bytes, (
            "OD-8 VIOLATION: embedded sk- token found in trace.jsonl via emit()"
        )

    def test_od8_emit_akia_in_msg_absent_from_trace_jsonl(self, tmp_path):
        """AKIA token embedded inside a message field must be absent from trace.jsonl."""
        token = "AKIA" + "B" * 16
        payload = {"msg": "aws key " + token + " loaded"}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            tw.emit("SLOT_ENTER", invocation_id="slot-c#3", payload=payload)
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            raw_bytes = jsonl_path.read_bytes()
        assert token.encode() not in raw_bytes, (
            "OD-8 VIOLATION: embedded AKIA token found in trace.jsonl via emit()"
        )

    def test_od8_emit_surrounding_text_preserved_on_disk(self, tmp_path):
        """Surrounding non-secret text in the value is preserved on disk."""
        token = "ghp_" + "C" * 36
        payload = {"summary": "prefix " + token + " suffix"}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            tw.emit("RETURN", invocation_id="slot-d#1", payload=payload)
            jsonl_path = tmp_path / ".trace" / tw.run_id / "trace.jsonl"
            raw_text = jsonl_path.read_text()
        # Non-secret surrounding text must survive
        assert b"prefix" in raw_text.encode()
        assert b"suffix" in raw_text.encode()
        assert token.encode() not in raw_text.encode()


class TestWriteSlotRecordEmbeddedTokenAbsentOnDisk:
    """OD-8: embedded credential token in write_slot_record() must not reach disk."""

    def test_od8_slot_ghp_in_summary_absent(self, tmp_path):
        """ghp_ token in envelope summary must be absent from slot file on disk."""
        token = "ghp_" + "y" * 36  # runtime build avoids gitleaks hook
        envelope = {
            "verdict": "pass",
            "summary": "worker used token " + token + " to push",
            "notes": "some notes here",
        }
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-embedded#1"
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            raw_bytes = slot_path.read_bytes()
        assert token.encode() not in raw_bytes, (
            "OD-8 VIOLATION: embedded ghp_ token found in slot file via write_slot_record()"
        )

    def test_od8_slot_sk_in_notes_absent(self, tmp_path):
        """sk- token embedded in envelope notes field must be absent from slot file."""
        token = "sk-" + "b" * 24
        envelope = {
            "verdict": "minor-only",
            "notes": "key " + token + " expired",
        }
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-embedded#2"
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            raw_bytes = slot_path.read_bytes()
        assert token.encode() not in raw_bytes, (
            "OD-8 VIOLATION: embedded sk- token found in slot file via write_slot_record()"
        )

    def test_od8_slot_clean_fields_intact(self, tmp_path):
        """Non-secret fields in the envelope survive the redaction pass."""
        token = "ghp_" + "z" * 36
        envelope = {
            "verdict": "pass",
            "summary": "leaked " + token + " here",
            "tokens_used": 512,
        }
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-embedded#3"
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            data = json.loads(slot_path.read_text())
        assert data["verdict"] == "pass"
        assert data["tokens_used"] == 512
        assert token not in data["summary"]
        assert "[REDACTED:secret]" in data["summary"]

    def test_od8_slot_surrounding_text_preserved(self, tmp_path):
        """Surrounding non-secret text around an embedded token is kept on disk."""
        token = "ghp_" + "W" * 36
        envelope = {"summary": "before " + token + " after"}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            inv_id = "slot-embedded#4"
            tw.write_slot_record(inv_id, envelope)
            slot_path = tmp_path / ".trace" / tw.run_id / f"slot-{inv_id}.json"
            data = json.loads(slot_path.read_text())
        assert "before" in data["summary"]
        assert "after" in data["summary"]
        assert token not in data["summary"]
