"""PreToolUse hook entrypoint for the reviewer-delete-guard: stdin JSON, scope
check, scratch lookup, classify, deny JSON on stdout. Fails closed (deny) for the
scoped read-mostly agents only; everything else is allowed silently."""
from __future__ import annotations

import getpass
import glob
import json
import os
import re
import sys
import tempfile

READ_MOSTLY_AGENTS = {"tp-review-confirmer", "tp-review-confirmer-deep",
                      "tp-review-confirmer-medium",
                      "tp-readonly-auditor", "tp-impl-auditor", "tp-phase-checker"}
_TMP_BASE = "/tmp"  # nosec B108 — deny-list entry for scratch_for, never written to
_MAX_READ = 256 * 1024
_MARKER = re.compile(r"^TP_SCRATCH: (.+?)\s*$", re.M)
_RAW_AGENT = re.compile(r'"agent_type"\s*:\s*"([^"]*)"')
_AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")


def shared_roots():
    """Shared temp roots (and HOME, `/`) that are never a valid scratch."""
    roots = [os.sep, _TMP_BASE, tempfile.gettempdir(),
             os.path.join(_TMP_BASE, f"claude-{os.getuid()}"),
             os.path.join(_TMP_BASE, f"pytest-of-{getpass.getuser()}")]
    roots += [os.environ.get("TMPDIR"), os.environ.get("HOME"), os.path.expanduser("~")]
    return [os.path.realpath(r) for r in roots if r]


def _scoped(agent_type):
    return isinstance(agent_type, str) and agent_type.rsplit(":", 1)[-1] in READ_MOSTLY_AGENTS


def _crash(exc):
    name = "ImportError" if isinstance(exc, ImportError) else type(exc).__name__
    return _deny("reviewer-delete-guard: refused — crashed: %s: %s" % (name, exc))


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}})


def transcript_file(payload):
    """The subagent's own transcript (never the parent's), or None. Falls back
    only to `<dirname(transcript_path)>/*/subagents/agent-<id>.jsonl`: one
    project dir, never a config-wide search."""
    tp, sid, aid = (payload.get(k) for k in ("transcript_path", "session_id", "agent_id"))
    if not (isinstance(tp, str) and isinstance(sid, str) and isinstance(aid, str)
            and tp and sid and _AGENT_ID.fullmatch(aid)):
        return None
    base = os.path.dirname(tp)
    path = os.path.join(base, sid, "subagents", f"agent-{aid}.jsonl")
    if os.path.isfile(path):
        return path
    hits = glob.glob(os.path.join(glob.escape(base), "*", "subagents", f"agent-{aid}.jsonl"))
    return hits[0] if len(hits) == 1 else None


def extract_marker(text):
    """The first `TP_SCRATCH: /abs` line's path, else None."""
    m = _MARKER.search(text or "")
    if not m or not os.path.isabs(m.group(1)):
        return None
    return m.group(1)


def _first_user_text(path):
    with open(path, "rb") as fh:
        data = fh.read(_MAX_READ).decode("utf-8", "replace")
    for line in data.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "user":
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"
                             and isinstance(b.get("text"), str))
        return ""
    return ""


def scratch_for(payload):
    """Realpath of the agent's own scratch dir, or None when unknown/unsafe."""
    try:
        path = transcript_file(payload)
        if not path:
            return None
        marker = extract_marker(_first_user_text(path))
        if not marker or not os.path.isdir(marker):
            return None
        real = os.path.realpath(marker)
        for root in shared_roots():
            if real == root or root.startswith(real.rstrip(os.sep) + os.sep):
                return None
        return real
    except OSError:
        return None


def _refusal(command, reason, scratch):
    roots = [r for r in shared_roots() if os.path.basename(r).startswith(("claude-", "pytest-of-"))]
    return ("reviewer-delete-guard: refused %r — %s. Delete only inside %s; shared temp roots "
            "(%s, $TMPDIR) are off-limits — the orchestrator owns cleanup."
            % (command[:120], reason, scratch or "no scratch known", ", ".join(roots)))


def _lazy_scratch(payload):
    """A memoized scratch lookup: run only when a delete needs containment."""
    memo = []

    def get():
        if not memo:
            memo.append(scratch_for(payload))
        return memo[0]
    return get


def _known(get):
    try:
        return get()
    except Exception:  # the message only; the verdict already failed closed
        return None


def run(payload):
    """Return (stdout, exit_code) for one PreToolUse payload."""
    agent = payload.get("agent_type") if isinstance(payload, dict) else None
    if not agent or not _scoped(agent):
        return "", 0
    try:
        import reviewer_delete_guard
        import reviewer_delete_shell  # noqa: F401
        if payload.get("tool_name") != "Bash":
            return "", 0
        command = (payload.get("tool_input") or {}).get("command") or ""
        scratch = _lazy_scratch(payload)
        verdict = reviewer_delete_guard.classify(command, scratch=scratch,
                                                 cwd=payload.get("cwd"))
        if verdict.allowed:
            return "", 0
        return _deny(_refusal(command, verdict.reason, _known(scratch))), 0
    except Exception as exc:  # fail closed for the scoped set
        return _crash(exc), 0


def main():
    raw = sys.stdin.read()
    payload = None
    try:
        import reviewer_delete_shell  # noqa: F401
        import reviewer_delete_guard  # noqa: F401
        payload = json.loads(raw)
        out, code = run(payload)
    except Exception as exc:
        if isinstance(payload, dict):
            agent = payload.get("agent_type")
        else:
            m = _RAW_AGENT.search(raw)
            agent = m.group(1) if m else None
        if _scoped(agent):
            out, code = _crash(exc), 0
        else:
            out, code = "", 0
    if out:
        print(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
