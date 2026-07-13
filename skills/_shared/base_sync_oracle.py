"""base_sync_oracle.py -- the independent-oracle guard (`oracle_independent`).

stdlib-only, total, never raises. The unified fail-closed precondition `base_sync_cert`'s
`certify_link`/`find_certified_anchor` guard on before trusting any RME re-derivation: the
oracle (wherever THIS code is actually running from) must be both FRESH-DATA (compared
against a just-fetched base tip, never a stale cached one) and DISJOINT-CODE (loaded from a
checkout that provably carries only already-gated base-line content). See
`three-pillars-docs/completed-tp-designs/approval-survives-safe-base-sync/detailed-design.md` for the
full numbered-step spec this module implements verbatim.

Built up across Phase 3 (task 3.2: FRESH-DATA + oracle identity; task 3.3: DISJOINT-CODE
branch classification; task 3.4: the universal content criterion + entry wiring).
`base_sync_cert.py` re-exports `oracle_independent` and wires it in as the real guard,
replacing its Phase-2 pass-through stub.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
_SEAT_RESOLVE_SH = _SHARED_DIR / "seat_resolve.sh"

_FETCH_REFUSE = (
    "could not fetch origin/<base> — refusing to certify against a possibly-stale base ref"
)
_GENERIC_REFUSE = "oracle code provenance indeterminate — no carry"
_UNKNOWN_WORKTREE_REFUSE = (
    "oracle checkout is not the primary worktree — unknown-worktree topology, no carry"
)
_CONTENT_REFUSE = "oracle checkout is not on the trusted base line — no carry"
_ORACLE_GIT_ERROR_REFUSE = "oracle code provenance indeterminate (git error) — no carry"

# git's own precise "no repository found here or in any parent directory" signal, verified
# live (`git -C <non-repo-dir> rev-parse --show-toplevel`): rc 128, stderr
# "fatal: not a git repository (or any of the parent directories): .git". Matched on the
# "(or any of the parent directories)" qualifier specifically -- NOT the bare substring
# "not a git repository" -- because a corrupt/dangling `.git` gitfile (pointing at a
# nonexistent gitdir) ALSO emits a message containing "not a git repository" (verified live:
# "fatal: not a git repository: /nonexistent/gitdir") but WITHOUT this qualifier, and a
# dubious-ownership `safe.directory` refusal is a different message entirely ("detected
# dubious ownership"). Both of those are ambiguous git errors -- not a confirmed absence of
# any repository -- and must fail closed, never waved through as external-install.
_NOT_A_REPO_MARKER = "not a git repository (or any of the parent directories)"


def _is_genuinely_outside_any_repo(rc: int, stderr: str) -> bool:
    """True ONLY for git's own precise "not a repo anywhere in the parent chain" signal (see
    `_NOT_A_REPO_MARKER` above). Any other rc/stderr combination -- a different rc, rc 128
    with a different message (dubious ownership, dangling gitdir, permission denied), or
    empty/malformed stderr -- returns False, so the caller fails closed instead of accepting
    an indeterminate git error as external-install."""
    if rc != 128:
        return False
    return _NOT_A_REPO_MARKER in (stderr or "").lower()


def _real_run_git_raw(args: list) -> tuple:
    """Unscoped `git <args>` -- the caller supplies its own `-C <dir>` when the target isn't
    `repo_root` (oracle identity/HEAD resolution target `code_dir`/`oracle_root`, never the
    subject repo). Never raises: any subprocess failure collapses to `(-1, "", "")`."""
    try:
        r = subprocess.run(["git", *args], capture_output=True)
    except Exception:
        return (-1, "", "")
    return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
           r.stderr.decode("utf-8", "surrogateescape"))


def _real_run_cmd(argv: list) -> tuple:
    """Default `run_cmd` seam -- non-git subprocesses (the `bash seat_resolve.sh`
    invocations). Never raises."""
    try:
        r = subprocess.run(argv, capture_output=True)
    except Exception:
        return (-1, "", "")
    return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
           r.stderr.decode("utf-8", "surrogateescape"))


def _make_default_git(repo_root):
    def _run(args: list) -> tuple:
        return _real_run_git_raw(["-C", str(repo_root), *args])
    return _run


def _oracle_code_dir() -> Path:
    """Hard-derives the physical directory this module's file lives in. NOT part of any
    public signature -- production always resolves to wherever `base_sync_oracle.py` is
    actually loaded from. The sole test seam is monkeypatching this private function
    directly (fixture topologies point it at a constructed oracle-root candidate)."""
    return Path(__file__).resolve().parent


def _canon(path) -> str:
    """Best-effort physical-path canonicalization -- mirrors `seat_resolve.sh`'s `_canon`
    (`cd && pwd -P`). Infallible: falls back to the raw string on any resolution failure,
    matching the bash helper's own fallback."""
    try:
        return str(Path(str(path)).resolve())
    except Exception:
        return str(path)


