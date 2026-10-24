"""escalate_first_hook.py — PreToolUse hook: an AskUserQuestion card in an
orchestrator-held design run must carry a `ruling: <id>` tag naming a ruling
file whose front `outcome` is `escalate`.

design: fable-escalation 5.1 — deny untagged / resolved / unknown; allow an
escalate ruling; scope gates; fail-open on any exception. Stdlib only.
(5.2 adds `--check-manifest`; 6.4 writes the named escalation.md.)

design: seat-escalate-first 2.2 — the seat (`seat_scope.is_seat`) is gated too: a card
needs a `seat-allow: <kind>` line, or a `ruling: <id>` naming an UNANSWERED `escalate`
ruling of any slug whose question the card restates. A run's ruling is read from its
`tp/<slug>` worktree when the seat root has none (fleet-seat-drive-gaps 1.7).
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
import seat_scope  # noqa: E402
from project_root import find_project_root  # noqa: E402

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


def _seat_why(rid, parsed, text) -> str:
    """Seat-only checks on a tagged card: the ruling is unspent and the card restates it."""
    if ruling_file.answer_of(parsed) is not None:
        return "ruling " + rid + " is already answered"
    question = str(parsed.get("question", "")).strip()
    if not question or not _TAG.sub("", text, count=1).strip().startswith(question):
        return "the card does not restate the question of ruling " + rid
    return ""


def _slug_of(rid) -> str:
    """The scope of ruling id `rid`: the id minus its `-YYYYMMDD-hex6` tail."""
    return rid[:-16]


def _why(questions, root, slug) -> str:
    """Reason to deny, or "" when every question carries an escalate ruling.

    `slug=None` is the seat: an allow-listed card passes, any slug's ruling is accepted,
    and the ruling must be unanswered and restated by the card (`_seat_why`).
    """
    for q in questions:
        text = q.get("question") if isinstance(q, dict) else None
        if not isinstance(text, str):
            return "a question carries no text"
        if slug is None and seat_scope.allowed(text):
            continue
        m = _TAG.search(text)
        if not m:
            return "a question carries no `ruling: <id>` line"
        rid = m.group(1)
        path = ruling_file.find(root, rid)
        if path is None and slug is None:
            wt = seat_scope.worktree_of(root, _slug_of(rid))
            if wt and os.path.isdir(wt):
                path = ruling_file.find(wt, rid)
        if path is None:
            return "ruling " + rid + " has no ruling file"
        parsed = ruling_file.parse(path)
        front = parsed.get("front", {})
        if slug is not None and front.get("slug") != slug:
            return "ruling " + rid + " belongs to another design"
        if front.get("outcome") != "escalate":
            return "ruling " + rid + " outcome is " + str(front.get("outcome"))
        why = _seat_why(rid, parsed, text) if slug is None else ""
        if why:
            return why
    return ""


def run(payload, env=None):
    """(stdout, rc) for one PreToolUse payload; allow = ("", 0). Fail-open."""
    try:
        env = os.environ if env is None else env
        if payload.get("tool_name") != "AskUserQuestion":
            return "", 0
        cwd = payload.get("cwd") or os.getcwd()
        slug = _scope(cwd, env)
        if slug is None and not seat_scope.is_seat(cwd, env):
            return "", 0
        questions = (payload.get("tool_input") or {}).get("questions") or []
        # The seat's rulings live where `ruling_cli` writes them: the project root.
        root = cwd if slug is not None else (find_project_root(Path(cwd)) or cwd)
        why = _why(questions, root, slug)
        if why:
            route = DOC if slug is not None else "/tp-escalate (" + DOC + ")"
            return _deny(why + "; route the question through " + route), 0
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
