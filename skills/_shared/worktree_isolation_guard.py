"""worktree_isolation_guard.py — the worker isolation predicate.

Guards against shared-worktree corruption (known-issues M13/M14): a worker
committing while its cwd is the shared orchestrator worktree rather than its
own dedicated worktree.

The load-bearing mechanical enforcement is invariant #32 in framework-check.sh
which calls this module with --assert-own-worktree before every commit.

Two advisory boundary helpers are also exposed:
  - forbid_checkout_in_shared: refuse git checkout inside a shared worktree
  - head_drift: pure comparator detecting orchestrator HEAD drift

Design refs:
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/detailed-design.md
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/plan.md
"""

from __future__ import annotations

import argparse
import os
import posixpath
import subprocess
import sys


# ---------------------------------------------------------------------------
# Task 1.1: live_tp_worktrees — porcelain parser returning (path, branch) pairs
# ---------------------------------------------------------------------------


def all_worktrees(worktree_porcelain: str) -> list[tuple[str, str, bool]]:
    """Parse `git worktree list --porcelain`; return (toplevel, branch, is_bare) for EVERY worktree.

    Unlike live_tp_worktrees this returns one entry per worktree regardless of
    branch (including master/main checkouts and detached HEADs). A detached
    worktree gets an empty-string branch. This is what lets the isolation
    predicate locate the registered default-branch (master/main) worktree
    toplevel — the shared orchestrator root — independently of the committing
    HEAD.

    The `is_bare` flag surfaces the porcelain `bare` line. On this operator's
    documented bare-base-checkout topology (core.bare=true WITH a live working
    tree), git emits a `bare` line and NO `branch refs/heads/...` line for the
    main checkout, so owner_branch parses to "" and would otherwise slip past
    the default-branch Case-2 BLOCK. Surfacing `is_bare` lets the isolation
    predicate classify that root as a shared-orchestrator seat regardless of how
    its branch is (not) reported. (See known-issues M14, bare-root coverage.)

    Returns a list of (toplevel_path, branch_name, is_bare). branch_name is the
    stripped short ref (no refs/heads/ prefix) or "" for a detached/bare
    worktree; is_bare is True iff the porcelain stanza carried a `bare` line.
    """
    result: list[tuple[str, str, bool]] = []
    current_path: str | None = None
    current_branch: str = ""
    current_bare: bool = False

    def _flush() -> None:
        nonlocal current_path, current_branch, current_bare
        if current_path is not None:
            result.append((current_path, current_branch, current_bare))
        current_path = None
        current_branch = ""
        current_bare = False

    for line in worktree_porcelain.splitlines():
        line = line.strip()
        if line.startswith("worktree "):
            # New stanza — flush the previous one.
            _flush()
            current_path = line[len("worktree "):]
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                current_branch = ref[len(prefix):]
            else:
                current_branch = ref
        elif line == "bare":
            current_bare = True
        elif line == "":
            _flush()

    _flush()
    return result


def live_tp_worktrees(worktree_porcelain: str) -> list[tuple[str, str]]:
    """Parse `git worktree list --porcelain`; return (toplevel, tp/<slug>) pairs.

    Extended over worktree_write_guard.live_tp_worktrees: also captures the
    `worktree <path>` line so the predicate can locate each worktree's own
    toplevel (needed to determine whether the committing cwd is inside one of
    those toplevels).

    Returns a list of (toplevel_path, branch_name) for every tp/* worktree.
    """
    return [(p, b) for p, b, _bare in all_worktrees(worktree_porcelain) if b.startswith("tp/")]


# Default-branch names that mark the shared orchestrator / master checkout.
_DEFAULT_BRANCHES = ("master", "main")

# ---------------------------------------------------------------------------
# Orchestration paper-trail carve-out
# ---------------------------------------------------------------------------

_ORCHESTRATION_PREFIX = "three-pillars-docs/tp-designs/orchestration/"


