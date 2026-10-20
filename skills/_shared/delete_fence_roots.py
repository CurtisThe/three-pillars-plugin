"""Activation and run-kind lookup for the delete fence (design delete-fence-own-tree 1.6).

Every function here is pure: the environment is an injected `dict` and git is an
injected callable `git(args, cwd) -> str`, so the roots never depend on how the
hook was launched and the tests never shell out. The fence is off (the hook
allows everything silently) in a repo with no tp markers, and stays off when
`TP_DELETE_FENCE=off` is in the hook process's own environment — never from an
assignment inside the command being classified.
"""
from __future__ import annotations

import os

_TMP = "/tmp"  # nosec B108 — a never-root entry, never written to
_PAD_BASE_ENV = "TP_FENCE_PAD_BASE"
_OFF = "off"
_TP_PREFIX = "tp/"
_REV_PARSE_ARGS = ["rev-parse", "--show-toplevel", "--git-dir",
                   "--git-common-dir", "--abbrev-ref", "HEAD"]


def fence_active(env, project_top, exists):
    """True when this repo is a tp repo whose deletes are fenced.

    `exists` is the filesystem predicate (`os.path.exists` in the hook, a stub
    in a test) applied to the two tp markers under `project_top`.
    """
    if (env or {}).get("TP_DELETE_FENCE") == _OFF:
        return False
    if (env or {}).get("TP_DESIGN_RUN") == "1":
        return True
    if not project_top:
        return False
    top = str(project_top).rstrip(os.sep) or os.sep
    return bool(exists(os.path.join(top, "three-pillars-docs"))
                or exists(os.path.join(top, ".three-pillars", "config.json")))


def project_top(env, cwd, git):
    """The project's top level: `CLAUDE_PROJECT_DIR` when set, else git's answer
    for `cwd`. The caller passes the result to `fence_active`.

    A failed `git rev-parse` (no git, or a repo with no commit yet) answers ""
    so a non-tp directory is not fenced; a design run still fails closed later,
    when `repo_info` is asked for the roots."""
    return project_context(env, cwd, git)[0]


def project_context(env, cwd, git):
    """`(top, info)`: the project's top level, and the `repo_info` read to find
    it (None when `CLAUDE_PROJECT_DIR` named it, or when git could not).

    The hook asks `repo_info` about the project top level, not the payload cwd:
    a subagent's cwd can be a linked detached worktree inside the run's own tree,
    whose branch and git dir say "seat". When git answered for `cwd`, that answer
    already describes the top it returned, so it is handed back rather than
    re-read: one `rev-parse` per hook run."""
    top = (env or dict()).get("CLAUDE_PROJECT_DIR")
    if top:
        return top, None
    try:
        info = repo_info(git, cwd)
    except Exception:  # noqa: BLE001 — unknown top level: not a tp repo
        return "", None
    return info["top"], info


def repo_info(git, cwd):
    """One `git rev-parse` for the whole fence: top level, git dir, common dir,
    branch. A linked worktree is the case where the git dir differs from the
    common dir."""
    out = git(_REV_PARSE_ARGS, cwd)
    lines = [line.strip() for line in (out or "").splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    top, git_dir, common_dir, branch = (lines + ["", "", "", ""])[:4]
    return {"top": _abs(cwd, top), "git_dir": _abs(cwd, git_dir),
            "common_dir": _abs(cwd, common_dir), "branch": branch}


def _abs(cwd, path):
    if not path or os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(str(cwd or ""), path))


def run_kind(env, info):
    """"design-run" for a run's own tree, "seat" for everything else.

    A run is `TP_DESIGN_RUN=1`, or a linked worktree whose branch is
    `tp/<slug>`. A linked worktree on any other branch (including a detached
    head) is the seat, and so is the main checkout even on a `tp/` branch.
    """
    if (env or {}).get("TP_DESIGN_RUN") == "1":
        return "design-run"
    if not info:
        return "seat"
    if info.get("git_dir") == info.get("common_dir"):
        return "seat"
    branch = info.get("branch") or ""
    if branch.startswith(_TP_PREFIX) and len(branch) > len(_TP_PREFIX):
        return "design-run"
    return "seat"


