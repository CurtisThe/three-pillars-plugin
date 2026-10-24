"""PreToolUse hook: deny worktree isolation and `.claude/` worktree adds.

design: worktrees-under-wt-only (Task 1.2)

Active in a tp repo (marker at the project top) or a design run
(`TP_DESIGN_RUN=1`); `TP_WT_LAYOUT=off` in the hook's own environment turns it
off. Denies (B1) an Agent/Task call that asks for worktree isolation, and (B2)
a Bash `git worktree add` whose target has a `.claude` path part. Any internal
error allows and prints one stderr line, so the hook never wedges a session.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

import delete_fence_roots
import worker_root

ISO = "work" + "tree"
_SPLIT = re.compile(r"&&|\|\||;|\||\n")
_VALUE_OPTS = {"-b", "-B", "--reason"}
_REASON = ("worktree layout: open a worktree under <repo>-wt/<slug> with "
           "`python3 skills/_shared/wt_root.py open --role <role> --slug <slug> --base-ref <ref>` instead; "
           "worktrees under .claude/ and worktree isolation get no classifier verdict")


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "wt-layout: refused — " + reason}})


def _git(args, cwd):
    proc = subprocess.run(["git", *args], cwd=cwd or None, capture_output=True,
                          text=True, check=True, timeout=10)
    return proc.stdout


def _active(env, cwd):
    if env.get("TP_WT_LAYOUT") == "off":
        return False
    if env.get("TP_DESIGN_RUN") == "1":
        return True
    top = delete_fence_roots.project_top(env, cwd, _git)
    if not top:  # git could not answer (e.g. no commit yet): walk up from cwd
        top = _marker_ancestor(cwd)
    return delete_fence_roots.fence_active({}, top, os.path.exists)


def _marker_ancestor(cwd):
    cur = os.path.abspath(cwd)
    while True:
        if (os.path.exists(os.path.join(cur, "three-pillars-docs"))
                or os.path.exists(os.path.join(cur, ".three-pillars", "config.json"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return ""
        cur = parent


def _join(base, path):
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(base or os.getcwd(), path)


def _add_target(words, cwd):
    """The target of `git [-C dir] worktree add ...` in `words`, else None."""
    if not words or os.path.basename(words[0]) != "git":
        return None
    i, base = 1, cwd
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            base = _join(base, words[i + 1])
        i += 2 if words[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if words[i:i + 2] != ["worktree", "add"]:
        return None
    i += 2
    while i < len(words):
        if words[i] in _VALUE_OPTS:
            i += 2
        elif words[i].startswith("-"):
            i += 1
        else:
            return _join(base, words[i])
    return None


def _bash_denied(command, cwd):
    seg_cwd = cwd
    for seg in _SPLIT.split(command):
        words = shlex.split(seg)
        if len(words) >= 2 and words[0] == "cd":
            seg_cwd = _join(seg_cwd, words[1])
            continue
        target = _add_target(words, seg_cwd)
        if target is not None and worker_root.has_claude_component(target):
            return True
    return False


def decide(payload, env):
    """The deny JSON for this payload, or "" to allow."""
    cwd = payload.get("cwd") or os.getcwd()
    tool = payload.get("tool_name")
    inp = payload.get("tool_input") or {}
    if tool not in ("Agent", "Task", "Bash") or not _active(env, cwd):
        return ""
    if tool in ("Agent", "Task"):
        return _deny(_REASON) if inp.get("isolation") == ISO else ""
    return _deny(_REASON) if _bash_denied(inp.get("command") or "", cwd) else ""


def main():
    try:
        out = decide(json.loads(sys.stdin.read()), dict(os.environ))
    except Exception as exc:  # noqa: BLE001 — never wedge a session
        print(f"wt_layout_hook: allowed after error: {exc}".replace("\n", " "),
              file=sys.stderr)
        return 0
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
