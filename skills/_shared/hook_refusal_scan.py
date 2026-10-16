#!/usr/bin/env python3
"""hook_refusal_scan.py — the watchdog's fast catch of a `Red:` commit a hook refused.

design: red-commit-hook-refusal (Part 3, Fast catch). `refused_commit(records)` reads parsed
transcript records (the shape `attempt_scan._tool_calls` reads), pairs each Bash `git commit`
call with its `tool_result`, and returns the hook tail of the first call where a test hook
refused the attempt's first commit. A git-level failure, a fixable-in-attempt tail (a
`failure_class.CLASSES` tail pattern), a lint-only refusal, an `Implement:` commit, or any
earlier successful commit all mean "keep running" — None. Never raises. Stdlib only.
"""
from __future__ import annotations

import re

import failure_class
import red_commit_gate

__all__ = ["refused_commit"]

_GIT_COMMIT = re.compile(r"\bgit\b[^\n]*\bcommit\b")
_DRY_RUN = re.compile(r"--dry-run")
# `Red:` as the start of the commit message, not anywhere in the command.
_RED_SUBJECT = re.compile(r"(?:-m|--message)\s+['\"]?\s*Red:\s")

# git's own failures — the worker can retry these, so they are never a fast catch.
_GIT_OWN_FAILURES = (
    r"nothing (added )?to commit",
    r"no changes added to commit",
    r"Author identity unknown",
    r"Please tell me who you are",
    r"empty ident",
    r"index\.lock",
    r"^fatal: ",
    r"Aborting commit due to empty commit message",
    r"not a git repository",
    r"pathspec",
)

_TAIL_CHARS = '"`$\\'


def _blocks(rec: dict) -> list[dict]:
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
    content = msg.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _command(block: dict) -> str:
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    cmd = inp.get("command")
    return cmd if isinstance(cmd, str) else ""


def _result(block: dict) -> tuple[bool, str]:
    """`(is_error, text)` for one `tool_result` block; content may be a str or text blocks."""
    c = block.get("content")
    if isinstance(c, str):
        text = c
    elif isinstance(c, list):
        text = "".join(x.get("text", "") for x in c
                       if isinstance(x, dict) and isinstance(x.get("text"), str))
    else:
        text = ""
    return bool(block.get("is_error")), text


def _results(records: list[dict]) -> dict:
    out: dict = {}
    for rec in records:
        if not isinstance(rec, dict) or rec.get("type") != "user":
            continue
        for b in _blocks(rec):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                out[b["tool_use_id"]] = _result(b)
    return out


def _commit_calls(records: list[dict]) -> list[dict]:
    """`{id, command}` for each Bash `git commit` (never `--dry-run`), in stream order."""
    calls = []
    for rec in records:
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        for b in _blocks(rec):
            if b.get("type") != "tool_use" or b.get("name") != "Bash":
                continue
            cmd = _command(b)
            if _GIT_COMMIT.search(cmd) and not _DRY_RUN.search(cmd):
                calls.append({"id": b.get("id"), "command": cmd})
    return calls


def _fixable(text: str) -> bool:
    """The tail matches a `failure_class` class the ladder can fix inside the attempt."""
    return any(c.get("field") == "tail" and re.search(c["pattern"], text)
               for c in failure_class.CLASSES)


def _qualifies(command: str, text: str) -> bool:
    if not _RED_SUBJECT.search(command):
        return False  # an `Implement:` refusal never stops an attempt
    if any(re.search(p, text, re.MULTILINE) for p in _GIT_OWN_FAILURES):
        return False
    if _fixable(text):
        return False
    return bool(red_commit_gate.failing_paths(text))


def _tail(text: str) -> str:
    s = re.sub(r"\s+", " ", text)
    for ch in _TAIL_CHARS:
        s = s.replace(ch, "")
    return s.strip()[-300:]


def refused_commit(records) -> str | None:
    """The hook tail of the first refused `Red:` commit, else None. Never raises."""
    try:
        if not isinstance(records, list):
            return None
        results = _results(records)
        calls = _commit_calls(records)
        # Any commit call that did not error means the attempt recovered — the worker
        # contract is "fix the cause, retry the commit once" — so nothing to catch.
        if any(results.get(c["id"]) is not None and not results[c["id"]][0] for c in calls):
            return None
        for call in calls:
            res = results.get(call["id"])
            if res is None:
                continue  # unanswered call — nothing to catch yet
            is_error, text = res
            if _qualifies(call["command"], text):
                return _tail(text)
    except Exception:  # noqa: BLE001 - the watchdog must never crash on a malformed transcript
        return None
    return None
