"""PreToolUse Bash hook for the delete fence: a tp design deletes only inside its own tree.

design: delete-fence-own-tree (Task 1.8)

Runs for every session and every `agent_type` (unlike the reviewer-delete hook,
which is scoped to the read-mostly set), and for none of them in the sense that
a main session is fenced exactly like its subagents. Four modules are wired
here, in this order:

  1. a prefilter — the raw command must hold a delete token (one that survives
     the quoted-message-heredoc rewrite below), or the hook allows without
     parsing and without calling git at all;
  2. activation (`delete_fence_roots.fence_active`) — a repo with no tp marker
     and no `TP_DESIGN_RUN` is not fenced, and `TP_DELETE_FENCE=off` in the hook
     process's own environment turns the fence off. An assignment inside the
     command never does: the classifier reads the command, this hook reads env;
  3. the root set (`delete_fence_roots.compute_roots`) — the run's own tree, its
     nested trees, its marker scratch (`reviewer_delete_hook.scratch_for`) and
     this session's harness pad. One `git rev-parse` and one `git worktree list`
     answer every question, however many modules ask;
  4. the classifier — `reviewer_delete_guard.classify(..., mode="fence")` for the
     shell text, and `delete_fence_py.check_python` for each inline Python body
     `delete_fence_py.inline_sources` finds in the command (its `shell_check`
     re-enters this hook's fence classifier, so a `subprocess.run(["rm", …])`
     string is judged by the same rules).

Fail mode: a crash (roots lookup, classifier, a `SyntaxError` in inline Python)
denies only when the raw command text holds a delete token, so a parser gap
never wedges an ordinary session. A denial names the allowed roots and says that
teardown of another tree belongs to the seat.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from delete_fence_verbs import DELETE_WORD

# The one token list, used both as the prefilter that skips parsing and as the
# fail-mode set that decides a crash — so the two cannot drift. It is the
# classifier's own fence-mode delete set (rm, rmdir, unlink, shred, mv, rsync,
# git clean, `worktree remove`, `-delete`, `-exec`), plus the delete verbs
# that appear
# only inside inline Python.
# tp-allow-fragile: the design pins this closed delete-token grammar over a shell command, not prose (design delete-fence-own-tree Behaviors 4)
TOKENS = re.compile(DELETE_WORD.pattern + r"|rmtree|os\.remove|\.unlink\(")
# The same set spelled out, for main()'s crash path when the shared list
# could not be imported at all (the kill-guard hook's pattern).
# tp-allow-fragile: the same closed delete-token grammar, spelled out so main()'s crash path still works when the shared module did not import
_RAW_TOKEN = re.compile(r"\b(rm|rmdir|unlink|shred|mv|rsync|clean|worktree\s+remove)\b"
                        r"|-delete|-exec|-execdir|-ok|-okdir"
                        r"|rmtree|os\.remove|\.unlink\(")

_PREFIX = "delete-fence: refused"
_SEAT = ("Teardown of another tree belongs to the seat: /tp-post-merge, "
         "`git worktree remove` from the seat's own checkout, or gc.")


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}})


def _refusal(command, reason, roots):
    """The denial text: the reason, the allowed roots, and who owns teardown."""
    return ("%s %r — %s. A tp design deletes only inside its own tree. Allowed roots: %s. %s"
            % (_PREFIX, command[:120], reason, ", ".join(roots) or "none", _SEAT))


def _crash(exc):
    return _deny("%s — crashed: %s: %s" % (_PREFIX, type(exc).__name__, exc))


def _cached_git(git):
    """Memoize by argv: the fence makes at most one `rev-parse` and one
    `worktree list` per hook run, however many modules ask."""
    cache = {}

    def call(args, cwd):
        key = tuple(args)
        if key not in cache:
            cache[key] = git(args, cwd)
        return cache[key]
    return call


def _roots(payload, env, git):
    """The fence's root list, or None when this repo is not fenced."""
    import delete_fence_roots
    import reviewer_delete_hook
    cwd = payload.get("cwd")
    call = _cached_git(git)
    top, info = delete_fence_roots.project_context(env, cwd, call)
    if not delete_fence_roots.fence_active(env, top, os.path.exists):
        return None
    # The run kind and the primary root follow the project top level, not the
    # payload cwd: a subagent's cwd can be a detached worktree inside the run's
    # own tree, which git alone would call the seat (task 2.4). `cwd` is then
    # used only for its own top level (`compute_roots`' `_cwd_top`).
    if info is None:
        info = delete_fence_roots.repo_info(call, top or cwd)
    kind = delete_fence_roots.run_kind(env, info)
    return delete_fence_roots.compute_roots(
        kind, info, cwd, env, call, reviewer_delete_hook.scratch_for(payload),
        payload.get("session_id"), os.getuid())


