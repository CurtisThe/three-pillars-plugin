"""base_sync_cert.py -- the certified no-op-chain primitive (RME single-link check + walk).

stdlib-only, total, never raises. Re-derives, from git objects alone, whether a base-sync
merge (or a chain of them) is a mechanical no-op certified against the shared
`auto_safe_resolution` AUTO-SAFE allowlist -- see
`three-pillars-docs/completed-tp-designs/approval-survives-safe-base-sync/detailed-design.md`.

Phase 2 scope: `git_version_ok`, the config interpreters, the `merge-tree -z` parser, RME
conditions 1-5 (`certify_link`/`_certify_link_unchecked`), and the chain walk
(`find_certified_anchor`/`certified_noop_chain`). The independent-oracle guard
(`oracle_independent`) lives in `base_sync_oracle.py` (Phase 3) and is re-exported here;
public `certify_link` guards at entry and `find_certified_anchor` guards once per walk.

This module builds up section by section (task 2.2: config/version guards; task 2.3: the
merge-tree parser; task 2.4/2.5: RME conditions; task 2.6: the chain walk; task 3.4: the
oracle guard wiring).
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from auto_safe_resolution import AUTO_SAFE_PATHS, RESOLVED, resolve_conflict_bytes  # noqa: E402
from base_sync_oracle import oracle_independent  # noqa: E402

_MERGE_SCRIPTS = _SHARED_DIR.parent / "tp-merge-from-main" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))
import verify as _verify  # noqa: E402

GIT_MIN_VERSION = (2, 38)          # git merge-tree --write-tree floor
_DEFAULT_MAX_CHAIN = 5

_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)")
_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
_MODE_RE = re.compile(r"^[0-7]{6}$")


@dataclass(frozen=True)
class LinkCheck:
    ok: bool
    reason: str = ""                    # "" when ok; else the FIRST failed RME condition, named
    conflicted_paths: tuple = field(default_factory=tuple)   # K, for audit detail


@dataclass(frozen=True)
class ChainResult:
    certified: bool
    anchor: "str | None" = None         # matched anchor (full sha) when certified
    links: int = 0                      # certified links crossed
    reason: str = ""                    # "" when certified; fail-closed reason otherwise


# ============================================================
# Task 2.2: config interpreters + git_version_ok
# ============================================================


def carry_enabled(config) -> bool:
    """True ONLY on a literal `True` -- the deliberate INVERSE of the strict-default
    `review.*` interpreters (here the strict default IS off). Absence, a non-dict `review`,
    corrupt config, or any truthy-non-bool value (1, "true", ...) all fold to False."""
    try:
        review = (config or {}).get("review") if isinstance(config, dict) else None
        if not isinstance(review, dict):
            return False
        return review.get("approval_survives_safe_base_sync") is True
    except Exception:
        return False


def carry_max_chain(config) -> int:
    """Reads `review.base_sync_carry_max_chain`: an int (bool excluded) in 1..20, else the
    default 5."""
    try:
        review = (config or {}).get("review") if isinstance(config, dict) else None
        if not isinstance(review, dict):
            return _DEFAULT_MAX_CHAIN
        val = review.get("base_sync_carry_max_chain")
        if isinstance(val, bool) or not isinstance(val, int):
            return _DEFAULT_MAX_CHAIN
        return val if 1 <= val <= 20 else _DEFAULT_MAX_CHAIN
    except Exception:
        return _DEFAULT_MAX_CHAIN


def _real_run_git_bare(args: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["git", *args], capture_output=True)
    except Exception:
        return (-1, "", "")
    return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
           r.stderr.decode("utf-8", "surrogateescape"))


def git_version_ok(*, run_git=None) -> bool:
    """Parses `git version` stdout -> `(major, minor) >= GIT_MIN_VERSION`. Parse failure,
    non-zero exit, or any exception -> False (min-git guard NEVER falls back to a weaker merge
    recomputation)."""
    try:
        git = run_git or _real_run_git_bare
        rc, out, _err = git(["version"])
        if rc != 0:
            return False
        m = _VERSION_RE.search(out)
        if not m:
            return False
        return (int(m.group(1)), int(m.group(2))) >= GIT_MIN_VERSION
    except Exception:
        return False


def _redecode_strict_utf8(surrogate_str: str) -> str:
    """Re-derive true UTF-8 text from a seam string decoded with `errors="surrogateescape"`.
    Raises `UnicodeDecodeError` iff the original bytes were not valid UTF-8 -- the SAME
    strict-decode policy `auto_safe_resolution.decode_blob_strict` applies, expressed over the
    str-shaped seam channel instead of raw bytes."""
    return surrogate_str.encode("utf-8", "surrogateescape").decode("utf-8")


# ============================================================
# Task 2.3: merge-tree -z parser -- fail-closed SHAPE invariant
# ============================================================


def _parse_merge_tree_z(out: str):
    """Parse `git merge-tree --write-tree -z --no-messages` stdout into `(tree_oid,
    conflicts)` where `conflicts` is `{path: {stage: (mode, oid)}}`. ANY shape anomaly --
    missing trailing NUL / trailing garbage, missing tree oid, malformed mode/oid, a
    non-integer or out-of-range (not 1-3) stage, a stanza missing its TAB-separated filename
    field, or an undecodable path -- returns None. The parser never guesses: an unrecognized
    shape is the caller's fail-closed "merge-tree output shape unrecognized"."""
    parts = out.split("\x00")
    if not parts or parts[-1] != "":
        return None
    parts = parts[:-1]
    if not parts:
        return None
    tree = parts[0]
    if not _OID_RE.match(tree):
        return None
    conflicts: dict = {}
    for stanza in parts[1:]:
        if "\t" not in stanza:
            return None
        head_part, path = stanza.split("\t", 1)
        fields = head_part.split(" ")
        if len(fields) != 3:
            return None
        mode, oid, stage_s = fields
        if not _MODE_RE.match(mode) or not _OID_RE.match(oid) or not stage_s.isdigit():
            return None
        stage = int(stage_s)
        if stage not in (1, 2, 3):
            return None
        try:
            path = _redecode_strict_utf8(path)
        except UnicodeDecodeError:
            return None
        conflicts.setdefault(path, {})[stage] = (mode, oid)
    return tree, conflicts