def orchestration_only_staged(staged_paths):
    """True iff the staged set is KNOWN, NON-EMPTY, and every path is under
    the orchestration slot. None (unprovable) and [] (no commit) → False —
    the carve-out never fires on an unprovable staged set (fail-closed).

    Paths are matched STRICTLY (forward-slash literals, no backslash
    normalization). A file literally named with backslash separators (a legal
    POSIX filename) is NOT in the orchestration slot. Backslash leniency
    lives ONLY in the CLI --staged-file override arm, where a human may have
    typed Windows-style separators on purpose; it is applied there before
    calling this function, never here.
    """
    if not staged_paths:
        return False
    for path in staged_paths:
        normalized = posixpath.normpath(path)
        if not normalized.startswith(_ORCHESTRATION_PREFIX):
            return False
    return True


# ---------------------------------------------------------------------------
# Task 1.2: is_shared_with_orchestrator + _realpath_within helper
# ---------------------------------------------------------------------------


def _realpath_within(child: str, parent: str) -> bool:
    """Return True iff `child` is equal to or under `parent` (realpath-normalized).

    Uses os.path.realpath for symlink resolution. Does NOT require paths to
    exist on disk — this is a string prefix check after normalization.
    """
    # Normalize separators and resolve any .. components
    norm_child = os.path.normpath(os.path.realpath(child)) if os.path.exists(child) else os.path.normpath(child)
    norm_parent = os.path.normpath(os.path.realpath(parent)) if os.path.exists(parent) else os.path.normpath(parent)

    # Ensure we compare full path components (add sep so /foo/bar doesn't match /foo/baz)
    if norm_child == norm_parent:
        return True
    return norm_child.startswith(norm_parent + os.sep)


def is_shared_with_orchestrator(*, cwd: str, worktree_toplevel: str) -> bool:
    """Return True iff `cwd` is NOT inside `worktree_toplevel`.

    A return value of True means the cwd is shared with the orchestrator (not
    inside its own tp worktree). False means cwd is inside the worktree.

    Copies the cwd_preflight target_worktree_path prefix idiom.
    """
    return not _realpath_within(cwd, worktree_toplevel)


# ---------------------------------------------------------------------------
# Task 1.3: assert_own_worktree — the invariant-#32 predicate
# ---------------------------------------------------------------------------


def _slug_provisioned_tp_branch(toplevel: str) -> str:
    """The tp/<slug> branch a worktree at `toplevel` was provisioned to hold.

    tp worktrees live at `<repo>-wt/<slug>` (the worktree-provisioning layout),
    so the expected branch is `tp/<basename(toplevel)>`. Returns "" when the path
    shape does not look like a tp worktree (no `-wt/` segment), so callers only
    apply the HEAD-drift check to genuine tp worktrees.
    """
    norm = os.path.normpath(toplevel)
    parent = os.path.dirname(norm)
    if parent.endswith("-wt"):
        return "tp/" + os.path.basename(norm)
    return ""


def _is_default_branch_root(toplevel: str, branch: str, is_bare: bool) -> bool:
    """Return True iff `toplevel` is the repo's MAIN/default (shared-orchestrator) checkout.

    Case-2 attribution must treat the operator's main checkout as a
    default-branch root REGARDLESS of how its branch is reported. On the
    documented bare-base-checkout topology (core.bare=true WITH a live working
    tree — see known-issues M14 and the operator's MEMORY note), `git worktree
    list --porcelain` emits a `bare` line and NO `branch refs/heads/master`
    line for the main checkout, so `branch` parses to "". That root is still the
    shared-orchestrator seat and a commit from it must BLOCK when tp/<slug>
    worktrees exist.

    Classify as a default-branch root when ANY of:
      - branch is master/main (the ordinary non-bare checkout); OR
      - the porcelain marked this worktree `bare` (a bare worktree WITH a
        working tree is still the seat); OR
      - the path is NOT a `-wt/<slug>`-provisioned worktree AND NOT an agent
        worktree (`.claude/worktrees/...`) — i.e. it is the main worktree root,
        even when its branch is unreported.

    Guards against over-blocking: a `-wt/<slug>` tp worktree or a
    `.claude/worktrees/agent-*` worktree is NEVER classified as a
    default-branch root, so healthy tp worktrees and agent candidate/* worktrees
    still PASS.
    """
    if branch in _DEFAULT_BRANCHES:
        return True
    if is_bare:
        return True
    # Path-shape fallback: the main checkout is neither a tp-provisioned
    # `-wt/<slug>` worktree nor an agent worktree under `.claude/worktrees/`.
    if _slug_provisioned_tp_branch(toplevel):
        return False
    norm = os.path.normpath(toplevel)
    if (os.sep + ".claude" + os.sep + "worktrees" + os.sep) in (norm + os.sep):
        return False
    return True


