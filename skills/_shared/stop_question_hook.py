"""stop_question_hook.py — Stop hook: a prose question for the operator is routed once.

design: seat-escalate-first 3.2 (Phase 3 §Stop-hook contract). When a session's turn ends,
the hook takes the turn's last assistant text and asks `prose_question.question_text` whether
it ends in a question for the operator. If it does and the session is gated — a design run
past `design` (`escalate_first_hook._scope`) or the seat (`seat_scope.is_seat`), both on the
project root — it returns ONE `{"decision": "block", "reason": …}` naming the route: a run
→ `skills/_shared/escalation.md` §Run.

design: seat-scope-interactive-questions 1.4 (B5) — a seat question is classified over its
span: **run-bound** when the last 16 non-blank lines carry a `ruling:` line or the question
block (`prose_question.question_block`) names a live run (`seat_scope.run_named`) — routed to
`/tp-escalate` from the base checkout — and **operator-direct** otherwise, which is told to
ask the question in an `AskUserQuestion` card instead. Nothing else of the window is read.

Nothing is returned (the turn ends) under `stop_hook_active` (never block twice in a row),
for a `claude -p` child (`TP_CHILD_SESSION=1`, set by `child_spawn.cmd_start`), for a
non-question, for a message carrying an allowed `seat-allow: <kind>` line, for an ungated
session, and on any error (one stderr line, fail-open like `escalate_first_hook.run`).
The reason never teaches the `seat-allow:` tag; only a message that already carries one
with an unknown kind is told that kind is not allowed. Always exits 0. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SHARED = os.path.dirname(os.path.abspath(__file__))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import escalate_first_hook  # noqa: E402
import prose_question  # noqa: E402
import seat_scope  # noqa: E402
from project_root import find_project_root  # noqa: E402

CHILD_SESSION_ENV = "TP_CHILD_SESSION"  # mirrors child_spawn_ops.CHILD_SESSION_ENV
DOC = escalate_first_hook.DOC
_TAGGED = re.compile(r"(?m)^seat-allow:[ \t]*(\S+)[ \t]*$")
_KIND_MAX = 40


def _fail(exc):
    print("stop-question: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    return "", 0


def _joined(content):
    """The text of one assistant message's `content` (a string, or a list of blocks)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = [b["text"] for b in content
             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
    return "\n".join(parts) if parts else None


def _transcript_text(path):
    """The text of the turn's trailing `assistant` lines of the transcript JSONL, else None.

    One assistant message is often split over several lines (a text line, then a tool_use
    line), so the text blocks of every assistant line after the last `user` line are joined.
    """
    tail = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                kind = entry.get("type") if isinstance(entry, dict) else None
                if kind == "user":
                    tail = []
                elif kind == "assistant":
                    message = entry.get("message")
                    text = _joined(message.get("content")) if isinstance(message, dict) else None
                    if text:
                        tail.append(text)
    except OSError:
        return None
    return "\n".join(tail) or None


def _text(payload):
    """The turn's final assistant text: the payload field, else the transcript's last text."""
    message = payload.get("last_assistant_message")
    if isinstance(message, str):
        return message
    path = payload.get("transcript_path")
    return _transcript_text(path) if isinstance(path, str) and path else None


def _kind(root, env):
    """"run", "seat", or None when the session at `root` is not gated."""
    if escalate_first_hook._scope(root, env) is not None:
        return "run"
    return "seat" if seat_scope.is_seat(root, env) else None


def _run_bound(root, stripped) -> bool:
    """True when the seat question is run-bound (B3): the detector's 16-line window carries
    a `ruling:` line, or the question block names a live run. Nothing else is read."""
    window = "\n".join(text for _, text in prose_question._lines(stripped, 16))
    if escalate_first_hook._TAG.search(window):
        return True
    return seat_scope.run_named(root, prose_question.question_block(stripped)) is not None


def _reason(summary, kind, text, bound=True):
    head = ('stop-question: your turn ended on a question for the operator ("%s") — '
            "never ask it as prose;" % summary)
    if kind == "run":
        route = (" route it through %s §Run, the Design run paragraph: open no card; write the "
                 "ruling with `ruling_cli.py ask` (skip it for a ruling you already hold), then "
                 "run `ruling_cli.py wait --id <id>`." % DOC)
    elif bound:
        route = (' from the base checkout, run `/tp-escalate <slug|seat> --question '
                 '"<question>"`.')
    else:
        route = " ask it in an `AskUserQuestion` card (recommended option first) instead."
    tagged = _TAGGED.search(text)
    unknown = " `%s` is not an allowed kind." % tagged.group(1)[:_KIND_MAX] if tagged else ""
    return head + route + unknown


def run(payload, env=None):
    """(stdout, rc) for one Stop payload; allow = ("", 0). Fail-open."""
    try:
        env = os.environ if env is None else env
        if env.get(CHILD_SESSION_ENV) == "1" or payload.get("stop_hook_active"):
            return "", 0
        text = _text(payload)
        if text is None or seat_scope.allowed(text):
            return "", 0
        # A `seat-allow:` line of an unknown kind is a tag, not prose: the question above it counts.
        stripped = _TAGGED.sub("", text)
        summary = prose_question.question_text(stripped)
        if summary is None:
            return "", 0
        cwd = payload.get("cwd") or os.getcwd()
        root = str(find_project_root(Path(cwd)) or cwd)
        kind = _kind(root, env)
        if kind is None:
            return "", 0
        bound = kind == "run" or _run_bound(root, stripped)
        reason = _reason(summary, kind, text, bound)
        return json.dumps({"decision": "block", "reason": reason}), 0
    except Exception as exc:
        return _fail(exc)


def check_manifest(path) -> int:
    """0 when `path` registers this hook as a `Stop` entry, else 1."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        print("stop-question: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    for e in (cfg.get("hooks") or {}).get("Stop") or []:
        for hk in e.get("hooks") or []:
            if hk.get("type") == "command" and "stop_question_hook.py" in str(hk.get("command", "")):
                return 0
    print("stop-question: %s registers no Stop entry running stop_question_hook.py" % path,
          file=sys.stderr)
    return 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check-manifest":
        if len(sys.argv) != 3:
            print("stop-question: --check-manifest needs one manifest path", file=sys.stderr)
            return 1
        return check_manifest(sys.argv[2])
    raw = sys.stdin.read()
    try:
        out, code = run(json.loads(raw))
    except Exception as exc:
        out, code = _fail(exc)
    if out:
        print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