# ============================================================
# git subprocess seam (repo-scoped default)
# ============================================================


def _make_default_git(repo_root):
    def _run(args: list[str]) -> tuple[int, str, str]:
        try:
            r = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True)
        except Exception:
            return (-1, "", "")
        return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
               r.stderr.decode("utf-8", "surrogateescape"))
    return _run


# ============================================================
# Task 2.4: certify_link RME conditions 1-2 (merge shape + recompute)
# ============================================================


def _cond1_merge_shape(git, h0: str, h1: str, base_ref: str):
    rc, out, _err = git(["rev-list", "--parents", "-n1", h1])
    if rc != 0:
        return None, "git error: rev-list --parents failed"
    parts = out.strip().split()
    if not parts:
        return None, "git error: rev-list --parents failed"
    parents = parts[1:]
    if len(parents) != 2:
        return None, f"merge shape: expected 2 parents, found {len(parents)}"
    p1, p2 = parents
    if p1.lower() != h0.lower():
        return None, "merge shape: first parent is not h0"
    rc2, _out2, _err2 = git(["merge-base", "--is-ancestor", p2, f"origin/{base_ref}"])
    if rc2 == 1:
        return None, "second parent not on base branch"
    if rc2 != 0:
        return None, "git error: merge-base --is-ancestor failed"
    return (p1, p2), ""


def _cond2_recompute(git, h0: str, p2: str):
    rc, out, _err = git(["merge-tree", "--write-tree", "-z", "--no-messages", h0, p2])
    if rc not in (0, 1):
        return None, None, "git error: merge-tree recompute failed"
    parsed = _parse_merge_tree_z(out)
    if parsed is None:
        return None, None, "merge-tree output shape unrecognized"
    tree, conflicts = parsed
    return tree, conflicts, ""


class _GitOpError(Exception):
    pass


# ============================================================
# Task 2.5: certify_link RME conditions 3-5 (allowlist, containment, resolver re-run)
# ============================================================


def _parse_dashz_names(out: str):
    """Parse a NUL-terminated `--name-only -z` path list. Empty stdout -> `[]`."""
    if out == "":
        return []
    if not out.endswith("\x00"):
        return None
    try:
        return [_redecode_strict_utf8(n) for n in out.split("\x00")[:-1]]
    except UnicodeDecodeError:
        return None


def _parse_ls_tree_line(out: str):
    line = out.rstrip("\n")
    if not line or "\t" not in line:
        return None
    head_part, _path = line.split("\t", 1)
    fields = head_part.split(" ")
    if len(fields) != 3:
        return None
    mode, _type, oid = fields
    if not _MODE_RE.match(mode) or not _OID_RE.match(oid):
        return None
    return mode, oid