def assert_own_worktree(
    *, cwd: str, worktree_porcelain: str, current_branch: str = "",
    staged_paths: list[str] | None = None
) -> tuple[bool, str]:
    """The load-bearing isolation predicate for framework-check invariant #32.

    Returns (ok, guidance_message). When ok=True, msg is empty.

    Topology-aware enforcement (see review wave2-0608 blocking #2/#3 and the
    archived design's "fires iff a tp/<slug> worktree is live AND cwd is not the
    worker's own worktree" rule):

    (1) PASS (empty-live short-circuit): no tp/<slug> worktree is live → nothing
        to isolate against. Mirrors #29.
    (2) BLOCK (shared-orchestrator commit — review blocking #2): cwd resolves to
        the registered default-branch (master/main) worktree toplevel while >=1
        tp/<slug> worktree is live. A commit from the shared master/orchestrator
        checkout is exactly the M14 headline corruption; it must fail-closed.
    (3) BLOCK (HEAD drift inside a tp worktree — review blocking #3): cwd is
        inside a tp-provisioned worktree (`<repo>-wt/<slug>`) but the current
        branch is NOT that worktree's `tp/<slug>` branch — a worker checked out a
        foreign/candidate branch inside an orchestrator tp/* worktree. The
        EXPECTED branch is derived from the worktree path (slug), NOT from the
        live HEAD, so the BLOCK still fires when the porcelain reports the
        drifted branch and the worktree therefore drops out of `live`.
    (4) PASS (worker in own tp worktree): cwd is inside a live tp/<slug> worktree
        toplevel AND current_branch matches that worktree's tp/<slug> branch —
        the orchestrator writing design artifacts on its own branch.
    (5) PASS (distinct non-default worktree, e.g. agent-*): cwd is inside a
        registered worktree that is neither the default-branch root nor a
        tp-provisioned worktree on a foreign branch — the worker operating in
        its own isolated agent worktree.

    Fail-closed: when current_branch is empty/unknown and cwd is inside a
    tp-provisioned worktree, BLOCK (can't prove the branch matches).

    The slug is derived from the porcelain/path, never passed as an argument.
    """
    worktrees = all_worktrees(worktree_porcelain)
    live = [(p, b) for p, b, _bare in worktrees if b.startswith("tp/")]

    # A tp/<slug> worktree is "provisioned" purely by its path shape
    # (`<repo>-wt/<slug>`), INDEPENDENT of its current (possibly drifted) HEAD.
    # The M14 single-drift incident is exactly the case where the SOLE
    # provisioned worktree has drifted to candidate/* — so it falls OUT of
    # `live` and the empty-live short-circuit would skip the drift BLOCK below.
    # We therefore short-circuit on empty-live ONLY when there is also no
    # provisioned -wt/<slug> worktree to attribute the cwd against; otherwise we
    # fall through to the owner-attribution + drift/shared-root BLOCK.
    provisioned = [
        (p, b) for p, b, _bare in worktrees if _slug_provisioned_tp_branch(p)
    ]

    # Case (1): empty-live short-circuit — nothing to isolate against. Applies
    # ONLY when no provisioned -wt/<slug> worktree exists (so no drifted tp
    # worktree is silently dropped from the live list).
    if not live and not provisioned:
        return True, ""

    live_str = ", ".join(f"{b} ({p})" for p, b in live) or "(none on tp/* HEAD)"

    # Identify the SINGLE registered worktree that owns cwd: the most-specific
    # (longest-path) registered toplevel containing cwd. Worktrees nest — agent
    # worktrees live UNDER the master checkout (<repo>/.claude/worktrees/...) —
    # so a naive "any containing toplevel" check would misattribute an agent
    # commit to the master root. git itself resolves to the deepest worktree;
    # we mirror that so each cwd is classified by exactly one owning worktree.
    owner_toplevel: str | None = None
    owner_branch: str = ""
    owner_is_bare: bool = False
    best_len = -1
    for toplevel, branch, is_bare in worktrees:
        if is_shared_with_orchestrator(cwd=cwd, worktree_toplevel=toplevel):
            continue
        tl_len = len(os.path.normpath(toplevel))
        if tl_len > best_len:
            best_len = tl_len
            owner_toplevel = toplevel
            owner_branch = branch
            owner_is_bare = is_bare

    # cwd is not inside ANY registered worktree (e.g. some unrelated path) —
    # nothing to attribute the commit to; PASS (case 2/5 falls through here).
    if owner_toplevel is None:
        return True, ""

    effective_branch = current_branch or owner_branch

    # Case (2): BLOCK a commit whose owning worktree is the registered
    # default-branch (shared-orchestrator) checkout while tp/* worktrees exist
    # (live OR provisioned-but-drifted). This is the positive predicate the
    # review requires: the shared-orchestrator-root commit (M14 headline
    # corruption). The drifted-provisioned set counts here too — a sole tp
    # worktree drifted to candidate/* leaves `live` empty, but the orchestrator
    # root must still BLOCK.
    #
    # Crucially the default-branch classification is NOT gated on the reported
    # branch alone: on this operator's documented bare-base-checkout topology
    # (core.bare=true WITH a live working tree) the porcelain emits a `bare` line
    # and NO `branch refs/heads/master` line for the main checkout, so
    # owner_branch parses to "". _is_default_branch_root() classifies that root
    # as the seat via the `bare` flag (and the path-shape fallback for the main
    # worktree), closing the M14 bare-root hole that previously failed OPEN.
    if _is_default_branch_root(owner_toplevel, owner_branch, owner_is_bare):
        # The orchestration carve-out applies ONLY when the seat's HEAD is
        # genuinely on a default branch (master/main) or is branchless AND the
        # worktree is actually bare (bare / branch not reported). A seat that has
        # been checked out in-place onto a named non-default branch (e.g. tp/b,
        # feature/x) has drifted — the carve-out must NOT fire there, because the
        # paper-trail commit would land on that design branch, not the
        # orchestration slot. A drifted named branch must take the BLOCK path
        # (same as pre-PR behaviour).
        # effective_branch="" covers the bare/unreported-branch topology ONLY when
        # the owning worktree is actually bare (owner_is_bare). A DETACHED non-bare
        # seat also produces effective_branch="" but must NOT get the carve-out —
        # it is not a known-safe branchless topology; it must BLOCK to prevent a
        # commit from landing in an unknown location.
        seat_on_default = (
            effective_branch in _DEFAULT_BRANCHES
            or (not effective_branch and owner_is_bare)
        )
        # Boundary honesty: exclusivity is proven for the staged set at check
        # time. git commit -a, a pathspec, or --amend can still add content at
        # commit time; that risk is mitigated by the framework's scoped-git-add
        # protocol (commit-after-work.md), documented here not hidden.
        if seat_on_default and orchestration_only_staged(staged_paths):
            return True, ""   # orchestration paper-trail carve-out (path-exclusive)
        root_label = owner_branch or ("bare" if owner_is_bare else "main checkout")
        prov_str = ", ".join(f"{b or '(detached)'} ({p})" for p, b in provisioned)
        msg = (
            f"FAIL: refusing commit — cwd '{cwd}' (HEAD on '{effective_branch or '?'}') is the "
            f"shared default-branch ({root_label}) orchestrator worktree '{owner_toplevel}', "
            f"but {len(live)} live and {len(provisioned)} provisioned tp/<slug> worktree(s) exist.\n"
            f"  This is the shared-worktree corruption class (known-issue M13; M14\n"
            f"  is archived in three-pillars-docs/known_issues_resolved.md):\n"
            f"  committing from the shared master/orchestrator checkout while dedicated\n"
            f"  tp/* worktrees exist risks orphaning/cross-contaminating their commits.\n"
            f"  Live tp/* worktree(s): {live_str}\n"
            f"  Provisioned -wt/<slug> worktree(s): {prov_str or '(none)'}\n"
            f"  Fix: run the commit inside the dedicated tp/* worktree it belongs to,\n"
            f"  NOT the shared default-branch orchestrator checkout."
        )
        return False, msg

    # Case (3): BLOCK HEAD drift inside a tp-provisioned worktree. The expected
    # branch is derived from the owning worktree's PATH (slug), independent of
    # the live HEAD — so the BLOCK still fires when the porcelain reports the
    # drifted branch and the worktree dropped out of `live`.
    expected = _slug_provisioned_tp_branch(owner_toplevel)
    if expected and effective_branch != expected:
        branch_info = (
            f" (HEAD is on '{effective_branch}')" if effective_branch else " (HEAD unknown)"
        )
        msg = (
            f"FAIL: refusing commit — cwd '{cwd}'{branch_info} is inside the "
            f"tp-provisioned worktree '{owner_toplevel}' (expected branch '{expected}'), "
            f"but HEAD is NOT on that worktree's tp/<slug> branch.\n"
            f"  This is the shared-worktree corruption class (known-issue M13; M14\n"
            f"  is archived in three-pillars-docs/known_issues_resolved.md):\n"
            f"  a worker has checked out a foreign/candidate branch inside an\n"
            f"  orchestrator tp/* worktree (HEAD drift), risking commit orphaning.\n"
            f"  Live tp/* worktree(s): {live_str}\n"
            f"  Fix: reattach this worktree to '{expected}' (git checkout {expected})\n"
            f"  before committing, or run the worker commit from its own agent worktree."
        )
        return False, msg

    # Cases (4)/(5): cwd's owning worktree is its own tp/<slug> worktree on the
    # matching branch, OR a distinct non-default worktree (agent-*) → PASS.
    return True, ""


