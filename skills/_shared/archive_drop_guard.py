"""archive_drop_guard.py — refuse an archive prune that would lose uncommitted work.

`archive_allowlist.apply` removes drops with `git rm -f` (design-complete runs
it after its staged `git mv`, which a plain `git rm` refuses), and `-f` skips
git's lost-work check. `uncommitted_drops` is that check: the drops whose
content no commit holds. `apply` raises `UncommittedDropError` for them and
removes nothing.

The worktree side of the check is `git diff` (index vs worktree), which reads
the file the way `git add` would — with the index consulted, so a CRLF blob
under `text=auto` is not "changed" by the normalisation `git hash-object`
would apply on its own. `git diff` skips index entries flagged
`--assume-unchanged` / `--skip-worktree`; only those are hashed by content.

The error's remedy only names actions that leave the rest of the index alone:
at design-complete the index holds step 6c's staged `git mv`, and anything
that resets the index wholesale would revert that rename and turn the re-run
into an empty plan. Stdlib only.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from task_scope import _git_env

_CHUNK = 200


class UncommittedDropError(RuntimeError):
    """Some drops hold work no commit has: `apply` refused and removed nothing.

    `paths` are the refused drops; `never_committed` the subset no commit
    holds any version of (staged as new, never committed), which the
    committed-content remedy cannot clear."""

    def __init__(self, paths: list[str], never_committed: list[str] = ()):
        self.paths = list(paths)
        self.never_committed = [p for p in never_committed if p in self.paths]
        msg = (
            f"refusing to remove {len(self.paths)} drop(s) with uncommitted content "
            "(no commit holds it); nothing was removed. For each path: keep any edit you want by "
            "copying the file out of the repo, then put the committed content back "
            "at that path only — `git restore -- <path>` for an unstaged edit; for a "
            "staged edit, `git show HEAD:<committed path> > <path>` then "
            "`git add -- <path>`. Then re-run. Leave the rest of the index as it is: "
            "it holds the staged `git mv` of the design dir.")
        if self.never_committed:
            msg += (
                " No commit holds any version of "
                + ", ".join(self.never_committed)
                + ": for those, `git rm --cached -- <path>` (the file stays on disk, "
                "untracked; the plan keeps it and step 6f stages it) or commit it.")
        super().__init__(msg + " Paths: " + ", ".join(self.paths))


def _git_z(root: Path, args: list[str], check: bool = True) -> list[str]:
    """NUL-split git output; a failure raises (fail closed) unless `check=False`."""
    r = subprocess.run(["git", "-C", str(root), "--literal-pathspecs", *args],
                       capture_output=True, text=True, env=_git_env(), check=check)
    return [x for x in r.stdout.split("\0") if x] if r.returncode == 0 else []


def _chunked(root: Path, args: list[str], paths: list[str]) -> list[str]:
    out: list[str] = []
    for i in range(0, len(paths), _CHUNK):
        out += _git_z(root, [*args, "--", *paths[i:i + _CHUNK]])
    return out


def _hidden(root: Path, paths: list[str]) -> set[str]:
    """Paths whose index entry `git diff` would skip: `git ls-files -v` tags
    other than `H` (`h` assume-unchanged, `S`/`s` skip-worktree)."""
    hidden = set()
    for e in _chunked(root, ["ls-files", "-v", "-z"], paths):
        tag, _, path = e.partition(" ")
        if tag != "H":
            hidden.add(path)
    return hidden


def _worktree_blobs(root: Path, paths: list[str]) -> dict[str, str]:
    """Blob id of each file's working-tree content (`git hash-object`, clean
    filters applied, the index not consulted); a symlink hashes its target
    text. A hashing failure raises — the caller cannot evaluate the drop."""
    out: dict[str, str] = {}
    files = []
    for p in paths:
        full = root / p
        if full.is_symlink():
            r = subprocess.run(["git", "-C", str(root), "hash-object", "--stdin"],
                               input=os.readlink(full).encode(), capture_output=True,
                               env=_git_env(), check=True)
            out[p] = r.stdout.decode().strip()
        else:
            files.append(p)
    for i in range(0, len(files), _CHUNK):
        chunk = files[i:i + _CHUNK]
        r = subprocess.run(["git", "-C", str(root), "hash-object", "--", *chunk],
                           capture_output=True, text=True, env=_git_env(), check=True)
        out.update(zip(chunk, r.stdout.split()))
    return out


def _content_changed(root: Path, paths: list[str]) -> set[str]:
    """Paths whose working-tree content differs from the index as `git add`
    would see it: a `git diff --numstat` entry that is not `0 0` (a mode-only
    change counts 0/0 and is not content; a binary change shows `-`)."""
    changed = set()
    for e in _chunked(root, ["diff", "--numstat", "--no-renames", "--no-ext-diff", "-z"], paths):
        added, deleted, path = e.split("\t", 2)
        if (added, deleted) != ("0", "0"):
            changed.add(path)
    return changed


def _never_committed(root: Path, paths: set[str]) -> list[str]:
    """The `paths` staged as new against HEAD (status `A` with renames
    detected): no commit holds any version of them."""
    entries = _git_z(root, ["diff", "--cached", "--name-status", "--find-renames", "-z"],
                     check=False)
    out, i = [], 0
    while i < len(entries):
        status, path = entries[i], entries[i + 1]
        i += 3 if status[0] in "RC" else 2  # R/C carry an old and a new path
        if status[0] == "A" and path in paths:
            out.append(path)
    return sorted(out)


def uncommitted_drops(drops: list[str], repo_root: str | Path) -> list[str]:
    """The drops whose content no commit holds: `git rm -f` would lose it.

    A drop is uncommitted when its index blob is not a blob of HEAD's tree
    (no HEAD: every drop is), or its working-tree content differs from the
    index — by `git diff` for a normal entry, by content hash for an entry
    `git diff` skips (`--assume-unchanged` / `--skip-worktree`). A pure staged
    rename (the design-complete `git mv`) keeps HEAD's blob, so it passes; so
    does a drop already deleted from the worktree, or one whose only change is
    its mode. A drop that is now something other than a file or symlink cannot
    be evaluated and is refused.
    """
    root = Path(repo_root)
    head_blobs = {e.split("\t", 1)[0].split()[2]
                  for e in _git_z(root, ["ls-tree", "-r", "-z", "HEAD"], check=False)}
    index: dict[str, str] = {}
    for e in _chunked(root, ["ls-files", "-s", "-z"], drops):
        meta, path = e.split("\t", 1)
        index[path] = meta.split()[1]
    bad = {p for p in drops if index.get(p) is None or index[p] not in head_blobs}
    present = [p for p in drops if p not in bad and os.path.lexists(root / p)]
    bad.update(p for p in present
               if not ((root / p).is_file() or (root / p).is_symlink()))
    present = [p for p in present if p not in bad]
    hidden = _hidden(root, present)
    hashed = _worktree_blobs(root, [p for p in present if p in hidden])
    bad.update(p for p, blob in hashed.items() if blob != index[p])
    bad.update(_content_changed(root, [p for p in present if p not in hidden]))
    return sorted(bad)


def never_committed_of(drops: list[str], repo_root: str | Path) -> list[str]:
    """Of `drops`, those staged as new with no committed version (for the
    error's remedy)."""
    return _never_committed(Path(repo_root), set(drops))