def _hash_object_stdin_real(data: bytes, repo_root=None):
    """Scoped to `repo_root` (`-C <repo_root>`) when given, so the blob hash is computed in
    the SUBJECT repo's own object format (e.g. non-SHA-1 repos) rather than the ambient
    process cwd's -- condition 5 compares this against `h1`'s committed blob oid, which is
    always `repo_root`-scoped. `repo_root=None` (the direct-call test seam) preserves the
    prior unscoped behavior."""
    try:
        argv = ["git"]
        if repo_root is not None:
            argv += ["-C", str(repo_root)]
        argv += ["hash-object", "--stdin"]
        r = subprocess.run(argv, input=data, capture_output=True)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("ascii", "replace").strip()


def _cond3_allowlist(conflicts: dict) -> str:
    for path in conflicts:
        if path not in AUTO_SAFE_PATHS:
            return "non-AUTO-SAFE conflict path"
    return ""


def _cond4_containment(git, tree: str, conflicts: dict, h1: str) -> str:
    rc, out, _err = git(["diff-tree", "-r", "-z", "--name-only", tree, f"{h1}^{{tree}}"])
    if rc != 0:
        return "git error: diff-tree failed"
    changed = _parse_dashz_names(out)
    if changed is None:
        return "diff-tree output shape unrecognized"
    if not set(changed).issubset(conflicts.keys()):
        return "change outside the conflicted region (condition 4)"
    return ""


def _cat_blob_strict(git, oid: str) -> str:
    rc, out, _err = git(["cat-file", "blob", oid])
    if rc != 0:
        raise _GitOpError("cat-file blob failed")
    return _redecode_strict_utf8(out)


def _cond5_resolve(git, conflicts: dict, h1: str, repo_root=None) -> str:
    for path, stages in conflicts.items():
        if not all(s in stages for s in (1, 2, 3)):
            return "non-content conflict"
        stage_modes = [stages[s][0] for s in (1, 2, 3)]
        rc, out, _err = git(["ls-tree", h1, "--", path])
        if rc != 0:
            return "git error: ls-tree failed"
        parsed = _parse_ls_tree_line(out)
        if parsed is None or parsed[0] != "100644" or any(m != "100644" for m in stage_modes):
            return "non-content conflict"
        try:
            base_txt = _cat_blob_strict(git, stages[1][1])
            ours_txt = _cat_blob_strict(git, stages[2][1])
            theirs_txt = _cat_blob_strict(git, stages[3][1])
        except UnicodeDecodeError:
            return "undecodable (non-UTF-8) blob content"
        except _GitOpError:
            return "git error: cat-file blob failed"
        status, merged = resolve_conflict_bytes(base=base_txt, ours=ours_txt, theirs=theirs_txt)
        if status != RESOLVED:
            return "resolver could not deterministically reproduce a resolution"
        ok, _dropped = _verify.verify(ours_txt, theirs_txt, merged)
        if not ok:
            return "zero-drop verifier detected a content drop"
        merged_oid = _hash_object_stdin_real(merged.encode("utf-8"), repo_root)
        h1_oid = parsed[1]
        if merged_oid is None or merged_oid.lower() != h1_oid.lower():
            return "resolved bytes do not match h1's committed blob"
    return ""


def _certify_link_unchecked(repo_root, h0: str, h1: str, *, base_ref: str, run_git=None) -> LinkCheck:
    """RME conditions 1-5, first-failure-wins. No oracle guard here -- callers (`certify_link`
    at entry, `find_certified_anchor`'s walk once-per-evaluation) own that."""
    git = run_git or _make_default_git(repo_root)
    try:
        parents, reason = _cond1_merge_shape(git, h0, h1, base_ref)
        if reason:
            return LinkCheck(False, reason)
        _p1, p2 = parents
        tree, conflicts, reason = _cond2_recompute(git, h0, p2)
        if reason:
            return LinkCheck(False, reason)
        reason = _cond3_allowlist(conflicts)
        if reason:
            return LinkCheck(False, reason, tuple(sorted(conflicts)))
        reason = _cond4_containment(git, tree, conflicts, h1)
        if reason:
            return LinkCheck(False, reason, tuple(sorted(conflicts)))
        reason = _cond5_resolve(git, conflicts, h1, repo_root)
        if reason:
            return LinkCheck(False, reason, tuple(sorted(conflicts)))
        return LinkCheck(True, "", tuple(sorted(conflicts)))
    except Exception:
        return LinkCheck(False, "internal error during link certification")


# ============================================================
# Independent-oracle guard seam -- wired to the real guard (task 3.4)
# ============================================================
#
# `oracle_independent` (base_sync_oracle.py): FRESH-DATA (mandatory fetch) + DISJOINT-CODE
# branch classification + the universal content criterion (positive whitelist). Public
# `certify_link` guards at entry; `find_certified_anchor` guards ONCE per evaluation (one
# fetch per walk, not per link) and walks via `_certify_link_unchecked`, which never guards.

