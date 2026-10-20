"""number_issues.py — placeholder known-issue ID numbering (design: basesync-autoresolve-coverage).

``plan_numbering(head, *, base=None, merge_base=None)`` is a pure planner: each
argument maps a repo-relative ``.md`` path to its full text. It (1) renumbers any
branch-side ID that collides with a base-side ID introduced independently since
``merge_base`` (a true collision, not a shared ancestor heading), then (2) assigns
the next free number per letter to every ``### L-new-slug`` placeholder heading
this branch introduced in ``ISSUE_FILES`` (in file order, then line order), rewriting
every occurrence of that placeholder text (heading and citations alike) across all of
``head``. The result holds only the files whose text changed.

A placeholder headed in ``merge_base``'s ``ISSUE_FILES`` but no longer in ``base``'s is
inherited and already numbered (or dropped) by the base: the merge brings the base's
number in, so this pass leaves it exactly as inherited. Numbering it here would mint a
second ID that collides with the base's. One the base still holds unnumbered is numbered
as usual (the base's side is unchanged, so the merge carries this number in cleanly).
A skipped key still heads the branch, so the ``/tp-merge`` placeholder gate refuses the PR
until a base-sync (``/tp-merge-from-main``) merges the base's number in; the CLI names
those keys (``inherited`` in the plan JSON, a stderr line when writing).
A branch that edited an inherited placeholder's entry still conflicts textually with the
base's numbering; that is a normal deferred hunk. Branch-added text citing such a
placeholder keeps the placeholder text (the base's number is not mapped back).

The CLI reads committed ``HEAD`` blobs only (never the worktree) of every ``.md`` file in the
whole tree (``LS_TREE_SCOPE``), plans against ``--base`` (read over ``base_read_paths``: HEAD's
paths plus ``ISSUE_FILES`` whether or not HEAD has them), and refuses to write over an
uncommitted edit to any file the plan touches. ``--base <name>`` resolves to ``origin/<name>``
when that remote-tracking ref exists (a local base can be stale and reissue a teammate's
just-landed ID; fetching first is the caller's job) and to the local ref only when it does not.

Exit codes: ``0`` ok (plan printed, written, committed, or nothing to do); ``2``
unresolvable ``--base`` or a failed git read; ``3`` dirty tree, nothing written;
``4`` ``git add``/``git commit`` failed (e.g. a pre-commit hook) -- the rewrite is
rolled back to ``HEAD`` and nothing is committed.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from task_scope import _git_env  # noqa: E402

import low_doc_parts  # noqa: E402  (the one list of the Low-doc parts)

# The cold Low doc (skill-context-diet D5b) is scanned too: the next free `L` counts past the
# highest `L` in all three, and a placeholder may be filed in the low file itself. A repo without
# the file is tolerated exactly as before — every reader here uses ``doc.get(path, "")``.
ISSUE_FILES = (
    "three-pillars-docs/known_issues.md",           # index 0: `_compute` checks this one
    "three-pillars-docs/known_issues_resolved.md",
    *low_doc_parts.PART_RELS,                      # part 1, then _2 … _9
)

DEFINED = re.compile(r"^### ([HML])-new-([a-z0-9]+(?:-[a-z0-9]+)*)(?=[ \t:(])", re.M)
NUMBERED = re.compile(r"^### ([HML])([0-9]+)\b", re.M)
PLACEHOLDER = re.compile(r"(?<![A-Za-z0-9-])([HML])-new-([a-z0-9]+(?:-[a-z0-9]+)*)(?![A-Za-z0-9])")


def _heading_max(*docs: dict) -> dict:
    """Per-letter max of ``NUMBERED`` headings in ``ISSUE_FILES`` across ``docs``."""
    maxes: dict = {}
    for doc in docs:
        for path in ISSUE_FILES:
            for m in NUMBERED.finditer(doc.get(path, "")):
                letter, num = m.group(1), int(m.group(2))
                if num > maxes.get(letter, 0):
                    maxes[letter] = num
    return maxes


def _heading_set(doc: dict) -> set:
    found = set()
    for path in ISSUE_FILES:
        for m in NUMBERED.finditer(doc.get(path, "")):
            found.add((m.group(1), int(m.group(2))))
    return found


def _defined_keys(doc: dict) -> set:
    """The ``<S>-new-<slug>`` keys headed (``DEFINED``) in ``doc``'s ``ISSUE_FILES``."""
    return {f"{m.group(1)}-new-{m.group(2)}"
            for path in ISSUE_FILES for m in DEFINED.finditer(doc.get(path, ""))}