# ---------------------------------------------------------------------------
# Task 1.4: forbid_checkout_in_shared boundary helper
# ---------------------------------------------------------------------------


def forbid_checkout_in_shared(*, cwd: str, worktree_porcelain: str) -> tuple[bool, str]:
    """Advisory boundary helper: refuse git checkout inside a shared worktree.

    Same containment shape as assert_own_worktree but with checkout-specific
    guidance. This is a read-only advisory — it advises/refuses, never runs
    the checkout.

    Returns (ok, guidance_message). ok=True means allow; ok=False means refuse.
    """
    live = live_tp_worktrees(worktree_porcelain)

    # No tp/* worktrees active → no shared-worktree hazard
    if not live:
        return True, ""

    # cwd is inside one of the live tp/* worktrees → in own worktree, allow
    for toplevel, _branch in live:
        if not is_shared_with_orchestrator(cwd=cwd, worktree_toplevel=toplevel):
            return True, ""

    # cwd is outside all live tp worktrees → refuse the checkout
    live_str = ", ".join(f"{b} ({p})" for p, b in live)
    msg = (
        f"REFUSE: forbidding git checkout — cwd '{cwd}' is in the shared orchestrator worktree.\n"
        f"  Performing a checkout here while tp/* worktrees are live risks\n"
        f"  orphaning the orchestrator's commits (known shared-worktree hazard).\n"
        f"  Live tp/* worktree(s): {live_str}\n"
        f"  Fix: run the checkout inside your own dedicated worktree,\n"
        f"  NOT the shared orchestrator worktree."
    )
    return False, msg


