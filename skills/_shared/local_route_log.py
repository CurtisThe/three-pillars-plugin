"""local_route_log.py — window/entries/transition/render helpers for the
`[routing]` protocol entries in a design's decisions.md, plus the `append`
CLI, the one writer of those entries.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py)

Import direction: `local_route_log` → `local_route_check`, one way;
`local_route_check`'s CLI imports this module lazily (inside its handlers),
never at module level, so the two never import each other at import time.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

# `ROUTE_KEYS`: the `append` CLI's `route` projection; `parse_result`
# classifies a stdin check line; `REASONS` is re-exported. The one direction.
from local_route_check import parse_result, REASONS, ROUTE_KEYS  # noqa: E402,F401

CHECK_RE = (
    r"^### \[routing\] (run-start|phase \d+): "
    r"(none|unrouted|router-down|routed) -> (unrouted|router-down|routed)/([a-z-]+)$"
)
END_RE = r"^### \[routing\] end: (routing: .+)$"
FLOOR_RE = r"^\*\*Route floor\*\*: local->sonnet: (\S+)$"

_CHECK_RE = re.compile(CHECK_RE, re.M)
_END_RE = re.compile(END_RE, re.M)
_FLOOR_RE = re.compile(FLOOR_RE, re.M)
_BASE_URL_RE = re.compile(r"\*\*Base URL\*\*: (\S+)")

# Labels counted (and rendered) in a `summary_line` floor suffix — a lost,
# mangled or stale route. Other labels (e.g. `unrouted/no-base-url`, written
# for an ordinary unrouted run) appear in the window but are not counted.
_COUNTED_FLOOR_LABELS = {"missing-route", "malformed-route", "stale-route"}

_FLOOR_SENTENCE = "claude ladder: local rows start at sonnet; no local-rung tp-task-worker"

# The dd's per-reason Effect clause, joined onto the floor sentence as
# "<floor>; <clause>". `ok` is handled separately (no floor sentence at all);
# `no-base-url`/`non-loopback` have no clause (floor only).
_REASON_CLAUSE = {
    "not-tp-router": "the base URL answers, so the Claude rungs run",
    "schema-unsupported": "the base URL answers, so the Claude rungs run",
    "bad-status": "the base URL answers, so the Claude rungs run",
    "connect-refused": (
        "nothing is listening (router down or restarting); a session whose own "
        "traffic uses this base URL stalls on every rung; resume once the router is back"
    ),
    "timeout": (
        "no /health answer within 2 s (router busy or hung); if it is hung, "
        "every rung on this base URL stalls"
    ),
    "error": "the probe failed (see detail); suspected env mismatch or router fault",
}


def open_window(text: str) -> str:
    """The text after the last `END_RE` line; all of `text` when there is none."""
    matches = list(_END_RE.finditer(text))
    if not matches:
        return text
    end = matches[-1].end()
    if end < len(text) and text[end] == "\n":
        end += 1
    return text[end:]


def _base_url_after(window: str, pos: int) -> str | None:
    """The `**Base URL**` field on the line right after `pos` (`none` -> None;
    no such field, or no next line -> None)."""
    start = pos + 1 if pos < len(window) and window[pos] == "\n" else pos
    newline = window.find("\n", start)
    line = window[start:newline] if newline != -1 else window[start:]
    match = _BASE_URL_RE.search(line)
    if match is None:
        return None
    value = match.group(1)
    return None if value == "none" else value


def entries(text: str) -> list[dict]:
    """Check entries in the open window, in order: `{scope, state, reason,
    base_url}`. `base_url` is parsed from the `**Base URL**` field on the
    line after each heading (`none` -> None)."""
    window = open_window(text)
    result = []
    for match in _CHECK_RE.finditer(window):
        scope, _frm, state, reason = match.groups()
        result.append({
            "scope": scope,
            "state": state,
            "reason": reason,
            "base_url": _base_url_after(window, match.end()),
        })
    return result


def current_route(text: str) -> dict | None:
    """`{"state", "reason", "base_url"}` of the open window's last check
    entry, else `None` (no check entry in the open window, including right
    after an `end` line)."""
    window_entries = entries(text)
    if not window_entries:
        return None
    last = window_entries[-1]
    return {"state": last["state"], "reason": last["reason"], "base_url": last["base_url"]}


def transition(text: str, result: dict, scope: str) -> dict | None:
    """The one rule deciding whether this check yields a logged entry.

    `scope == "run-start"` always yields one: `from` is the window's current
    state, else `"none"`. Any other scope (`"phase N"`) yields one only when
    there is no current route yet (`current_route(text) is None`, so a
    full-design's first phase is the baseline) or `result["state"]` differs
    from the current route's state — a reason-only change (same state) is
    `None`.
    """
    current = current_route(text)
    frm = current["state"] if current is not None else "none"
    if scope != "run-start" and current is not None and result["state"] == current["state"]:
        return None
    return {"from": frm, "entry": render_entry(result, scope, frm)}


def _effect_text(reason: str) -> str:
    """The `**Effect**` text for `reason`, per the dd's table."""
    if reason == "ok":
        return "unchanged (the router decides each request)"
    clause = _REASON_CLAUSE.get(reason)
    if clause is not None:
        return f"{_FLOOR_SENTENCE}; {clause}"
    return _FLOOR_SENTENCE


def render_entry(result: dict, scope: str, frm: str) -> str:
    """Render the `[routing]` entry text for `result` at `scope`, transitioning
    from `frm`. Round-trips: the first line matches `CHECK_RE`."""
    base_url = result.get("base_url") or "none"
    ollama = result.get("ollama") or "n/a"
    return (
        f"### [routing] {scope}: {frm} -> {result['state']}/{result['reason']}\n"
        f"**Checked**: {result['checked_at']} · **Base URL**: {base_url} · "
        f"**Ollama**: {ollama} (info only)\n"
        f"**Effect**: {_effect_text(result['reason'])}"
    )


def _floor_suffix(window: str) -> str:
    """`; floor(<label>) x<N>` for each counted `FLOOR_RE` label in `window`,
    per label in first-appearance order (uncounted labels are ignored)."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for match in _FLOOR_RE.finditer(window):
        label = match.group(1)
        if label not in _COUNTED_FLOOR_LABELS:
            continue
        if label not in counts:
            counts[label] = 0
            order.append(label)
        counts[label] += 1
    return "".join(f"; floor({label}) x{counts[label]}" for label in order)


def summary_line(text: str) -> str:
    """Summarize the open window. All routed, no counted floor ->
    `routing: routed/ok`; otherwise `routing: <state>/<reason> -> claude
    ladder` for the first non-routed entry (`routed/ok` when every entry
    routed), `; last <state>/<reason>` when the last entry differs, plus the
    floor suffix. No check entry but a `FLOOR_RE` line (counted or not) ->
    `routing: unknown (no routing check logged) -> claude ladder` + suffix.
    Neither -> the last `END_RE` capture anywhere in `text`, else
    `routing: not checked`."""
    window = open_window(text)
    floor_suffix = _floor_suffix(window)
    window_entries = entries(text)
    if window_entries:
        all_routed = all(e["state"] == "routed" for e in window_entries)
        if all_routed:
            if not floor_suffix:
                return "routing: routed/ok"
            return "routing: routed/ok -> claude ladder" + floor_suffix
        first = next(e for e in window_entries if e["state"] != "routed")
        base = f"routing: {first['state']}/{first['reason']} -> claude ladder"
        last = window_entries[-1]
        if (last["state"], last["reason"]) != (first["state"], first["reason"]):
            base += f"; last {last['state']}/{last['reason']}"
        return base + floor_suffix
    if _FLOOR_RE.search(window):
        return "routing: unknown (no routing check logged) -> claude ladder" + floor_suffix
    end_matches = list(_END_RE.finditer(text))
    if end_matches:
        return end_matches[-1].group(1)
    return "routing: not checked"


def end_entry(text: str) -> str | None:
    """`"### [routing] end: " + summary_line(text)`, or `None` when the open
    window has neither a current route nor any `FLOOR_RE` line (nothing to
    close)."""
    if current_route(text) is None and not _FLOOR_RE.search(open_window(text)):
        return None
    return "### [routing] end: " + summary_line(text)


# ---------------------------------------------------------------------------
# The `append` CLI — the one mechanical writer of `[routing]` entries
# (Task 2.4; detailed-design.md §local_route_log.py → "`append` CLI")
# ---------------------------------------------------------------------------

SCHEMA_HEADER = "# Decisions log — schema v1\n"  # auto-mode.md §Schema version


def _route_projection(obj: dict) -> dict:
    """The `route` print: exactly the five `ROUTE_KEYS`, never `transition`/
    `ollama`/`detail`."""
    return {key: obj[key] for key in ROUTE_KEYS}


def append_entry(decisions: Path, entry: str) -> None:
    """The public TRUE-append entry point (design: run-throughput Task 4.1).

    A thin wrapper around `_append_entry` — same flock + single `os.write` +
    schema-header handling. Any other module (e.g. `dispatch_log.py`) that
    needs to append a decisions.md line calls this, never opens the file
    itself."""
    return _append_entry(decisions, entry)


def _append_entry(decisions: Path, entry: str) -> None:
    """Append `entry` after a blank line: a TRUE append, never a rewrite.

    ONE `os.open(O_RDWR|O_CREAT|O_APPEND)` (no exists-check, no second open);
    an exclusive `flock` held from the size read through the ONE `os.write`
    decides: empty file -> `SCHEMA_HEADER` first, last byte not `\\n` -> one.
    So racing writers leave one header and every entry (lock pinned by
    test_local_route_log_lock.py; single open by test_local_route_log_race.py).
    A failed/short write raises `OSError`, never truncating prior bytes. Encoding
    precedes the open (an unencodable entry never creates the file); no mkdir."""
    block = ("\n" + entry + "\n").encode("utf-8")
    header = SCHEMA_HEADER.encode("utf-8")
    fd = os.open(decisions, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.fstat(fd).st_size
        if size == 0:
            payload = header + block
        elif os.pread(fd, 1, size - 1) != b"\n":
            payload = b"\n" + block
        else:
            payload = block
        written = os.write(fd, payload)
        if written != len(payload):
            raise OSError(errno.EIO, f"short write: {written} of {len(payload)} bytes")
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    return None


def _handle_append(decisions: Path, stdin: str) -> dict:
    """Classify one stdin line and append its entry. Never raises: the result
    dict always has exactly `route`, `line`, `appended`, `error`."""
    result = {"route": None, "line": None, "appended": False, "error": None}
    try:
        obj = json.loads(stdin)
    except ValueError:
        result["error"] = "stdin is not a JSON line"
        return result
    if not isinstance(obj, dict):
        result["error"] = "stdin JSON line is not an object"
        return result
    if "schema" in obj:  # a check line
        try:
            parsed = parse_result(obj)  # can raise TypeError on an unhashable reason
        except Exception:
            result["error"] = "check line is not a valid result v1"
            return result
        if parsed is None:
            result["error"] = "check line is not a valid result v1"
            return result
        result["route"] = _route_projection(parsed)  # five keys, whatever transition
        trans = obj.get("transition")
        if trans is None:
            return result  # no-op: no append, no file, no error
        if isinstance(trans, dict) and "error" in trans:
            result["error"] = f"transition error: {trans['error']}"
            return result
        entry = trans.get("entry") if isinstance(trans, dict) else None
        # `entry and …` guards an empty-string entry (an empty `splitlines()`
        # would raise IndexError); it is a clean "no entry", not a crash.
        if isinstance(entry, str) and entry and _CHECK_RE.match(entry.splitlines()[0]):
            try:
                _append_entry(decisions, entry)
            except (OSError, UnicodeError) as exc:
                result["error"] = f"append failed: {exc}"
            else:
                result["appended"] = True
        else:
            result["error"] = "transition carries no entry"
        return result
    if "line" in obj and "entry" in obj:  # an end line
        entry = obj["entry"]
        if entry is None:
            result["line"] = obj["line"]
            return result  # no-op: no append, no file, no error
        if not (isinstance(entry, str) and _END_RE.match(entry)):
            result["error"] = "end entry is not a valid end line"
            return result  # line stays null for an invalid stdin
        result["line"] = obj["line"]
        try:
            _append_entry(decisions, entry)
        except (OSError, UnicodeError) as exc:
            result["error"] = f"append failed: {exc}"
        else:
            result["appended"] = True
        return result
    result["error"] = "stdin is neither a check line nor an end line"
    return result


def main(argv: list[str] | None = None) -> int:
    """`append --decisions PATH` reads one JSON line on stdin (a `check` or an
    `end` line), appends its entry and prints one JSON line. Always exits 0:
    invalid stdin (incl. an empty `transition.entry`), a no-op transition or a
    failed write all print the result dict with `error` set and leave the file
    untouched (or uncreated) — so the CLI never crashes, whatever the stdin."""
    parser = argparse.ArgumentParser(description="append a [routing] entry")
    sub = parser.add_subparsers(dest="command", required=True)
    ap = sub.add_parser("append", help="append the stdin line's entry")
    ap.add_argument("--decisions", required=True, type=Path,
                    help="the design's decisions.md")
    args = parser.parse_args(argv)
    stdin = sys.stdin.read()
    try:
        result = _handle_append(args.decisions, stdin)
    except Exception as exc:  # noqa: BLE001 — the CLI always exits 0, never raises
        result = {"route": None, "line": None, "appended": False,
                  "error": f"append failed: {exc}"}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