class _Worktree:
    __slots__ = ("path", "bare")

    def __init__(self, path: str, bare: bool):
        self.path = path
        self.bare = bare


def _parse_worktree_porcelain(out: str):
    """Mirror `seat_resolve.sh::_parse_worktrees`'s shape: parallel stanzas separated by a
    blank line, each starting with a `worktree <path>` line and optionally containing a bare
    `bare` line. Returns `None` on an empty/malformed listing (no stanza found) -- the
    caller's fail-closed trigger."""
    entries = []
    cur_path = None
    cur_bare = False
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur_path is not None:
                entries.append(_Worktree(cur_path, cur_bare))
            cur_path = line[len("worktree "):]
            cur_bare = False
        elif line == "bare":
            cur_bare = True
        elif line == "":
            if cur_path is not None:
                entries.append(_Worktree(cur_path, cur_bare))
            cur_path = None
            cur_bare = False
    if cur_path is not None:
        entries.append(_Worktree(cur_path, cur_bare))
    return entries or None


def _classify_disjoint_code(repo_root, oracle_root: str, *, run_git, run_cmd) -> tuple:
    """Step 3 -- DISJOINT-CODE branch classification, given an already-resolved
    `oracle_root` (the caller has already handled the external-install case: this is only
    called with a resolved, existing repo toplevel). Returns `(True, "")` when a
    checkout-bearing acceptance branch applies (distinct-repo, OR confirmed-seat including
    the bare-hub sub-case) -- step 4's content criterion still gates these unconditionally;
    `(False, reason)` on any refusal. `run_git` is scoped to `repo_root` (the subject); the
    worktree enumeration runs there. `run_cmd` invokes `seat_resolve.sh` (real by default;
    injected only for error/indeterminate simulation)."""
    try:
        rc, out, _err = run_git(["worktree", "list", "--porcelain"])
    except Exception:
        return False, _GENERIC_REFUSE
    if rc != 0:
        return False, _GENERIC_REFUSE
    worktrees = _parse_worktree_porcelain(out)
    if not worktrees:
        return False, _GENERIC_REFUSE

    oracle_canon = _canon(oracle_root)
    primary = worktrees[0]
    matched = next((wt for wt in worktrees if _canon(wt.path) == oracle_canon), None)

    if matched is None:
        return True, ""   # distinct-repo: continue to step 4

    # confirmed-seat: matched IS a registered worktree of the subject repo.
    if not primary.bare:
        try:
            rc_seat, _o, _e = run_cmd(["bash", str(_SEAT_RESOLVE_SH), "--am-i-seat",
                                       "--repo", oracle_root])
        except Exception:
            return False, _GENERIC_REFUSE
        if rc_seat != 0:
            return False, _GENERIC_REFUSE
        if oracle_canon != _canon(primary.path):
            return False, _UNKNOWN_WORKTREE_REFUSE
        return True, ""

    # bare-primary carve-out: the primary entry is the bare hub, not a checkout -- probe
    # the HUB (verified live: probing --json from the base worktree itself classifies
    # unknown-worktree; the bare-hub-variant verdict only appears probed from the hub).
    try:
        rc_json, out_json, _e = run_cmd(["bash", str(_SEAT_RESOLVE_SH), "--json",
                                         "--repo", primary.path])
    except Exception:
        return False, _GENERIC_REFUSE
    if rc_json != 0:
        return False, _GENERIC_REFUSE
    try:
        parsed = json.loads(out_json)
    except Exception:
        return False, _GENERIC_REFUSE
    if not isinstance(parsed, dict) or parsed.get("state") != "bare-hub-variant":
        return False, _GENERIC_REFUSE
    seat_path = parsed.get("seat_path")
    if not isinstance(seat_path, str) or not seat_path or _canon(seat_path) != oracle_canon:
        return False, _GENERIC_REFUSE
    return True, ""


def _content_whitelist(repo_root, oracle_root: str, base_tip: str, *, run_git) -> tuple:
    """Step 4 -- the UNIVERSAL CONTENT CRITERION (positive whitelist), applied uniformly to
    EVERY checkout-bearing accepted branch. `oracle_head = git -C oracle_root rev-parse
    HEAD^{commit}` (resolves a detached HEAD too -- a seat (mis)checked-out detached at a
    chain ancestor is NOT exempt); absent/unresolvable -> refuse. ACCEPT iff `git -C
    repo_root merge-base --is-ancestor oracle_head base_tip` exits 0 (`base_tip` is step 1's
    fetched tip, reused as-is, never re-derived) -- the oracle's HEAD is an ancestor-or-equal
    of the freshly-fetched base tip, i.e. it carries only already-gated, trusted base-line
    content. ANY other outcome refuses: rc 1 (not an ancestor -- INCLUDES a commit unknown to
    `repo_root` entirely, e.g. an unrelated-origin checkout, rc 128 -- the stated fail-closed
    trade-off), rc > 1, or any subprocess failure. There is NO presence probe and NO ancestry
    test against `head_oid` -- the attempt-3 default-permit formulas over those two tests
    were unsound (fixtures 15/16 pin the two defeats)."""
    rc, out, _err = _real_run_git_raw(["-C", str(oracle_root), "rev-parse", "HEAD^{commit}"])
    if rc != 0:
        return False, _CONTENT_REFUSE
    oracle_head = out.strip()
    if not oracle_head:
        return False, _CONTENT_REFUSE
    try:
        rc2, _out2, _err2 = run_git(["merge-base", "--is-ancestor", oracle_head, base_tip])
    except Exception:
        return False, _CONTENT_REFUSE
    if rc2 != 0:
        return False, _CONTENT_REFUSE
    return True, ""


