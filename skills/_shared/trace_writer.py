"""trace_writer.py — Trace-directory writer for the orchestrator record system.

Public API:
  BLOB_THRESHOLD : int
      Size in bytes above which a serialized payload is spilled to a blob file
      (default 64 KB).

  run_id() -> str
      Generate a ULID-shaped sortable string: 26 Crockford base32 characters
      (10 timestamp chars + 16 random chars). Stdlib-only; no external dep.

  class TraceWriter
      Context manager that owns one trace run directory.

      TraceWriter(design_dir: Path, run_id: str | None = None, args: dict = ())
          design_dir : parent dir; creates design_dir/.trace/<run-id>/.
          run_id     : override (useful in tests); generated if None.
          args       : invocation args dict — routed through redact() before
                       writing to meta.json (OD-8 open-path gate).

      __enter__ -> TraceWriter
          Creates run dir + blobs/ subdir, writes initial meta.json (args
          already redacted), emits RUN_START to trace.jsonl.

      emit(event_type, *, invocation_id=None, payload) -> None
          Redacts payload, builds event via trace_events.event, appends one
          JSON line to trace.jsonl.

      write_slot_record(invocation_id, clipped_envelope) -> None
          Redacts clipped_envelope, writes slot-<invocation-id>.json.

      spill(payload) -> dict
          Redact first, then measure serialized size. If over BLOB_THRESHOLD,
          hash via sha256, write to blobs/<sha>, return {"$blob": sha, "bytes": N}.
          Otherwise return the redacted payload as-is.

      __exit__(exc_type, exc_val, exc_tb) -> False
          Finalizes meta.json (end_ts, exit_status, redactions counter),
          emits RUN_END. exit_status / exception text routed through redact()
          (OD-8 close-path gate). Never suppresses exceptions.

  OD-8 invariant: EVERY write that touches disk passes through trace_filter.redact.
  meta.json is gated on BOTH paths (open: args; close: exit_status/exception).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import traceback
from pathlib import Path
from typing import Any

import trace_events
import trace_filter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOB_THRESHOLD: int = 64 * 1024  # 64 KB

# ---------------------------------------------------------------------------
# Crockford base32 encoder (ULID alphabet — no I L O U)
# ---------------------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _b32_encode(value: int, width: int) -> str:
    """Encode *value* as a Crockford base-32 string of exactly *width* chars."""
    chars: list[str] = []
    for _ in range(width):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


# ---------------------------------------------------------------------------
# run_id()
# ---------------------------------------------------------------------------


def run_id() -> str:
    """Return a 26-char Crockford base-32 ULID-shaped string.

    Layout: 10 chars timestamp (ms precision) + 16 chars random.
    Sortable lexically by generation time.
    """
    ts_ms = int(time.time() * 1000)  # 48-bit millisecond timestamp
    rand_bits = int.from_bytes(secrets.token_bytes(10), "big")  # 80 bits
    ts_part = _b32_encode(ts_ms, 10)
    rand_part = _b32_encode(rand_bits, 16)
    return ts_part + rand_part


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _redact_and_dump(value: Any) -> tuple[str, int]:
    """Redact value then return (json_line, redaction_count).

    Returns a single JSON line (no newline) and the total number of
    redactions made during the walk.
    """
    redacted, counts = trace_filter.redact_with_report(value)
    line = json.dumps(redacted, separators=(",", ":"))
    total = sum(counts.values())
    return line, total


# ---------------------------------------------------------------------------
# Deep text redactor — for multi-line exception text
# ---------------------------------------------------------------------------

# Tokenise on whitespace boundaries so embedded tokens can match per-word.
_SPLITTER = re.compile(r"(\s+)")


def _redact_text_deep(text: str) -> tuple[str, dict[str, int]]:
    """Redact a multi-line string token-by-token.

    Split on whitespace so credential tokens embedded inside traceback lines
    (e.g. "ValueError: ...token ghp_XXXX\\n") still trigger the per-word
    ^ghp_...$ patterns inside trace_filter.

    Returns (redacted_text, combined_counts).
    """
    parts = _SPLITTER.split(text)  # alternates: [word, ws, word, ws, ...]
    out: list[str] = []
    combined: dict[str, int] = {}
    for part in parts:
        if _SPLITTER.fullmatch(part):
            # Pure whitespace — keep as-is
            out.append(part)
        else:
            r, c = trace_filter.redact_with_report(part)
            out.append(r if isinstance(r, str) else str(r))
            for k, v in c.items():
                combined[k] = combined.get(k, 0) + v
    return "".join(out), combined


# ---------------------------------------------------------------------------
# TraceWriter
# ---------------------------------------------------------------------------


class TraceWriter:
    """Context manager that records a single trace run to disk.

    Every write that touches disk passes through trace_filter.redact (OD-8).
    """

    def __init__(
        self,
        design_dir: Path,
        *,
        run_id: str | None = None,  # noqa: F811 — shadows module-level run_id
        args: dict[str, Any] | None = None,
    ) -> None:
        self._design_dir = Path(design_dir)
        self.run_id: str = run_id if run_id is not None else globals()["run_id"]()
        self._args: dict[str, Any] = dict(args) if args else {}
        self._run_dir: Path | None = None
        self._jsonl_path: Path | None = None
        self._redactions_total: int = 0
        # Exposed so tests can inject before __exit__
        self._exit_status: str | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "TraceWriter":
        run_dir = self._design_dir / ".trace" / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "blobs").mkdir(exist_ok=True)
        self._run_dir = run_dir
        self._jsonl_path = run_dir / "trace.jsonl"

        # OD-8 open-path: redact args before writing meta.json
        redacted_args, counts = trace_filter.redact_with_report(self._args)
        self._redactions_total += sum(counts.values())

        meta = {
            "v": trace_events.TRACE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "start_ts": trace_events._utc_now_iso(),
            "args": redacted_args,
        }
        (run_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        # Emit RUN_START
        self.emit(trace_events.RUN_START, invocation_id=None, payload={})
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self._run_dir is None:
            return False  # __enter__ never ran

        # Determine exit_status string (OD-8 close-path: redact before disk).
        # Traceback text is split into lines so per-line secret patterns (e.g.
        # ^ghp_...$) can match individual lines rather than the full multi-line
        # block — a credential URL inside a traceback line must still be caught.
        if exc_val is not None:
            raw_status = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        elif self._exit_status is not None:
            raw_status = self._exit_status
        else:
            raw_status = "ok"

        # Redact the exception text word-by-word so that credential tokens
        # embedded inside traceback lines (e.g. "...with token ghp_XXXX...")
        # can still match the per-word ^ghp_...$ patterns in trace_filter.
        # We split on whitespace boundaries, redact each token, then rejoin,
        # preserving the original whitespace run between tokens.
        redacted_status, total_counts = _redact_text_deep(raw_status)
        self._redactions_total += sum(total_counts.values())

        # Emit RUN_END
        self.emit(
            trace_events.RUN_END,
            invocation_id=None,
            payload={"exit_status": redacted_status},
        )

        # Re-read meta.json, stamp end fields, write back
        meta_path = self._run_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["end_ts"] = trace_events._utc_now_iso()
        meta["exit_status"] = redacted_status
        meta["redactions"] = self._redactions_total
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return False  # never suppress exceptions

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def run_dir(self) -> Path | None:
        """Public read-only accessor for the active run directory (Path or None).

        Matches the pseudocode in record-replay.md which references
        ``replay_writer.run_dir``. Returns None before __enter__ is called.
        """
        return self._run_dir

    # ------------------------------------------------------------------
    # emit()
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        *,
        invocation_id: str | None = None,
        payload: dict[str, Any],
    ) -> None:
        """Redact payload, build event, append one line to trace.jsonl."""
        line, n = _redact_and_dump(payload)
        self._redactions_total += n
        redacted_payload = json.loads(line)

        evt = trace_events.event(
            event_type,
            invocation_id=invocation_id,
            payload=redacted_payload,
        )
        evt_line = json.dumps(evt, separators=(",", ":"))
        with self._jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(evt_line + "\n")

    # ------------------------------------------------------------------
    # write_slot_record()
    # ------------------------------------------------------------------

    def write_slot_record(
        self,
        invocation_id: str,
        clipped_envelope: dict[str, Any],
    ) -> None:
        """Redact envelope then write slot-<invocation-id>.json."""
        line, n = _redact_and_dump(clipped_envelope)
        self._redactions_total += n
        redacted = json.loads(line)
        slot_path = self._run_dir / f"slot-{invocation_id}.json"
        slot_path.write_text(json.dumps(redacted, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # spill()
    # ------------------------------------------------------------------

    def spill(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Redact-then-hash; spill to blobs/ if serialized size > BLOB_THRESHOLD.

        Returns:
            {"$blob": sha256_hex, "bytes": N}  if over threshold
            redacted_payload                    otherwise
        """
        line, n = _redact_and_dump(payload)
        self._redactions_total += n
        raw = line.encode("utf-8")

        if len(raw) <= BLOB_THRESHOLD:
            return json.loads(line)

        sha = hashlib.sha256(raw).hexdigest()
        blob_path = self._run_dir / "blobs" / sha
        blob_path.write_bytes(raw)
        return {"$blob": sha, "bytes": len(raw)}
