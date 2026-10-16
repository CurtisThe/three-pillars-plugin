"""task_attempts.py — per-task attempt worktrees: namespace, placement, lifecycle.

design: local-implement-and-review (Behavior 5, Q6-b)

Every attempt (task worker, escalated Opus, opus-from-start under ``--local``) runs in
its own worktree, so nothing here ever runs ``git reset --hard`` or ``git clean`` in the
dispatcher's tree.

* **Placement (inv #32)** — ``<dispatcher_root>/.tp-scratch/tp-attempt-<slug>-
  <task>-<nonce>`` (``scratch_root.SCRATCH_DIR``; the legacy ``.claude/worktrees``
  parent is still accepted, for residue from before the move), never ``/tmp``: the
  isolation guard classifies a worktree that is neither ``<repo>-wt/<slug>`` nor under
  a scratch parent as the seat, so with a live ``tp/*`` worktree every hooked commit
  there would be refused. Branches are ``tp-attempt/<slug>/<task>-<nonce>``
  (never ``tp/*``).
* **Owner record** — ``<git-common-dir>/tp-attempts/<slug>/<task>-<nonce>.json``, written
  ``opening`` before the branch and worktree exist and ``open`` after, so a crash at any
  point leaves a record ``sweep`` can clean up. ``owner.pid``/``host`` are diagnostic;
  liveness is registration-based (the owner's root is still a registered worktree).
* **Snapshots** — the ``refs/remotes`` sha map and ``dirty_outside`` of the dispatcher and
  of the worktree holding ``guard_ref``, for ``task_verify check`` steps 1-2.

Stdlib only; ``task_verify.py`` is the CLI that delegates here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import scratch_root
import task_scope

ATTEMPT_PARENT = scratch_root.SCRATCH_DIR
DIR_PREFIX = "tp-attempt-"
BRANCH_PREFIX = "tp-attempt/"
RECORDS = "tp-attempts"
EXCLUDE_LINE = scratch_root.ignore_line()


class DirtyTree(Exception):
    """The dispatcher has uncommitted changes outside its design dir (``env-error``)."""

    def __init__(self, paths):
        self.paths = list(paths)
        super().__init__("dirty tree outside the design dir: " + ", ".join(self.paths))


def _git(repo, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=task_scope._git_env())


def _out(repo, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-") or "x"


def slug_of(design_dir_rel: str) -> str:
    """The attempt namespace: the design dir's basename."""
    return _safe(Path(str(design_dir_rel or "").rstrip("/")).name or "design")


def toplevel(root) -> str:
    """The realpath of the worktree toplevel containing ``root``."""
    return os.path.realpath(_out(root, "rev-parse", "--show-toplevel"))


def common_dir(root) -> str:
    return os.path.realpath(_out(root, "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"))


def record_path(attempt: dict) -> str:
    return os.path.join(attempt["common_dir"], RECORDS, attempt["attempt_id"] + ".json")


def _write_record(rec: dict) -> None:
    path = record_path(rec)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _ensure_exclude(common: str) -> None:
    """Append ``/.tp-scratch/`` to the common ``info/exclude`` once (local only)."""
    path = os.path.join(common, "info", "exclude")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    if EXCLUDE_LINE in text.splitlines():
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(("" if not text or text.endswith("\n") else "\n") + EXCLUDE_LINE + "\n")