def _inline_verdict(command, roots, cwd, shell_check):
    """The first refusal reason among the command's inline Python bodies."""
    import delete_fence_py
    for source in delete_fence_py.inline_sources(command):
        why = delete_fence_py.check_python(source, roots, cwd, shell_check)
        if why:
            return why
    return None


def _data_rewritten(command):
    """`command` with each quoted `$(cat <<'EOF' … EOF)` message argument
    replaced by a placeholder word, or `command` itself when there is no such
    heredoc, when one could run as code, or when the helper is unavailable.

    The helper is the kill guard's, `kill_guard_hook._data_heredocs` — one rule
    for both hooks, so a commit message or PR body that merely *mentions*
    `rm -rf` is data for the fence exactly as it is prose for the kill guard. A
    quoted heredoc is never expanded and never runs; the helper answers None
    when the substitution sits where its body could be executed
    (`bash -c "$(cat <<'EOF' … EOF)"`), and then nothing is rewritten. Imported
    lazily — this hook runs for every Bash call — and fail-open: importing
    `kill_guard_hook` has no side effects (its `main()` is `__main__`-guarded),
    but a failed import falls back to the unrewritten command rather than
    wedging the fence."""
    try:
        import kill_guard_hook
        rewritten = kill_guard_hook._data_heredocs(command)
    except Exception:
        return command
    return command if rewritten is None else rewritten


def _verdict(command, roots, cwd):
    """Refusal reason for one command against `roots`, else None. A quoted
    message heredoc is rewritten to data first (task 2.2), so neither the
    classifier nor the inline-Python scan reads the message's words."""
    import reviewer_delete_guard
    command = _data_rewritten(command)

    def shell_check(text):
        return _verdict(text, roots, cwd)

    def classify(text, at=cwd):
        verdict = reviewer_delete_guard.classify(text, scratch=roots, cwd=at, mode="fence")
        return None if verdict.allowed else verdict.reason

    why = classify(command)
    if why:
        return why
    # Inline Python runs wherever the shell has moved to: after a `cd` in the
    # command its relative literals are judged with the cwd unknown (denied).
    import delete_fence_py
    py_cwd = None if delete_fence_py.moves_cwd(command) else cwd
    return _inline_verdict(command, roots, py_cwd, lambda text, at=py_cwd: classify(text, at))


def run(payload, *, env=None, git=None):
    """Return (stdout, exit_code) for one PreToolUse payload."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return "", 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not TOKENS.search(command):
        return "", 0  # prefilter: no delete token — no parse, no git call
    # The prefilter reads the rewritten text too: when the only delete words
    # are inside a quoted message heredoc they are data, so the command is
    # allowed without a parse or a git call (task 2.2).
    if not TOKENS.search(_data_rewritten(command)):
        return "", 0
    env = dict(os.environ) if env is None else env
    if git is None:
        git = _subprocess_git
    try:
        roots = _roots(payload, env, git)
        if roots is None:
            return "", 0
        why = _verdict(command, roots, payload.get("cwd"))
        return "" if why is None else _deny(_refusal(command, why, roots)), 0
    except Exception as exc:  # fail closed only for a command that could delete
        return _crash(exc), 0


# Repo-local git env that would redirect `git -C <cwd>` at another repository
# (the M17 rule). Spelled out here rather than imported from the dev-only
# `git_env.py`: this hook ships in core, and a shipped file may not import a
# dev-only one (framework-check inv #45).
_REPO_ENV = ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
             "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
             "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
             "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
             "GIT_SHALLOW_FILE", "GIT_COMMON_DIR")


def _subprocess_git(args, cwd):
    """The default git seam: one `git -C <cwd> …` with the repo-local env scrubbed."""
    env = {k: v for k, v in os.environ.items() if k not in _REPO_ENV}
    proc = subprocess.run(["git", "-C", str(cwd or "."), *args], capture_output=True,
                          text=True, env=env, timeout=5)
    if proc.returncode:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), proc.stderr.strip()[:200]))
    return proc.stdout


def main():
    raw = sys.stdin.read()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        out, code = run(json.loads(raw))
    except Exception as exc:
        try:
            token = TOKENS.search(raw)
        except Exception:  # the token list itself is missing: any delete word denies
            token = _RAW_TOKEN.search(raw)
        out, code = ((_crash(exc) if token else ""), 0)
    if out:
        print(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
