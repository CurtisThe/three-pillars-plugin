"""merge_carry.py -- classify a base-sync MERGE as a proof-neutral link (basesync-docs-only-carry).

`proof_neutral_carry.strip_proof_neutral_commits` walks first-parent. A merge of the base branch into
a converged PR brings other PRs' already-reviewed history plus, sometimes, living-doc conflict
resolutions. It cannot change the code the reviewers read when ALL of these hold:

  * it has exactly two parents (an octopus merge is never neutral);
  * its second parent is on the base branch's first-parent history (`origin/<base>`, else the local
    `<base>`): a merge from any other ref, or from a commit that only reached the base through a
    side branch's merge, is not neutral;
  * the merge's tree equals the CLEAN merge of its two parents (`git merge-tree --write-tree P1 P2`,
    git's own merge of the two sides) except on living-doc `.md` paths, and every path that merge
    reports as conflicted is also a living-doc `.md`. So a clean auto-merge, or a whole file kept
    from one side (`-s ours`, `checkout --ours`), is judged against what git would have produced:
    a code path that deviates from the clean merge, in either direction, is never neutral. The
    deviating paths are the hand-resolved ones, with a regular-file mode, status added or modified.

The accepted resolved-path set is every living-doc `.md` per `living_doc_carry.is_living_doc_carry_path`:
all of `three-pillars-docs/**/*.md` except `specs/` and `project-context.md`, the design's own
`tp-designs/<slug>/` and `completed-tp-designs/<slug>/` dirs and other designs' dirs included, the
same set the single-commit carry uses.

`merge_link(git, merge, parents, base_ref=...)` returns `(ok, reason, lines)`; `lines` is the
per hand-resolved path (one that deviates from the clean merge tree) the smaller of its
added+deleted counts against either parent, summed, so base content that came in unchanged adds
none and a binary file elsewhere does not matter; 0 when not neutral. Every reason starts with
`merge commit`. Without a resolvable `base_ref` no merge is neutral, which is the behaviour before
this module existed.

`lazy_base_ref(pr_url, derive_fn)` is the callers' memoised base-branch lookup, so the one `gh`
call happens only when the walk reaches a merge.

stdlib-only, total, never raises, and `git` through the `run_git(args) -> (rc, out, err)`
seam shared with `round_log_carry`: read-only apart from `merge-tree --write-tree`, which only
adds unreachable objects. Every unknown (git older than 2.38 included) is "not neutral".
"""
from __future__ import annotations

import re

_REF_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_ZERO_MODE = "000000"
_REG_MODE = "100644"


def lazy_base_ref(pr_url, derive_fn=None):
    """A memoised zero-arg callable returning the PR's base branch name, or None. Never raises."""
    cache = []

    def _get():
        if not cache:
            try:
                if derive_fn is not None:
                    cache.append(derive_fn(pr_url))
                else:
                    import diff_balloon_guard  # in _shared/ beside this file
                    cache.append(diff_balloon_guard.derive_base_ref(pr_url))
            except Exception:
                cache.append(None)
        return cache[0]

    return _get


def _resolve_base_ref(base_ref):
    """The base branch name from a str or a zero-arg callable, or None when unusable."""
    try:
        name = base_ref() if callable(base_ref) else base_ref
    except Exception:
        return None
    if isinstance(name, str) and _REF_RE.fullmatch(name):
        return name
    return None


def _on_base_first_parent(git, sha: str, base: str) -> "tuple[bool, str]":
    """(True, "") when `sha` is on the first-parent history of `origin/<base>`, else `<base>`."""
    for ref in (f"origin/{base}", base):
        rc, _, _ = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        if rc != 0:
            continue
        rc, out, _ = git(["rev-list", "--first-parent", ref, "--"])
        if rc != 0:
            return (False, "cannot read the base first-parent history")
        if sha in out.split():
            return (True, "")
        return (False, f"second parent is not on the first-parent history of {ref}")
    return (False, f"base branch {base} not found")


