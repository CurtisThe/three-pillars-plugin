"""escalate_first_hook.py — PreToolUse hook: an AskUserQuestion card in an
orchestrator-held design run must carry a `ruling: <id>` tag naming a ruling
file whose front `outcome` is `escalate`.

design: fable-escalation 5.1 — deny untagged / resolved / unknown; allow an
escalate ruling; scope gates; fail-open on any exception. Stdlib only.
(5.2 adds `--check-manifest`; 6.4 writes the named escalation.md.)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_SHARED = os.path.dirname(os.path.abspath(__file__))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import ruling_file  # noqa: E402

DOC = "skills/_shared/escalation.md"
_TAG = re.compile(r"(?m)^ruling: (%s)\s*$" % ruling_file.ID_RE.strip("^$"))
# Repo-local git env that would redirect `git -C <cwd>` at another repository.
_REPO_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR")


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "escalate-first: denied — " + reason}})


def _fail(exc):
    print("escalate-first: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    return "", 0


def _branch(cwd):
    env = {k: v for k, v in os.environ.items() if k not in _REPO_ENV}
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True, env=env, timeout=5)
    return out.stdout.strip() if out.returncode == 0 else None


def _scope(cwd, env):
    """The design slug when enforcement applies, else None (allow)."""
    if env.get("TP_DESIGN_RUN") != "1":
        return None
    branch = _branch(cwd)
    if not branch or not branch.startswith("tp/"):
        return None
    slug = branch[3:]
    base = Path(cwd) / "three-pillars-docs"
    lock_path = base / "tp-designs" / slug / "lock.json"
    if not lock_path.is_file():
        # Tier 5.6 archives the lock; Tiers 6-7 stay enforced from there.
        lock_path = base / "completed-tp-designs" / slug / "lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if not str(lock.get("owner", "")).startswith("orchestrator:"):
        return None
    if lock.get("phase") in (None, "design"):
        return None
    return slug


def _why(questions, root, slug) -> str:
    """"Reason to deny, or "" when every question carries an escalate ruling."""
    for q in questions:
        text = q.get("question") if isinstance(q, dict) else None
        if not isinstance(text, str):
            return "a question carries no text"
        m = _TAG.search(text)
        if not m:
            return "a question carries no `ruling: <id>` line"
        rid = m.group(1)
        path = ruling_file.find(root, rid)
        if path is None:
            return "ruling " + rid + " has no ruling file"
        front = ruling_file.parse(path).get("front", {})
        if front.get("slug") != slug:
            return "ruling " + rid + " belongs to another design"
        if front.get("outcome") != "escalate":
            return "ruling " + rid + " outcome is " + str(front.get("outcome"))
    return ""


def run(payload, env=None):
    """(stdout, rc) for one PreToolUse payload; allow = ("", 0). Fail-open."""
    try:
        env = os.environ if env is None else env
        if payload.get("tool_name") != "AskUserQuestion":
            return "", 0
        cwd = payload.get("cwd") or os.getcwd()
        slug = _scope(cwd, env)
        if slug is None:
            return "", 0
        questions = (payload.get("tool_input") or {}).get("questions") or []
        why = _why(questions, cwd, slug)
        if why:
            return _deny(why + "; route the question through " + DOC), 0
        return "", 0
    except Exception as exc:
        return _fail(exc)


def check_manifest(path) -> int:
    """0 when `path` registers this hook as an AskUserQuestion PreToolUse entry, else 1."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        print("escalate-first: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    for e in (cfg.get("hooks") or {}).get("PreToolUse") or []:
        if e.get("matcher") != "AskUserQuestion":
            continue
        for hk in e.get("hooks") or []:
            if hk.get("type") == "command" and "escalate_first_hook.py" in str(hk.get("command", "")):
                return 0
    print("escalate-first: %s registers no AskUserQuestion entry running "
          "escalate_first_hook.py" % path, file=sys.stderr)
    return 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check-manifest":
        if len(sys.argv) != 3:
            print("escalate-first: --check-manifest needs one manifest path", file=sys.stderr)
            return 1
        return check_manifest(sys.argv[2])
    raw = sys.stdin.read()
    try:
        out, code = run(json.loads(raw))
    except Exception as exc:
        print("escalate-first: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        out, code = "", 0
    if out:
        print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
