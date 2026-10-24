#!/usr/bin/env python3
"""salvage_digest.py — a compact digest of a failed worker attempt, for the next rung.

design: ladder-diagnose-and-size-pins (plan Task 1.3)

`digest(transcript, repo, base_sha, test_command=None)` returns `{test, files, calls}`:
the last Bash call that ran the task's test command (else any pytest call) with its
output tail (last 40 lines); every file touched since `base_sha` (committed, uncommitted
or untracked) as a `task_prompt_blocks.size_rows` row; the last 10 tool calls, oldest
first, as `{name, summary}`. A missing or unreadable transcript yields empty `test` and
`calls`, never an exception. Reads no process name. Stdlib only.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt_scan  # noqa: E402
import task_prompt_blocks  # noqa: E402
import transcript_tail  # noqa: E402

__all__ = ["digest", "TAIL_LINES", "LAST_CALLS"]

TAIL_LINES = 40
LAST_CALLS = 10
_SUMMARY_CHARS = 120


def _summary(call: dict) -> str:
    inp = call["input"]
    for key in ("command", "file_path", "path", "pattern", "description"):
        if isinstance(inp.get(key), str):
            text = inp[key]
            break
    else:
        text = ""
    return " ".join(text.split())[:_SUMMARY_CHARS]


def _test_part(calls: list[dict], results: dict, test_command: str | None) -> dict:
    def ran(c, needle):
        return c["name"] == "Bash" and needle in str(c["input"].get("command", ""))

    pick = None
    if test_command:
        pick = next((c for c in reversed(calls) if ran(c, test_command)), None)
    if pick is None:
        pick = next((c for c in reversed(calls) if ran(c, "pytest")), None)
    if pick is None:
        return {"command": "", "output_tail": ""}
    tail = results.get(pick["id"], "").splitlines()[-TAIL_LINES:]
    return {"command": str(pick["input"]["command"]), "output_tail": "\n".join(tail)}


def _git_lines(repo, *args) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln for ln in out.splitlines() if ln]


def _touched(repo, base_sha: str) -> list[str]:
    seen = _git_lines(repo, "diff", "--name-only", base_sha)
    seen += _git_lines(repo, "ls-files", "--others", "--exclude-standard")
    return sorted(set(seen))


def digest(transcript, repo, base_sha: str, test_command: str | None = None) -> dict:
    """The salvage digest; see the module docstring."""
    try:
        records = transcript_tail.read_records(transcript)
    except (OSError, TypeError, ValueError):
        records = []
    calls = attempt_scan._tool_calls(records)
    results = attempt_scan._tool_results(records)
    return {
        "test": _test_part(calls, results, test_command),
        "files": task_prompt_blocks.size_rows(_touched(repo, base_sha), repo),
        "calls": [{"name": c["name"], "summary": _summary(c)} for c in calls[-LAST_CALLS:]],
    }
