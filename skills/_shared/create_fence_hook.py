"""PreToolUse hook for the create fence: a tp design run makes files only inside its own tree.

design: run-scratch-in-fence (Task 1.5)

The delete fence guards deletes only; this hook is its other half. It reads one
PreToolUse payload and denies a create whose literal target is outside every
create root. Active only under `TP_DESIGN_RUN=1`, off with `TP_CREATE_FENCE=off`
(both read from the hook process's own environment, never from the command).

  * Write, Edit and NotebookEdit carry one path (`file_path` / `notebook_path`);
  * Bash is read by `create_fence_targets` (redirects, the explicit-destination
    verbs, inline Python, a `TMPDIR`/cache-var assignment) behind its cheap verb
    prefilter, so a plain `ls` never reaches the parser or git.

Create roots: the delete fence's roots (`delete_fence_roots.compute_roots`: the
run's tree, nested trees, its marker scratch, this session's pad, and the run's
own `<tree>/.tp-scratch/run` when TMPDIR names it, which is what lets a worker in
an attempt tree create in the run's scratch), plus `/dev/{null,stdout,stderr,tty}`
and `$CLAUDE_CONFIG_DIR/projects/*/memory/`.

Each literal target is resolved with `os.path.realpath` (non-strict: it follows
every existing link, a dangling final one included, and appends the part that
does not exist yet); the result must sit inside a root. A command that makes a symlink and also
creates at or below that link path is refused outright, naming both (the link is
not there yet when paths are resolved). A computed target (an
unknown `$VAR`, a command substitution, a glob) is allowed: a stray is reversible
and the leftover check reports it. A crash allows with one stderr line: a parser
gap must never wedge an ordinary session.
"""
from __future__ import annotations

import json
import os
import sys

_PREFIX = "create-fence: refused"
_OFF = "off"
_FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}
_DEV_SINKS = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty")
_MEMORY = "memory"


def active(env):
    """True under a design run with the switch not turned off."""
    return env.get("TP_DESIGN_RUN") == "1" and env.get("TP_CREATE_FENCE") != _OFF


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}})


def _inside(path, base):
    """True when `path` is `base` or below it (both already normalised)."""
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def _config_projects(env):
    config = env.get("CLAUDE_CONFIG_DIR") or os.path.join(
        env.get("HOME") or os.path.expanduser("~"), ".claude")
    return os.path.join(os.path.realpath(config), "projects")


def _refusal(what, path, roots, env):
    return ("%s %s — %s is outside this run's tree. A tp design run creates files only inside "
            "its own tree: use $TMPDIR (its run dir) for scratch. Allowed roots: %s; %s; %s."
            % (_PREFIX, what[:120], path, ", ".join(roots) or "none", ", ".join(_DEV_SINKS),
               os.path.join(_config_projects(env), "*", _MEMORY) + os.sep))


def _link_refusal(what, link, other):
    return ("%s %s — it makes the symlink %s and also creates %s through it. The link is not "
            "there yet when this check resolves paths, so it cannot tell where %s lands: make "
            "the link in one command and write through it in the next, or write inside this "
            "run's tree." % (_PREFIX, what[:120], link, other, other))


def _roots(payload, env, git):
    """The fence roots for this run (the delete fence's own set)."""
    import delete_fence_roots
    import reviewer_delete_hook
    from delete_fence_hook import _cached_git
    cwd = payload.get("cwd")
    call = _cached_git(git)
    top, info = delete_fence_roots.project_context(env, cwd, call)
    if info is None:
        info = delete_fence_roots.repo_info(call, top or cwd)
    return delete_fence_roots.compute_roots(
        delete_fence_roots.run_kind(env, info), info, cwd, env, call,
        reviewer_delete_hook.scratch_for(payload), payload.get("session_id"), os.getuid())


def _is_sink(path):
    return any(_inside(os.path.normpath(path), sink) for sink in _DEV_SINKS)


def _allowed(path, roots, env):
    """True when the real location of `path` is inside a create root."""
    if _is_sink(path):
        return True
    real = os.path.realpath(path)
    if any(_inside(real, root) for root in roots):
        return True
    projects = _config_projects(env)
    if _inside(real, projects) and real != projects:
        parts = os.path.relpath(real, projects).split(os.sep)
        return len(parts) >= 2 and parts[1] == _MEMORY
    return False


def _file_tool_path(payload):
    """The absolute path a file tool writes, or None when there is none to judge."""
    path = (payload.get("tool_input") or {}).get(_FILE_TOOLS[payload["tool_name"]])
    if not isinstance(path, str) or not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(payload["cwd"], path) if payload.get("cwd") else None


def _bash_paths(payload, env):
    """The literal paths a Bash command would create (none when it has no create verb)."""
    import create_fence_targets
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not create_fence_targets.has_create_verb(command):
        return command, [], None
    found = create_fence_targets.shell_targets(command, payload.get("cwd"), env)
    return command, found[0], getattr(found, "conflict", None)


def run(payload, *, env=None, git=None):
    """Return (stdout, exit_code) for one PreToolUse payload."""
    if not isinstance(payload, dict):
        return "", 0
    tool = payload.get("tool_name")
    env = dict(os.environ) if env is None else env
    if (tool != "Bash" and tool not in _FILE_TOOLS) or not active(env):
        return "", 0
    conflict = None
    if tool == "Bash":
        what, paths, conflict = _bash_paths(payload, env)
    else:
        path = _file_tool_path(payload)
        what, paths = "%s %s" % (tool, path), [path] if path else []
    if conflict:
        return _deny(_link_refusal(what, *conflict)), 0
    paths = [p for p in paths if not _is_sink(p)]
    if not paths:
        return "", 0
    if git is None:
        from delete_fence_hook import _subprocess_git as git
    roots = _roots(payload, env, git)
    for path in paths:
        if not _allowed(path, roots, env):
            return _deny(_refusal(what, path, roots, env)), 0
    return "", 0


def main():
    raw = sys.stdin.read()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        out, code = run(json.loads(raw))
    except Exception as exc:  # fail open: a parser gap must not wedge an ordinary session
        sys.stderr.write("create-fence: hook crashed, allowing (fail-open): %s: %s\n"
                         % (type(exc).__name__, " ".join(str(exc).split())[:200]))
        out, code = "", 0
    if out:
        print(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