def _clean_merge(git, first: str, second: str) -> "tuple[str, list] | str":
    """(clean merge tree id, conflicted paths) from `git merge-tree`, or a reason string."""
    rc, out, _ = git(["merge-tree", "--write-tree", "-z", "--name-only", first, second])
    if rc not in (0, 1):
        return "cannot compute the clean merge (git merge-tree failed)"
    parts = out.split("\0")
    tree, conflicted = parts[0], []
    for name in parts[1:]:
        if not name:
            break
        conflicted.append(name)
    if not _SHA_RE.fullmatch(tree):
        return "cannot read the clean merge tree"
    if (rc == 1) != bool(conflicted):
        return "cannot read the conflicted paths of the clean merge"
    return (tree, conflicted)


def _raw_by_path(git, old: str, new: str) -> "dict | None":
    """{path: (old_mode, new_mode, status)} of `old..new` (tree-ishes), or None when unreadable."""
    import round_log_carry
    rc, out, _ = git(["diff-tree", "-r", "--no-renames", "--raw", "-z", old, new])
    entries = round_log_carry._parse_raw(out) if rc == 0 else None
    if entries is None:
        return None
    return {path: (old_mode, new_mode, status) for old_mode, new_mode, status, path in entries}


def _numstat_by_path(git, parent: str, merge: str, paths) -> "dict | None":
    """{path: added+deleted} of `parent..merge` limited to `paths`; None when unreadable or binary."""
    rc, out, _ = git(["diff-tree", "-r", "--no-renames", "--numstat", "-z", parent, merge, "--",
                      *[f":(literal){path}" for path in paths]])
    if rc != 0:
        return None
    counts = {}
    for tok in out.split("\0"):
        if not tok:
            continue
        cols = tok.split("\t", 2)
        if len(cols) != 3 or not (cols[0].isdigit() and cols[1].isdigit()):
            return None
        counts[cols[2]] = int(cols[0]) + int(cols[1])
    return counts


def _is_living_doc_md(path: str) -> bool:
    import living_doc_carry
    return path.endswith(".md") and living_doc_carry.is_living_doc_carry_path(path)


def _resolved_path_reason(path: str, entry: tuple) -> str:
    """"" when this hand-resolved path is a neutral living-doc change, else why it is not."""
    old_mode, new_mode, status = entry
    if not _is_living_doc_md(path):
        return f"{path} is hand-resolved and is not a living-doc .md"
    if status not in ("M", "A") or new_mode != _REG_MODE \
            or old_mode != (_REG_MODE if status == "M" else _ZERO_MODE):
        return f"{path} is hand-resolved with status {status} or a mode change"
    return ""


def merge_link(git, merge: str, parents, *, base_ref=None) -> "tuple[bool, str, int]":
    """(True, "", resolved_lines) when `merge` over `parents` cannot change reviewed code.

    `parents` is the commit's parent list in order (first = the branch). Total: any failure,
    however odd, is `(False, "merge commit: <why>", 0)`; this never raises.
    """
    try:
        parents = list(parents)
        if len(parents) != 2:
            return (False, f"merge commit with {len(parents)} parents", 0)
        if not all(_SHA_RE.fullmatch(sha) for sha in [merge, *parents]):
            return (False, "merge commit: unexpected parent ids", 0)
        base = _resolve_base_ref(base_ref)
        if base is None:
            return (False, "merge commit: no resolvable base branch", 0)
        ok, why = _on_base_first_parent(git, parents[1], base)
        if not ok:
            return (False, f"merge commit: {why}", 0)
        clean = _clean_merge(git, parents[0], parents[1])
        if isinstance(clean, str):
            return (False, f"merge commit: {clean}", 0)
        tree, conflicted = clean
        for path in conflicted:
            if not _is_living_doc_md(path):
                return (False, f"merge commit: {path} conflicts and is not a living-doc .md", 0)
        resolved = _raw_by_path(git, tree, merge)
        if resolved is None:
            return (False, "merge commit: cannot compare the merge with the clean merge", 0)
        for path, entry in sorted(resolved.items()):
            why = _resolved_path_reason(path, entry)
            if why:
                return (False, f"merge commit: {why}", 0)
        if not resolved:
            return (True, "", 0)
        first_n, second_n = (_numstat_by_path(git, parent, merge, resolved) for parent in parents)
        if first_n is None or second_n is None:
            return (False, "merge commit: binary or unreadable numstat", 0)
        # a path equal to one parent's version has no row there: that side costs 0 lines
        return (True, "", sum(min(first_n.get(path, 0), second_n.get(path, 0)) for path in resolved))
    except Exception as exc:  # total: never raise
        return (False, f"merge commit: error: {exc}", 0)