def inherited_numbered(head: dict, base: dict, merge_base: dict) -> set:
    """Placeholder keys head inherited from ``merge_base`` that ``base`` no longer heads:
    the base numbered (or dropped) them, so only a base-sync clears them from head."""
    return (_defined_keys(merge_base) - _defined_keys(base)) & _defined_keys(head)


def _compute(head: dict, base: dict, merge_base: dict):
    """Returns ``(assign, files)``: ``assign`` maps old id/placeholder -> new id;
    ``files`` maps path -> new text for every path head's text changed."""
    if ISSUE_FILES[0] not in head:
        return {}, {}

    working = dict(head)
    next_free = _heading_max(head, base)
    assign: dict = {}

    collisions = sorted(_heading_set(head) & _heading_set(base) - _heading_set(merge_base))
    for letter, num in collisions:
        new_num = next_free.get(letter, 0) + 1
        next_free[letter] = new_num
        old_id, new_id = f"{letter}{num}", f"{letter}{new_num}"
        assign[old_id] = new_id
        pattern = re.compile(rf"(?<![A-Za-z0-9-]){old_id}(?![0-9])")
        for path, text in list(working.items()):
            if head.get(path) == merge_base.get(path):
                continue  # unchanged since merge_base: out of head's renumbering scope
            working[path] = pattern.sub(new_id, text)

    placeholder_order: list = []
    # Inherited and already numbered (or dropped) by the base: the merge brings its number in.
    seen: set = inherited_numbered(head, base, merge_base)
    for path in ISSUE_FILES:
        for m in DEFINED.finditer(working.get(path, "")):
            key = f"{m.group(1)}-new-{m.group(2)}"
            if key not in seen:
                seen.add(key)
                placeholder_order.append((m.group(1), key))
    for letter, key in placeholder_order:
        new_num = next_free.get(letter, 0) + 1
        next_free[letter] = new_num
        assign[key] = f"{letter}{new_num}"

    if assign:
        def repl(m):
            return assign.get(f"{m.group(1)}-new-{m.group(2)}", m.group(0))
        for path, text in list(working.items()):
            working[path] = PLACEHOLDER.sub(repl, text)

    files = {p: t for p, t in working.items() if head.get(p) != t}
    return assign, files


def plan_numbering(head: dict, *, base: dict | None = None, merge_base: dict | None = None) -> dict:
    """Pure planner: see module docstring. Only placeholder/branch files; never mutates inputs."""
    _, files = _compute(head, base or {}, merge_base or {})
    return files


class NumberIssuesError(RuntimeError):
    """A git invocation needed by the CLI failed."""


def _run_git(repo: Path, args: list) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], env=_git_env(),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise NumberIssuesError(detail[-1] if detail else f"git {' '.join(args)} failed")
    return proc.stdout


def _show(repo: Path, ref: str, path: str):
    """``path``'s text at ``ref``, or None when absent or not UTF-8. Read as bytes so CRLF line
    endings survive; a non-UTF-8 file cannot hold a placeholder this pass rewrites, so it is
    skipped (``numbering_carry._texts`` skips it the same way)."""
    proc = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], env=_git_env(),
                          capture_output=True)
    if proc.returncode != 0:
        return None
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _doc_at(repo: Path, ref: str, paths: list) -> dict:
    doc = {}
    for path in paths:
        text = _show(repo, ref, path)
        if text is not None:
            doc[path] = text
    return doc


# The citation scope: every committed `.md` file in the WHOLE tree (issue-id-placeholders.md:
# "the numbering pass rewrites every occurrence of the placeholder across the tree"), not just
# `three-pillars-docs/` -- CLAUDE.md and skill docs cite issue IDs too. `--full-tree` keeps the
# listing repo-wide whatever the cwd. `numbering_carry._tree_entries` re-derives the plan over
# this SAME scope, so the two must change together.
LS_TREE_SCOPE = ("ls-tree", "-r", "--full-tree")


def _head_paths(repo: Path) -> list:
    # `-z`: without it core.quotePath C-quotes a non-ASCII name, which then fails the `.md`
    # test, so the file drops out of the plan while `numbering_carry` (also `-z`) keeps it.
    out = _run_git(repo, [*LS_TREE_SCOPE, "-z", "--name-only", "HEAD"])
    return [p for p in out.split("\0") if p.endswith(".md")]


