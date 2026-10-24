"""run_no_cards_hook.py — PreToolUse hook: a seat-launched design run opens no
AskUserQuestion card.

design: run-no-cards-hook Task 1.1 — a run told in prose to open no card opened
four (run-scratch-in-fence, 2026-10-23/24); a card stalls the run until the
operator presses a key, and the seat cannot answer one. Deny every card with a
reason naming the ruling-file route. Stdlib only; fail-open on any exception.
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

import autonomous_gate  # noqa: E402
import ruling_file  # noqa: E402

PREFIX = "run-no-cards"
_TAG = re.compile(r"(?m)^ruling: (%s)\s*$" % ruling_file.ID_RE.strip("^$"))
_CLI = 'python3 "$TP_ROOT"/skills/_shared/ruling_cli.py'
_DOC = "(skills/_shared/escalation.md §Design run)"
ASK_REASON = (
    "a design run (TP_DESIGN_RUN=1) opens no AskUserQuestion card; write the question with "
    + _CLI + " ask --scope <slug> --question <text> --option 'LABEL=DESCRIPTION' (2-4) "
    "--recommended LABEL [--kind <kind>], which prints the awaiting-operator line and the "
    "answer command, then run " + _CLI + " wait --id <id> " + _DOC)


def wait_reason(rid):
    return ("a design run opens no AskUserQuestion card; this card already names ruling "
            + rid + ", so write no new ruling: print `awaiting-operator: ruling " + rid
            + "`, then run " + _CLI + " wait --id " + rid
            + " and act on the label it prints " + _DOC)


def _tag_id(tool_input):
    if not isinstance(tool_input, dict):
        return None
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return None
    for q in questions:
        text = q.get("question") if isinstance(q, dict) else None
        if isinstance(text, str):
            m = _TAG.search(text)
            if m:
                return m.group(1)
    return None


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": PREFIX + ": denied — " + reason}})


def _fail(exc):
    print("%s: %s: %s" % (PREFIX, type(exc).__name__, exc), file=sys.stderr)
    return "", 0


def run(payload, env=None):
    """(stdout, rc) for one PreToolUse payload; allow = ("", 0). Fail-open."""
    try:
        env = os.environ if env is None else env
        if not isinstance(payload, dict):
            raise TypeError("payload is not an object")
        if payload.get("tool_name") != "AskUserQuestion":
            return "", 0
        if not autonomous_gate.seat_launched(env):
            return "", 0
        rid = _tag_id(payload.get("tool_input"))
        return _deny(wait_reason(rid) if rid else ASK_REASON), 0
    except Exception as exc:
        return _fail(exc)


def check_manifest(path) -> int:
    """0 when `path` registers this hook as an AskUserQuestion PreToolUse entry, else 1."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        print("%s: %s: %s" % (PREFIX, type(exc).__name__, exc), file=sys.stderr)
        return 1
    for e in (cfg.get("hooks") or {}).get("PreToolUse") or []:
        if e.get("matcher") != "AskUserQuestion":
            continue
        for hk in e.get("hooks") or []:
            if hk.get("type") == "command" and "run_no_cards_hook.py" in str(hk.get("command", "")):
                return 0
    print("%s: %s registers no AskUserQuestion entry running run_no_cards_hook.py"
          % (PREFIX, path), file=sys.stderr)
    return 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check-manifest":
        if len(sys.argv) != 3:
            print(PREFIX + ": --check-manifest needs one manifest path", file=sys.stderr)
            return 1
        return check_manifest(sys.argv[2])
    try:
        out, code = run(json.loads(sys.stdin.read()))
    except Exception as exc:
        print("%s: %s: %s" % (PREFIX, type(exc).__name__, exc), file=sys.stderr)
        out, code = "", 0
    if out:
        print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