# ---------------------------------------------------------------------------
# Task 1.5: head_drift pure comparator
# ---------------------------------------------------------------------------


def head_drift(*, dispatch_sha: str, return_sha: str) -> tuple[bool, str]:
    """Pure comparator for orchestrator HEAD drift.

    Returns (ok, msg):
      ok=True, msg="" → no drift (SHAs are equal and both non-empty)
      ok=False, msg=... → drift detected, or INDETERMINATE (empty SHA)

    Empty either side → INDETERMINATE-style block (never a silent pass).

    This is an advisory comparator — the load-bearing orphan protection is
    the branch-name reattach in tp-run-full-design §Branch hygiene rule 3.
    head_drift is for finer SHA-level drift detection when a caller records
    a pre-dispatch SHA.
    """
    if not dispatch_sha or not return_sha:
        which = "dispatch_sha" if not dispatch_sha else "return_sha"
        msg = (
            f"INDETERMINATE: '{which}' is empty — cannot prove no HEAD drift.\n"
            f"  Record the pre-dispatch SHA before dispatch and pass both.\n"
            f"  Blocking fail-closed (empty SHA is never a silent pass)."
        )
        return False, msg

    if dispatch_sha != return_sha:
        msg = (
            f"WARN: orchestrator HEAD drift detected.\n"
            f"  dispatch_sha: {dispatch_sha}\n"
            f"  return_sha:   {return_sha}\n"
            f"  The orchestrator's HEAD moved during the worker dispatch.\n"
            f"  Verify branch integrity (see §Branch hygiene rule 3)."
        )
        return False, msg

    return True, ""