def remotes_snapshot(root) -> dict:
    """``{refname: sha}`` for every ``refs/remotes`` ref."""
    out = _out(root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes")
    return dict(line.split(" ", 1) for line in out.splitlines() if " " in line)


def worktree_for_ref(root, ref: str) -> str | None:
    """Realpath of the registered worktree that has branch ``ref`` checked out."""
    want = ref if ref.startswith("refs/") else f"refs/heads/{ref}"
    path = None
    for line in _out(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch {want}" and path:
            return os.path.realpath(path)
    return None


def _add_worktree(top: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(rec["attempt_dir"]), exist_ok=True)
    _git(top, "worktree", "add", "-q", "-b", rec["branch"], rec["attempt_dir"], rec["base_sha"])


def _new_record(top: str, task_id: str, design_dir_rel: str, guard_ref, dirty) -> dict:
    slug, nonce, task = slug_of(design_dir_rel), uuid.uuid4().hex[:8], _safe(task_id)
    head = _out(top, "rev-parse", "HEAD")
    branch = _git(top, "symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip()
    guard_root = worktree_for_ref(top, guard_ref) if guard_ref else None
    guard_sha = _out(top, "rev-parse", "--verify", f"{guard_ref}^{{commit}}") if guard_ref else None
    guard_dirty = task_scope.dirty_outside(guard_root, design_dir_rel) if guard_root else []
    return {
        "attempt_id": f"{slug}/{task}-{nonce}", "task_id": str(task_id), "slug": slug,
        "status": "opening", "common_dir": common_dir(top), "design_dir_rel": design_dir_rel,
        "attempt_dir": os.path.join(top, ATTEMPT_PARENT, f"{DIR_PREFIX}{slug}-{task}-{nonce}"),
        "branch": f"{BRANCH_PREFIX}{slug}/{task}-{nonce}",
        "base_sha": head, "dispatcher_head": head, "dispatcher_branch": branch,
        "guard_ref": guard_ref, "guard_sha": guard_sha, "guard_root": guard_root,
        "remotes_snapshot": remotes_snapshot(top),
        "dirty_snapshot": {"dispatcher": list(dirty), "guard_root": guard_dirty},
        "owner": {"dispatcher_root": top, "pid": os.getpid(), "host": socket.gethostname(),
                  "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
    }


def open_attempt(root, task_id: str, design_dir_rel: str, *, guard_ref: str | None = None) -> dict:
    """Open one attempt worktree off the dispatcher's ``HEAD`` → its (``open``) record.

    Refuses with ``DirtyTree`` when ``dirty_outside(root, design_dir_rel)`` is non-empty.
    Order (crash-safe): record ``opening`` → branch + ``worktree add`` → record ``open``.
    """
    top = toplevel(root)
    dirty = task_scope.dirty_outside(top, design_dir_rel)
    if dirty:
        raise DirtyTree(dirty)
    rec = _new_record(top, task_id, design_dir_rel, guard_ref, dirty)
    _ensure_exclude(rec["common_dir"])
    _write_record(rec)
    try:
        _add_worktree(top, rec)
    except Exception:
        discard(rec, root=top)
        raise
    rec["status"] = "open"
    _write_record(rec)
    return rec


def _owner_root(rec: dict) -> str:
    return str((rec.get("owner") or {}).get("dispatcher_root") or "")


def removable(rec: dict) -> bool:
    """True iff ``attempt_dir`` normalises to a direct child named ``tp-attempt-*`` of one
    of ``scratch_root.scan_parents(<owner.dispatcher_root>)`` (the new scratch base,
    then the legacy ``.claude/worktrees``) — the only paths ``rm`` may target."""
    owner = _owner_root(rec)
    if not owner or not rec.get("attempt_dir"):
        return False
    parents = [os.path.realpath(p) for p in scratch_root.scan_parents(owner)]
    target = os.path.realpath(str(rec["attempt_dir"]))
    return (os.path.dirname(target) in parents
            and os.path.basename(target).startswith(DIR_PREFIX))


def _repo_for(rec: dict, root) -> str:
    if root:
        return str(root)
    owner = _owner_root(rec)
    return owner if owner and os.path.isdir(owner) else str(rec["common_dir"])


def discard(attempt: dict, *, root=None) -> dict:
    """Remove an attempt: worktree dir → ``worktree prune`` → branch → record.

    Idempotent (a hand-deleted dir, an absent branch or record are tolerated). ``rm``
    only ever targets a ``tp-attempt-*`` child of one of ``<owner>``’s scratch
    parents; any other ``attempt_dir`` is left on disk (branch + record only, logged). Only a
    ``tp-attempt/`` branch is ever deleted. Never touches the dispatcher's tree.
    → ``{attempt_id, removed_dir, log}``.
    """
    repo, adir, log = _repo_for(attempt, root), str(attempt.get("attempt_dir") or ""), []
    removed = False
    if removable(attempt):
        if os.path.exists(adir):
            _git(repo, "worktree", "remove", "--force", "--force", adir, check=False)
            if os.path.exists(adir):
                shutil.rmtree(adir, ignore_errors=True)
            removed = not os.path.exists(adir)
    elif adir:
        parents = ", ".join(scratch_root.scan_parents(_owner_root(attempt) or "?"))
        log.append(f"attempt_dir outside {parents} {DIR_PREFIX}*; not removed: {adir}")
    _git(repo, "worktree", "prune", check=False)
    branch = str(attempt.get("branch") or "")
    if branch.startswith(BRANCH_PREFIX):
        res = _git(repo, "branch", "-D", branch, check=False)
        still = _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
        if res.returncode and still.returncode == 0:
            log.append(f"branch not deleted: {branch}: {res.stderr.strip()}")
    try:
        os.remove(record_path(attempt))
    except FileNotFoundError:
        pass
    for line in log:
        print(f"task_attempts: {line}", file=sys.stderr)
    return {"attempt_id": attempt.get("attempt_id"), "removed_dir": removed, "log": log}


def registered_roots(root) -> set:
    """Realpaths of every worktree ``git worktree list`` still registers."""
    out = _out(root, "worktree", "list", "--porcelain")
    return {os.path.realpath(line[len("worktree "):])
            for line in out.splitlines() if line.startswith("worktree ")}


def _resolve(repo, ref: str) -> str:
    res = _git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def _reached(repo, sha: str, target: str) -> bool:
    """``sha`` is an ancestor of ``target``, or (a cherry-pick land) an equivalent patch is."""
    if _git(repo, "merge-base", "--is-ancestor", sha, target, check=False).returncode == 0:
        return True
    if not _resolve(repo, f"{sha}~1"):
        return False
    cherry = _git(repo, "cherry", target, sha, f"{sha}~1", check=False)
    return cherry.returncode == 0 and cherry.stdout.strip().startswith("-")


def _landed(repo, rec: dict, own: bool) -> dict | None:
    """The ``landed`` entry for a ``landing`` record whose commit reached the dispatcher."""
    if rec.get("status") != "landing":
        return None
    sha = rec.get("commit_sha") or _resolve(repo, f"refs/heads/{rec.get('branch', '')}")
    # A dead owner's HEAD is gone with its worktree; its branch (e.g. the worker's
    # candidate branch, swept from the orchestrator's Cleanup) still carries the land.
    target = _resolve(repo, "HEAD" if own else str(rec.get("dispatcher_branch") or ""))
    if not sha or not target or sha == rec.get("base_sha") or not _reached(repo, sha, target):
        return None
    return {"attempt_id": rec["attempt_id"], "task_id": rec["task_id"], "sha": sha}


def _partial_land(repo, rec: dict, own: bool, log: list) -> None:
    """A ``landing`` record whose tip is not reached: a range land that died between its
    commits. An own one is undone (abort a cherry-pick left in progress, else quit it; then
    ``reset --keep`` to ``pre_land_head`` if a strict ancestor of HEAD); a dead owner's is
    only logged. The caller discards the attempt, so the task re-runs."""
    pre = rec.get("status") == "landing" and _resolve(repo, str(rec.get("pre_land_head") or ""))
    if not pre:
        return
    pick = ("sequencer", "CHERRY_PICK_HEAD")  # a pick left in progress blocks the next land
    done = own and any(os.path.exists(_out(repo, "rev-parse", "--path-format=absolute",
                                           "--git-path", n)) for n in pick)
    if done and _git(repo, "cherry-pick", "--abort", check=False).returncode:
        _git(repo, "cherry-pick", "--quit", check=False)
    head = _resolve(repo, "HEAD" if own else str(rec.get("dispatcher_branch") or ""))
    ahead = head and head != pre and not _git(repo, "merge-base", "--is-ancestor", pre, head,
                                              check=False).returncode
    if ahead and not own:
        log.append(f"partial-land: {rec.get('branch')}")
        return
    if ahead:
        done = _git(repo, "reset", "--keep", "-q", pre, check=False).returncode == 0
    if ahead or done:
        log.append(f"partial-land reset{'' if done else ' failed'}: {rec['attempt_id']}")


def sweep(root, slug: str) -> dict:
    """Discard this slug's leftover attempts → ``{discarded, landed, log}``.

    ``worktree prune`` first; then only records under ``tp-attempts/<slug>/`` whose owner
    is dead (its root no longer registered) or is ``realpath(root)`` itself (sweep runs
    before the dispatcher opens anything). Other slugs and live owners are never touched.
    A ``landing`` record whose commit already reached the dispatcher (crash after land,
    before discard) is reported in ``landed`` so the task is recorded done, not re-run; one
    whose range landed only in part is undone by ``_partial_land``.
    """
    top = toplevel(root)
    _git(top, "worktree", "prune", check=False)
    live = registered_roots(top)
    rec_dir = os.path.join(common_dir(top), RECORDS, _safe(slug))
    out = {"discarded": [], "landed": [], "log": []}
    for path in sorted(Path(rec_dir).glob("*.json")) if os.path.isdir(rec_dir) else []:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["log"].append(f"unreadable record skipped: {path}: {exc}")
            continue
        owner = os.path.realpath(_owner_root(rec)) if _owner_root(rec) else ""
        own = owner == top
        if not own and owner in live:
            continue
        hit = _landed(top, rec, own)
        if hit:
            out["landed"].append(hit)
        else:
            _partial_land(top, rec, own, out["log"])
        out["log"].extend(discard(rec, root=top)["log"])
        out["discarded"].append(rec["attempt_id"])
    return out