def oracle_independent(repo_root, head_oid, *, base_ref, run_git=None, run_cmd=None) -> tuple:
    """The unified fail-closed precondition. Returns `(True, "")` or `(False, reason)`; first
    failure wins; ANY exception or indeterminacy -> `(False, ...)`. `head_oid` is accepted
    for call-site/signature stability (the attempt-2 HEAD-oid sub-checks it originally
    supported are superseded by the universal content criterion -- decision 18 -- and it is
    otherwise unused here).

    Step 1 -- FRESH-DATA: `git fetch origin <base>` MUST exit 0, then `origin/<base>^{commit}`
    must resolve, else refuse with the stale-base reason. This precedes everything else:
    step 4's content criterion compares against this fetched tip.
    Step 2 -- oracle identity: `code_dir = Path(<this module>.__file__).resolve().parent`;
    `oracle_root = git -C code_dir rev-parse --show-toplevel`. `--show-toplevel` failing with
    git's own precise "not a repository anywhere in the parent chain" signal (rc 128,
    `_NOT_A_REPO_MARKER` in stderr -- code genuinely lives outside any git repo, e.g. a
    plugin-cache install) is the external-install DISJOINT-CODE branch: disjoint holds
    outright, no checkout exists, step 4 is exempt by construction. ANY OTHER outcome -- a
    different rc, rc 128 with a different message (dubious ownership, a corrupt/dangling
    gitfile, permission denied), an empty/whitespace toplevel, or the seam raising -- is an
    AMBIGUOUS git error, not a confirmed absence of a repository, and refuses fail-closed
    with `_ORACLE_GIT_ERROR_REFUSE` (never silently trusted as external-install).
    Step 3 -- DISJOINT-CODE branch classification (`_classify_disjoint_code`): exactly one
    acceptance branch applies (distinct-repo / confirmed-seat incl. the bare-hub carve-out);
    anything else refuses with "oracle code provenance indeterminate — no carry" (or, for a
    same-repo registered worktree that is neither the primary nor under `*-wt/`, the distinct
    unknown-worktree reason).
    Step 4 -- the universal content criterion (`_content_whitelist`): applied uniformly to
    every checkout-bearing accepted branch (distinct-repo AND confirmed-seat incl. bare-hub;
    external-install has no checkout and is exempt by construction).
    """
    try:
        git = run_git or _make_default_git(repo_root)
        cmd = run_cmd or _real_run_cmd

        # ---- Step 1: FRESH-DATA ----
        try:
            rc, _out, _err = git(["fetch", "origin", base_ref])
        except Exception:
            return False, _FETCH_REFUSE
        if rc != 0:
            return False, _FETCH_REFUSE
        try:
            rc2, out2, _err2 = git(["rev-parse", f"origin/{base_ref}^{{commit}}"])
        except Exception:
            return False, _FETCH_REFUSE
        base_tip = out2.strip()
        if rc2 != 0 or not base_tip:
            return False, _FETCH_REFUSE

        # ---- Step 2: oracle identity ----
        code_dir = _oracle_code_dir()
        rc3, out3, err3 = _real_run_git_raw(["-C", str(code_dir), "rev-parse", "--show-toplevel"])
        if rc3 != 0:
            if _is_genuinely_outside_any_repo(rc3, err3):
                return True, ""     # external-install: accepted outright, step 4 exempt
            # ANY other git error (dubious ownership, dangling gitdir, permission denied, ...)
            # is ambiguous provenance, never a confirmed external-install -- fail closed.
            return False, _ORACLE_GIT_ERROR_REFUSE
        oracle_root = out3.strip()
        if not oracle_root:
            # defensive: an unresolved (empty/whitespace) toplevel is NOT a confirmed
            # external-install either -- fail closed rather than silently trusting it.
            return False, _ORACLE_GIT_ERROR_REFUSE

        # ---- Step 3: DISJOINT-CODE branch classification ----
        ok3, reason3 = _classify_disjoint_code(repo_root, oracle_root, run_git=git, run_cmd=cmd)
        if not ok3:
            return False, reason3

        # ---- Step 4: universal content criterion (positive whitelist) ----
        return _content_whitelist(repo_root, oracle_root, base_tip, run_git=git)
    except Exception:
        return False, "internal error during oracle guard"
