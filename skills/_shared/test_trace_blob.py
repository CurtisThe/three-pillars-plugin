"""test_trace_blob.py — Task 3.4: blob spillover above BLOB_THRESHOLD.

Separated from test_trace_writer.py to keep that file under the
500-line / 50k-char hard cap (no grandfather on new _shared files).

Tests:
  - Sub-threshold payloads stay inline.
  - Over-threshold payloads spill to blobs/<sha256>.
  - Hashing happens AFTER redaction (OD-8: secret absent from blob file).
"""

from __future__ import annotations

import hashlib
import json

import trace_writer


BLOB_THRESHOLD = trace_writer.BLOB_THRESHOLD  # 64 KB


class TestBlobSpill:
    """Task 3.4 — spill() threshold, blob files, redact-then-hash."""

    def test_sub_threshold_payload_stays_inline(self, tmp_path):
        """Payload below BLOB_THRESHOLD is returned unchanged (no spill)."""
        small = {"data": "x" * 10}  # well below 64 KB
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            result = tw.spill(small)
        # Result is the redacted payload directly (no $blob marker)
        assert "$blob" not in result

    def test_over_threshold_payload_returns_blob_marker(self, tmp_path):
        """Payload over BLOB_THRESHOLD is replaced by {"$blob": sha, "bytes": N}."""
        large_str = "A" * (BLOB_THRESHOLD + 1024)
        large = {"data": large_str}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            result = tw.spill(large)
        assert "$blob" in result, f"expected $blob marker, got keys: {list(result.keys())}"
        assert "bytes" in result

    def test_blob_file_is_written(self, tmp_path):
        """Blob content file exists under blobs/<sha256>."""
        large_str = "B" * (BLOB_THRESHOLD + 512)
        large = {"data": large_str}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
            result = tw.spill(large)
        blob_sha = result["$blob"]
        blob_path = tmp_path / ".trace" / rid / "blobs" / blob_sha
        assert blob_path.exists(), f"blob file not found at {blob_path}"

    def test_blob_sha_matches_content(self, tmp_path):
        """The $blob sha256 matches the actual file content."""
        large_str = "C" * (BLOB_THRESHOLD + 256)
        large = {"data": large_str}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
            result = tw.spill(large)
        blob_sha = result["$blob"]
        blob_path = tmp_path / ".trace" / rid / "blobs" / blob_sha
        raw = blob_path.read_bytes()
        expected_sha = hashlib.sha256(raw).hexdigest()
        assert blob_sha == expected_sha, (
            f"blob sha mismatch: stored={blob_sha!r}, actual={expected_sha!r}"
        )

    def test_blob_bytes_field_matches_serialized_size(self, tmp_path):
        """The bytes field in the inline marker equals the blob file size."""
        large_str = "D" * (BLOB_THRESHOLD + 128)
        large = {"data": large_str}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
            result = tw.spill(large)
        blob_sha = result["$blob"]
        blob_path = tmp_path / ".trace" / rid / "blobs" / blob_sha
        assert result["bytes"] == blob_path.stat().st_size

    # OD-8: redaction happens BEFORE hashing — secret absent from blob file
    def test_od8_secret_absent_from_blob_file(self, tmp_path):
        """OD-8 invariant: redact-then-hash means secret is NOT in the blob file.

        The secret is placed under a NON-sensitive key ('summary') so the test
        exercises value-level redaction through the spill() path.  Using a
        sensitive key like 'api_key' only proves key-level blanking; it cannot
        detect a write path that skips redact() entirely.
        """
        secret = "ghp_" + "T" * 36  # runtime construction avoids scanner
        # Build a large payload (over threshold) containing a secret in a non-sensitive key
        padding = "E" * BLOB_THRESHOLD  # ensure we exceed threshold
        large = {"summary": "used token " + secret + " here", "padding": padding}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
            result = tw.spill(large)
        assert "$blob" in result, "payload should have spilled to a blob"
        blob_sha = result["$blob"]
        blob_path = tmp_path / ".trace" / rid / "blobs" / blob_sha
        raw_bytes = blob_path.read_bytes()
        assert secret.encode() not in raw_bytes, (
            "OD-8 VIOLATION: secret found in blob file — redaction must happen before hashing"
        )

    # OD-8: separate spill() value-path test with non-sensitive key (new)
    def test_od8_spill_value_path_secret_absent(self, tmp_path):
        """OD-8 invariant: token in a non-sensitive value field absent from blob file."""
        secret = "ghs_" + "S" * 36  # ghs_ family; runtime build avoids scanner
        padding = "F" * BLOB_THRESHOLD
        large = {"notes": "clone url used token " + secret + " for auth", "padding": padding}
        with trace_writer.TraceWriter(tmp_path, args={}) as tw:
            rid = tw.run_id
            result = tw.spill(large)
        assert "$blob" in result, "payload should have spilled to a blob"
        blob_sha = result["$blob"]
        blob_path = tmp_path / ".trace" / rid / "blobs" / blob_sha
        raw_bytes = blob_path.read_bytes()
        assert secret.encode() not in raw_bytes, (
            "OD-8 VIOLATION: ghs_ token found in blob file after spill()"
        )