def base_read_paths(head_paths) -> list:
    """The paths read at the base and at the merge-base: HEAD's ``.md`` paths plus
    ``ISSUE_FILES``, whether or not HEAD has them. A branch cut before ``known_issues_resolved.md``
    existed must still see an ID the base holds only there, or the pass reissues it (the planner
    never writes a file HEAD lacks: ``_compute`` emits head's paths only).
    ``numbering_carry._certify`` reads its base and merge-base over this SAME set, so the CLI and
    the certifier cannot drift. Both readers skip a path the ref does not hold."""
    paths = list(head_paths)
    paths.extend(p for p in ISSUE_FILES if p not in paths)
    return paths


def _resolve_base(repo: Path, base: str) -> str:
    """``origin/<base>`` when that remote-tracking ref exists, else ``base`` itself."""
    if not base.startswith(("origin/", "refs/")):
        try:
            return _run_git(repo, ["rev-parse", "--verify", "--quiet",
                                   f"refs/remotes/origin/{base}^{{commit}}"]).strip()
        except NumberIssuesError:
            pass
    return _run_git(repo, ["rev-parse", "--verify", f"{base}^{{commit}}"]).strip()


def _commit(repo: Path, files: dict, head: dict, base_sha: str) -> int:
    """Stage + commit ``files``; on failure roll the rewrite back to ``HEAD`` and return 4."""
    try:
        _run_git(repo, ["add", "--", *sorted(files)])
        message = f"chore(ids): number issue IDs\n\nNumbered-against: {base_sha}\n"
        # Pathspec form commits only the planned files, never whatever else is staged.
        _run_git(repo, ["commit", "-m", message, "--", *sorted(files)])
    except NumberIssuesError as exc:
        try:
            _run_git(repo, ["reset", "-q", "--", *sorted(files)])
        except NumberIssuesError:
            pass
        for path in files:  # the dirty-tree check proved these held HEAD's text
            (repo / path).write_bytes(head[path].encode("utf-8"))
        print(f"number_issues: error: commit failed, rewrite rolled back: {exc}", file=sys.stderr)
        return 4
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="number_issues.py",
                                      description="number placeholder known-issue IDs")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    write = args.write or args.commit
    # ls-tree paths are root-relative, so every write, status and pathspec below must run
    # from the top level, not from a subdirectory `--repo` (the default `.` included).
    try:
        repo = Path(_run_git(Path(args.repo), ["rev-parse", "--show-toplevel"]).strip())
    except NumberIssuesError as exc:
        print(f"number_issues: error: not a git work tree: {exc}", file=sys.stderr)
        return 2

    try:
        base_sha = _resolve_base(repo, args.base)
    except NumberIssuesError as exc:
        print(f"number_issues: error: unresolvable --base: {exc}", file=sys.stderr)
        return 2

    try:
        paths = _head_paths(repo)
    except NumberIssuesError as exc:
        print(f"number_issues: error: {exc}", file=sys.stderr)
        return 2

    head = _doc_at(repo, "HEAD", paths)
    base_paths = base_read_paths(paths)
    base_doc = _doc_at(repo, base_sha, base_paths)
    try:
        merge_base_sha = _run_git(repo, ["merge-base", "HEAD", base_sha]).strip()
        merge_base_doc = _doc_at(repo, merge_base_sha, base_paths)
    except NumberIssuesError:
        merge_base_doc = {}

    assign, files = _compute(head, base_doc, merge_base_doc)
    inherited = sorted(inherited_numbered(head, base_doc, merge_base_doc))

    if not write:
        print(json.dumps({"assign": assign, "files": sorted(files), "inherited": inherited}))
        return 0

    if inherited:
        print(f"number_issues: left as inherited, the base already numbered them: "
              f"{', '.join(inherited)}; run /tp-merge-from-main to merge its numbers in",
              file=sys.stderr)

    if not files:
        return 0

    watched = sorted(set(ISSUE_FILES) | set(files))
    dirty = _run_git(repo, ["status", "--porcelain", "--", *watched])
    if dirty.strip():
        print("number_issues: dirty tree, refusing to write (commit or stash first)", file=sys.stderr)
        return 3

    for path, text in files.items():
        (repo / path).write_bytes(text.encode("utf-8"))

    if not args.commit:
        return 0

    return _commit(repo, files, head, base_sha)


if __name__ == "__main__":
    sys.exit(main())