def compute_roots(kind, info, payload_cwd, env, git, scratch, session_id, uid):
    """The real paths a delete may touch (strictly inside one of them).

    A design run gets its own top level, the payload cwd's top level (a subagent's
    own tree) and the registered worktrees nested under its top level; the seat
    gets its checkout and every registered worktree. Both get `scratch` and this
    session's harness pad. `git` is called once, for `worktree list --porcelain`.
    Anything on the never-root list, or that is a parent of one, is dropped.
    """
    env = env or {}
    top = _real((info or {}).get("top"))
    listed = _worktrees(git, top or payload_cwd)
    roots = [top]
    if kind == "design-run":
        roots += [w for w in listed if top and _within(w, top)]
        roots.append(_cwd_top(payload_cwd, top, listed))
    else:
        roots += listed
    roots.append(_real(scratch))
    roots += _pad_roots(env, session_id, uid)
    never = _never_roots(env, uid)
    out = []
    for root in roots:
        if root and root not in out and not _never(root, never, uid):
            out.append(root)
    return out


def _real(path):
    return os.path.realpath(str(path)) if path else ""


def _within(path, base):
    """True when `path` is `base` or inside it (both already real paths)."""
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def _worktrees(git, cwd):
    """Registered worktree paths from `git worktree list --porcelain`."""
    if not cwd:
        return []
    try:
        out = git(["worktree", "list", "--porcelain"], cwd)
    except Exception:  # noqa: BLE001 — fewer roots is the safe failure
        return []
    return [_real(line[len("worktree "):].strip())
            for line in (out or "").splitlines() if line.startswith("worktree ")]


def _cwd_top(payload_cwd, top, listed):
    """The top level of the payload cwd (nearest `.git` going up), or "".

    A subagent runs in its own tree, so the cwd's top level can differ from the
    project's. A registered worktree outside the project that is not a direct
    child of `.claude/worktrees` is a sibling design, never a root.
    """
    here = _real(payload_cwd)
    while here and not os.path.lexists(os.path.join(here, ".git")):
        parent = os.path.dirname(here)
        if parent == here:
            return ""
        here = parent
    if not here or here == top:
        return ""
    holder = os.path.dirname(here)
    agent_tree = (os.path.basename(holder) == "worktrees"
                  and os.path.basename(os.path.dirname(holder)) == ".claude")
    if here in listed and not agent_tree and not (top and _within(here, top)):
        return ""
    return here


def _pad_roots(env, session_id, uid):
    """This session's harness scratchpad dirs `<base>/<project>/<session_id>`.

    Found by scanning the real base dir (no wildcard roots). A session id that
    could leave its slot, and any symlinked dir, is skipped.
    """
    sid = str(session_id or "")
    if not sid or sid in (".", "..") or os.sep in sid or "\0" in sid:
        return []
    base = env.get(_PAD_BASE_ENV) or os.path.join(_TMP, "claude-%s" % uid)
    found = []
    try:
        with os.scandir(base) as entries:
            for proj in entries:
                pad = os.path.join(proj.path, sid)
                if (proj.is_dir(follow_symlinks=False) and os.path.isdir(pad)
                        and not os.path.islink(pad)):
                    found.append(_real(pad))
    except OSError:
        return []
    return found


def _never_roots(env, uid):
    home = env.get("HOME") or os.path.expanduser("~")
    pad = env.get(_PAD_BASE_ENV) or os.path.join(_TMP, "claude-%s" % uid)
    return [_real(p) for p in (os.sep, home, _TMP, env.get("TMPDIR"), pad) if p]


def _never(root, never, uid):
    """True for a never-root, a parent of one, or a `pytest-of-*` / `claude-<uid>` dir."""
    name = os.path.basename(root)
    if name.startswith("pytest-of-") or name == "claude-%s" % uid:
        return True
    return any(_within(n, root) for n in never)
