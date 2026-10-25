"""run_no_cards_hook.py — PreToolUse hook: a seat-launched design run opens no
AskUserQuestion card.

design: run-no-cards-hook Task 1.1 — a run told in prose to open no card opened
four (run-scratch-in-fence, 2026-10-23/24); a card stalls the run until the
operator presses a key, and the seat cannot answer one. Deny every card with a
reason naming the ruling-file route. Stdlib only; fail-open on any exception.

design: followups-1024 item 5 — a `ruling: <id>` tag counts only for this run's
own `escalate` ruling, and every tag on the card is checked, not only the first.
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
import escalate_first_hook  # noqa: E402
import finalizer_ruling  # noqa: E402
import ruling_file  # noqa: E402
from project_root import find_project_root  # noqa: E402

PREFIX = "run-no-cards"
_TAG = re.compile(r"(?m)^ruling: (%s)\s*$" % ruling_file.ID_RE.strip("^$"))
_CLI = 'python3 "$TP_ROOT"/skills/_shared/ruling_cli.py'
_DOC = "(skills/_shared/escalation.md §Design run)"
ASK_REASON = (
    "a design run (TP_DESIGN_RUN=1) opens no AskUserQuestion card; write the question with "
    + _CLI + " ask --scope <slug> --question <text> --option 'LABEL=DESCRIPTION' (2-4) "
    "--recommended LABEL [--kind <kind>]"
    " (an operator-only question must pass its own kind, one of "
    + ", ".join(finalizer_ruling.OPERATOR_ONLY) + ", and stays the operator's)"
    ", which prints the awaiting-operator line and the "
    "answer command, then run " + _CLI + " wait --id <id> " + _DOC)


def wait_reason(*rids):
    named = "; ".join("print `awaiting-operator: ruling %s`, then run %s wait --id %s"
                      % (r, _CLI, r) for r in rids)
    return ("a design run opens no AskUserQuestion card; this card already names ruling "
            + ", ".join(rids) + ", so write no new ruling: " + named
            + " and act on the label it prints " + _DOC)


def _tags(tool_input):
    """(each question's first tag in order, duplicates dropped; count untagged)."""
    if not isinstance(tool_input, dict):
        return [], 1
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return [], 1
    ids, untagged = [], 0
    for q in questions:
        text = q.get("question") if isinstance(q, dict) else None
        m = _TAG.search(text) if isinstance(text, str) else None
        if m is None:
            untagged += 1
        elif m.group(1) not in ids:
            ids.append(m.group(1))
    return ids, untagged


def _check(root, rid, slug) -> str:
    """`""` when `rid` names this run's own escalate ruling, else why it does not."""
    path = ruling_file.find(root, rid)
    if path is None:
        return "no ruling file here"
    try:
        parsed = ruling_file.parse(path)
    except Exception:
        return "cannot be read"
    front = parsed.get("front") or {}
    if front.get("outcome") != "escalate":
        return "outcome is %s" % front.get("outcome", "-")
    if slug is not None and front.get("slug") != slug:
        return "belongs to another design"
    return ""


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
        cwd = payload.get("cwd") or os.getcwd()
        root = find_project_root(Path(cwd)) or cwd
        branch = escalate_first_hook._branch(cwd)
        slug = branch[3:] if isinstance(branch, str) and branch.startswith("tp/") else None
        ids, untagged = _tags(payload.get("tool_input"))
        checked = [(rid, _check(root, rid, slug)) for rid in ids]
        verified = [rid for rid, why in checked if not why]
        bad = ["ruling %s %s" % (rid, why) for rid, why in checked if why]
        if not verified:
            reason = "; ".join(bad) + ("; " if bad else "") + ASK_REASON
        else:
            reason = wait_reason(*verified)
            if bad or untagged:
                other = ([str(untagged) + " untagged question" if untagged else None] + bad)
                reason += ("; for every other question ("
                           + ", ".join(x for x in other if x) + "): " + ASK_REASON)
        return _deny(reason), 0
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
