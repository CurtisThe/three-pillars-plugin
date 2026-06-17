"""trace_index.py — CLI for walking a trace dir to a human-readable timeline.

Usage:
    python3 skills/_shared/trace_index.py <trace-dir> [--json] [--diff <other-dir>]

    <trace-dir>       Path to a trace run directory (contains meta.json +
                      trace.jsonl + slot-*.json).
    --json            Emit structured JSON instead of markdown.
    --diff <other>    Also render trace_replay.diff between <trace-dir> and <other>.

Exits:
    0  — success
    2  — bad/missing trace dir, missing meta.json, or no arguments

Default output: human-readable markdown timeline + per-slot verdict table.
--json opt-in: structured JSON (list of event objects + slots list).

Callable as main(argv) for tests or ``python3 trace_index.py`` directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import trace_events
import trace_replay

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USAGE = (
    "Usage: trace_index.py <trace-dir> [--json] [--diff <other-trace-dir>]\n"
    "\n"
    "  <trace-dir>   Path to a trace run directory (meta.json + trace.jsonl + slot-*.json)\n"
    "  --json        Emit structured JSON output instead of markdown\n"
    "  --diff <dir>  Render diff between <trace-dir> and <other-trace-dir>\n"
)

# Event types to include in the timeline (in preferred display order within a slot).
_TIMELINE_EVENTS = {
    trace_events.RUN_START,
    trace_events.SLOT_ENTER,
    trace_events.DISPATCH,
    trace_events.TOOL_CALL,
    trace_events.TOOL_RETURN,
    trace_events.RETURN,
    trace_events.SLOT_EXIT,
    trace_events.RUN_END,
}

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _load_trace_dir(trace_dir: Path) -> tuple[dict, list[dict], dict[str, dict]]:
    """Read trace dir and return (meta, events, slots).

    Args:
        trace_dir: Path to the trace run directory.

    Returns:
        (meta, events, slots) where events is a list of event dicts ordered
        by ts, and slots maps invocation_id -> clipped envelope.

    Raises:
        FileNotFoundError: If meta.json is missing.
    """
    meta_path = trace_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Read trace.jsonl (may be absent or empty for bare dirs)
    jsonl_path = trace_dir / "trace.jsonl"
    events: list[dict] = []
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # Sort by ts (ISO-8601 strings sort lexically)
    events.sort(key=lambda e: e.get("ts", ""))

    # Read slot records
    slots: dict[str, dict] = {}
    for slot_file in sorted(trace_dir.glob("slot-*.json")):
        stem = slot_file.stem  # "slot-design-audit#1"
        inv_id = stem[len("slot-"):]
        slots[inv_id] = json.loads(slot_file.read_text(encoding="utf-8"))

    return meta, events, slots


def _one_line_summary(event: dict) -> str:
    """Return a brief one-line summary for a timeline event."""
    etype = event.get("event_type", "?")
    payload = event.get("payload") or {}
    inv_id = event.get("invocation_id") or ""

    if etype == trace_events.RUN_START:
        return "run started"
    if etype == trace_events.RUN_END:
        status = payload.get("exit_status", "?")
        return f"run ended: {status}"
    if etype == trace_events.SLOT_ENTER:
        slot = payload.get("slot", inv_id.split("#")[0] if inv_id else "?")
        return f"enter {slot}"
    if etype == trace_events.SLOT_EXIT:
        slot = payload.get("slot", inv_id.split("#")[0] if inv_id else "?")
        return f"exit {slot}"
    if etype == trace_events.DISPATCH:
        slot = payload.get("slot", inv_id.split("#")[0] if inv_id else "?")
        return f"dispatch {slot}"
    if etype == trace_events.RETURN:
        verdict = payload.get("verdict", "?")
        status = payload.get("status", "?")
        return f"verdict={verdict} status={status}"
    if etype == trace_events.TOOL_CALL:
        tool = payload.get("tool", "?")
        inp = payload.get("input", "")
        summary = str(inp)[:40] if inp else ""
        return f"tool={tool} {summary}".rstrip()
    if etype == trace_events.TOOL_RETURN:
        tool = payload.get("tool", "?")
        return f"tool={tool} returned"
    return str(payload)[:60]


# ---------------------------------------------------------------------------
# Markdown rendering (Task 5.1)
# ---------------------------------------------------------------------------


def _render_timeline(events: list[dict]) -> str:
    """Render a markdown timeline from a list of trace events."""
    lines: list[str] = ["## Timeline", ""]
    lines.append("| ts | invocation_id | event | summary |")
    lines.append("|---|---|---|---|")
    for evt in events:
        etype = evt.get("event_type", "")
        if etype not in _TIMELINE_EVENTS:
            continue
        ts = evt.get("ts", "")
        inv_id = evt.get("invocation_id") or ""
        summary = _one_line_summary(evt)
        lines.append(f"| {ts} | {inv_id} | {etype} | {summary} |")
    lines.append("")
    return "\n".join(lines)


def _render_table(slots: dict[str, dict]) -> str:
    """Render a markdown per-slot verdict table from slot records."""
    lines: list[str] = ["## Slots", ""]
    lines.append("| slot | status | verdict | tokens |")
    lines.append("|---|---|---|---|")
    for inv_id in sorted(slots):
        env = slots[inv_id]
        status = env.get("status", "")
        verdict = env.get("verdict", "")
        tokens = env.get("tokens", "")
        lines.append(f"| {inv_id} | {status} | {verdict} | {tokens} |")
    lines.append("")
    return "\n".join(lines)


def _render_diff_markdown(diffs: list[dict]) -> str:
    """Render a diff list as markdown."""
    if not diffs:
        return "## Diff\n\nNo differences — trajectories are identical.\n"
    lines = ["## Diff", ""]
    lines.append("| slot | field | recorded | replayed |")
    lines.append("|---|---|---|---|")
    for entry in diffs:
        slot = entry.get("slot", "")
        field = entry.get("field", "")
        recorded = entry.get("recorded", "")
        replayed = entry.get("replayed", "")
        lines.append(f"| {slot} | {field} | {recorded} | {replayed} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON rendering (Task 5.2)
# ---------------------------------------------------------------------------


def _render_json(meta: dict, events: list[dict], slots: dict[str, dict]) -> Any:
    """Return a structured dict suitable for JSON serialisation."""
    return {
        "meta": meta,
        "timeline": [
            {
                "ts": e.get("ts"),
                "invocation_id": e.get("invocation_id"),
                "event_type": e.get("event_type"),
                "summary": _one_line_summary(e),
                "payload": e.get("payload"),
            }
            for e in events
            if e.get("event_type") in _TIMELINE_EVENTS
        ],
        "slots": [
            {
                "invocation_id": inv_id,
                "status": env.get("status"),
                "verdict": env.get("verdict"),
                "tokens": env.get("tokens"),
                "artifact_path": env.get("artifact_path"),
            }
            for inv_id, env in sorted(slots.items())
        ],
    }


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_argv(argv: list[str]) -> tuple[str | None, bool, str | None]:
    """Parse argv into (trace_dir, use_json, diff_dir).

    Returns (None, False, None) if argv is empty or malformed.
    """
    if not argv:
        return None, False, None

    args = list(argv)
    use_json = False
    diff_dir: str | None = None
    trace_dir: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            use_json = True
        elif arg == "--diff":
            i += 1
            if i < len(args):
                diff_dir = args[i]
            else:
                # --diff with no following value is a usage error
                import sys  # noqa: PLC0415
                sys.stderr.write("Error: --diff requires a following <other-trace-dir> argument\n\n")
                sys.stderr.write(_USAGE)
                sys.exit(2)
        elif not arg.startswith("--"):
            trace_dir = arg
        i += 1

    return trace_dir, use_json, diff_dir


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> None:
    """Entry point for the trace_index CLI.

    Args:
        argv: Command-line arguments (not including the script name).

    Exits with code 2 on bad/missing input.
    """
    trace_dir_str, use_json, diff_dir_str = _parse_argv(argv)

    if not trace_dir_str:
        sys.stderr.write(_USAGE)
        sys.exit(2)

    trace_dir = Path(trace_dir_str)

    # Validate trace dir
    if not trace_dir.is_dir():
        sys.stderr.write(
            f"Error: trace dir not found or not a directory: {trace_dir}\n\n{_USAGE}"
        )
        sys.exit(2)

    meta_path = trace_dir / "meta.json"
    if not meta_path.exists():
        sys.stderr.write(
            f"Error: {meta_path} not found — not a valid trace directory\n\n{_USAGE}"
        )
        sys.exit(2)

    # Load the trace dir
    try:
        meta, events, slots = _load_trace_dir(trace_dir)
    except Exception as exc:
        sys.stderr.write(f"Error loading trace dir: {exc}\n")
        sys.exit(2)

    if use_json:
        # Structured JSON output
        structured = _render_json(meta, events, slots)
        sys.stdout.write(json.dumps(structured, indent=2))
        sys.stdout.write("\n")
    else:
        # Markdown output (default)
        sys.stdout.write(_render_timeline(events))
        sys.stdout.write(_render_table(slots))

    # --diff rendering
    if diff_dir_str is not None:
        diff_dir = Path(diff_dir_str)
        try:
            diffs = trace_replay.diff(trace_dir, diff_dir)
        except Exception as exc:
            sys.stderr.write(f"Error computing diff: {exc}\n")
            sys.exit(2)

        if use_json:
            sys.stdout.write(json.dumps({"diff": diffs}, indent=2))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(_render_diff_markdown(diffs))


if __name__ == "__main__":
    main(sys.argv[1:])