_oracle_guard = oracle_independent


def certify_link(repo_root, h0: str, h1: str, *, base_ref: str, head_oid=None,
                 run_git=None, run_cmd=None) -> LinkCheck:
    """Public single-link RME check: guards the independent-oracle precondition at entry
    (`oracle_independent`), then delegates to `_certify_link_unchecked`."""
    try:
        ok, reason = _oracle_guard(repo_root, head_oid if head_oid is not None else h1,
                                   base_ref=base_ref, run_git=run_git, run_cmd=run_cmd)
        if not ok:
            return LinkCheck(False, reason)
    except Exception:
        return LinkCheck(False, "internal error during oracle guard")
    return _certify_link_unchecked(repo_root, h0, h1, base_ref=base_ref, run_git=run_git)


# ============================================================
# Task 2.6: chain walk
# ============================================================


def _shallow_probe(git):
    rc, out, _err = git(["rev-parse", "--is-shallow-repository"])
    if rc != 0 or out.strip() != "false":
        return False, "shallow/incomplete history — cannot walk chain; carry requires a full clone"
    return True, ""


def _commit_exists(git, sha: str) -> bool:
    rc, _out, _err = git(["cat-file", "-e", f"{sha}^{{commit}}"])
    return rc == 0


def _first_parent(git, sha: str):
    """Return `(p1, error)`. `error` True on any rev-list failure or a root commit (no
    parent) -- both surface as the walk's "history incomplete" reason."""
    rc, out, _err = git(["rev-list", "--parents", "-n1", sha])
    if rc != 0:
        return None, True
    parts = out.strip().split()
    if len(parts) < 2:
        return None, True
    return parts[1], False


def find_certified_anchor(repo_root, head, candidates, *, base_ref, max_links=None,
                          run_git=None, run_cmd=None) -> ChainResult:
    """First-parent walk from `head`, re-proving each link via `_certify_link_unchecked`.
    Entry guards (git version -> shallow probe -> oracle guard -> head existence), each fails
    closed with a distinct reason; `candidates` matched as lowercased full SHAs. Total, never
    raises."""
    try:
        try:
            cand_lower = {c.lower() for c in candidates} if candidates else set()
        except Exception:
            cand_lower = set()
        cur = head
        if isinstance(cur, str) and cur.lower() in cand_lower:
            return ChainResult(True, cur, 0, "")   # pre-walk short-circuit, links == 0

        if not git_version_ok(run_git=run_git):
            return ChainResult(False, None, 0, "git < 2.38 — carry unavailable")
        git = run_git or _make_default_git(repo_root)
        ok_shallow, shallow_reason = _shallow_probe(git)
        if not ok_shallow:
            return ChainResult(False, None, 0, shallow_reason)
        ok_oracle, oracle_reason = _oracle_guard(repo_root, head, base_ref=base_ref,
                                                 run_git=run_git, run_cmd=run_cmd)
        if not ok_oracle:
            return ChainResult(False, None, 0, oracle_reason)
        if not isinstance(cur, str) or not _commit_exists(git, cur):
            return ChainResult(False, None, 0, "head commit unavailable — fetch origin")

        max_n = max_links if (isinstance(max_links, int) and not isinstance(max_links, bool)) else _DEFAULT_MAX_CHAIN
        links = 0
        while True:
            if links >= max_n:
                # `>=`, not `==`: defensive against a non-positive/garbage `max_n` (would
                # otherwise never equal an incrementing `links` and silently disable the cap
                # entirely) -- fail-closed direction only, boundary unchanged for valid caps.
                return ChainResult(False, None, links,
                                   f"chain cap {max_n} exceeded — re-approve on the current head")
            p1, err = _first_parent(git, cur)
            if err:
                return ChainResult(False, None, links, "history incomplete")
            lc = _certify_link_unchecked(repo_root, p1, cur, base_ref=base_ref, run_git=run_git)
            if not lc.ok:
                return ChainResult(False, None, links, lc.reason)
            cur = p1
            links += 1
            if cur.lower() in cand_lower:
                return ChainResult(True, cur, links, "")
    except Exception:
        return ChainResult(False, None, 0, "internal error during chain walk")


def certified_noop_chain(repo_root, anchor, head, *, base_ref, max_links=None,
                         run_git=None, run_cmd=None) -> ChainResult:
    """`certified_noop_chain(anchor, head)` == `find_certified_anchor(head, {anchor})`."""
    candidates = {anchor} if isinstance(anchor, str) else set()
    return find_certified_anchor(repo_root, head, candidates, base_ref=base_ref,
                                 max_links=max_links, run_git=run_git, run_cmd=run_cmd)