# ---------------------------------------------------------------------------
# Task 1.6: main CLI
# ---------------------------------------------------------------------------


def _run_git(repo: str, args: list[str]) -> str:
    """Run a git command in `repo` and return its stdout. Raises on error."""
    result = subprocess.run(
        ["git", "-C", repo] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main(argv=None) -> int:
    """CLI for worktree isolation guard.

    Subcommands:
      --assert-own-worktree   (flag form, used by invariant #32)
      assert-own              (equivalent subcommand form)
      forbid-checkout         (advisory checkout boundary check)
      head-drift              (pure SHA comparator)

    Override flags for hermetic testing (no real git needed when provided):
      --repo                  repo root (default: cwd)
      --cwd                   override the current working directory
      --worktree-porcelain    override porcelain output (literal string)
      --dispatch-sha          dispatch-time HEAD SHA (for head-drift)
      --return-sha            return-time HEAD SHA (for head-drift)
      --staged-file           override staged files (repeatable; assert-own only)
      --no-staged             hermetic empty staged set (assert-own only)

    Exit 0 = pass/allow, 1 = block/refuse (guidance on stderr).
    Fail-closed on parse success.
    """
    parser = argparse.ArgumentParser(
        description="Worktree isolation guard: ensure worker operates in its own worktree.",
        add_help=True,
    )
    # Subcommand via positional OR flag (--assert-own-worktree is the form #32 uses)
    parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["assert-own", "forbid-checkout", "head-drift"],
        help="subcommand to run (alternative to --assert-own-worktree flag)",
    )
    parser.add_argument(
        "--assert-own-worktree",
        action="store_true",
        dest="assert_own_flag",
        default=False,
        help="flag form of 'assert-own' (used by framework-check invariant #32)",
    )
    parser.add_argument("--repo", default=".", help="repo root (default: .)")
    parser.add_argument("--cwd", default=None, help="override cwd (default: os.getcwd())")
    parser.add_argument(
        "--worktree-porcelain",
        default=None,
        dest="worktree_porcelain",
        help="override porcelain output (literal string)",
    )
    parser.add_argument(
        "--dispatch-sha",
        default=None,
        dest="dispatch_sha",
        help="dispatch-time HEAD SHA (for head-drift subcommand)",
    )
    parser.add_argument(
        "--return-sha",
        default=None,
        dest="return_sha",
        help="return-time HEAD SHA (for head-drift subcommand)",
    )
    parser.add_argument(
        "--branch",
        default=None,
        dest="branch",
        help="override current branch name (for assert-own; default: read from git)",
    )
    # Staged-path overrides for assert-own (mirrors worktree_write_guard.py idiom).
    # Mutually exclusive: --staged-file (repeatable) / --no-staged (hermetic empty).
    staged_group = parser.add_mutually_exclusive_group()
    staged_group.add_argument(
        "--staged-file",
        action="append",
        dest="staged_files",
        default=None,
        metavar="PATH",
        help="override staged files for assert-own (repeatable); absent = read from git",
    )
    staged_group.add_argument(
        "--no-staged",
        action="store_true",
        dest="no_staged",
        default=False,
        help="assert-own: hermetic empty staged set (carve-out can't fire)",
    )
    args = parser.parse_args(argv)

    # Determine which subcommand to run
    cmd = args.subcommand
    if args.assert_own_flag:
        cmd = "assert-own"
    if cmd is None:
        parser.error("subcommand required: assert-own | forbid-checkout | head-drift "
                     "(or use --assert-own-worktree flag)")
        return 2

    repo = args.repo

    if cmd in ("assert-own", "forbid-checkout"):
        # Resolve cwd
        if args.cwd is not None:
            cwd = args.cwd
        else:
            try:
                cwd = _run_git(repo, ["rev-parse", "--show-toplevel"]).strip()
            except Exception:
                cwd = os.getcwd()

        # Resolve porcelain
        if args.worktree_porcelain is not None:
            porcelain = args.worktree_porcelain
        else:
            porcelain = _run_git(repo, ["worktree", "list", "--porcelain"])

        if cmd == "assert-own":
            # Resolve current branch (for assert-own only — needed to detect HEAD drift)
            if args.branch is not None:
                current_branch = args.branch
            else:
                try:
                    current_branch = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
                except Exception:
                    current_branch = ""

            # Resolve staged paths for the carve-out consult (assert-own only).
            # Mirrors worktree_write_guard.py's override idiom:
            #   --no-staged    → [] (hermetic empty; carve-out can't fire)
            #   --staged-file  → that list
            #   neither        → git diff --cached --name-only (live)
            #   git error      → None (unknown; carve-out can't fire — fail-closed)
            if args.no_staged:
                staged_paths: list[str] | None = []
            elif args.staged_files is not None:
                # Apply backslash leniency here (trusted human CLI input may use
                # Windows-style separators) — NOT inside orchestration_only_staged(),
                # where strictness is required to block backslash-named POSIX files.
                staged_paths = [
                    p.replace("\\", "/") for p in args.staged_files
                ]
            else:
                try:
                    raw = _run_git(
                        repo,
                        ["diff", "--cached", "--name-only", "--no-renames", "-z"],
                    )
                    # -z produces NUL-separated, unquoted paths (no C-quoting).
                    # --no-renames ensures both the source and destination of a
                    # staged rename appear separately, so mixed-staging detection
                    # fires correctly when one side is outside the allowlist.
                    staged_paths = [p for p in raw.split("\x00") if p]
                except Exception:
                    staged_paths = None  # unknown → carve-out can't fire

            ok, msg = assert_own_worktree(
                cwd=cwd,
                worktree_porcelain=porcelain,
                current_branch=current_branch,
                staged_paths=staged_paths,
            )
        else:
            ok, msg = forbid_checkout_in_shared(cwd=cwd, worktree_porcelain=porcelain)

        if not ok:
            print(msg, file=sys.stderr)
            return 1
        return 0

    elif cmd == "head-drift":
        # Resolve SHAs
        dispatch_sha = args.dispatch_sha if args.dispatch_sha is not None else ""
        return_sha = args.return_sha if args.return_sha is not None else ""

        ok, msg = head_drift(dispatch_sha=dispatch_sha, return_sha=return_sha)
        if not ok:
            print(msg, file=sys.stderr)
            return 1
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
