#!/usr/bin/env python3
"""An atom a side moved into its archive is not a drop (basesync-autoresolve-coverage, Behavior 8).

`verify.verify` reads ours ∪ theirs against the result, so a side that moves an entry or a History
line out of a living doc into its archive (`living_doc_archive.ARCHIVES`) looks like a drop, and
the proof can never carry across that sync. `verify_with_moves` takes such an atom off the drop
list only when EVERY condition of the fail-closed rule holds; any other drop stays, and any git,
decode or parse failure leaves the drop. Per dropped atom and removing side X (theirs, then ours;
Y is the other side):

  1. the atom is in the merge-base copy of the live doc, and X's live doc no longer holds it;
  2. every line of the base copy that yields the atom has a block (the line, or for a `### `
     heading its lines up to the next `#`-`###` heading) that the same cut yields, with equal
     count, from Y's copy. Equality of the cut block, never a substring;
  3. X's archive holds the atom (exact text) or, for a `### <H|M|L><n>` heading, a heading with the
     same ID that X's live doc does not hold, and the base archive held neither (the copy is new
     in this sync window). Several yielding lines need that many archive copies.

An archive absent at a rev reads as empty text; any other git failure makes the whole loader
`None`. A result with no drops never calls the loader. Not `skills/_shared/verify_moves.py`
(the verbatim move verifier for a docs archival commit). Stdlib only.
"""
from __future__ import annotations

import dataclasses
import functools
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "_shared"))
from living_doc_archive import ARCHIVES  # noqa: E402
from verify import DROPS_DETECTED, VERIFIED, VerifyResult, atoms, verify  # noqa: E402

ID_HEADING = re.compile(r"^### ([HML][0-9]+)(?![0-9])", re.M)
_HEADING = re.compile(r"#{1,3}(?:\s|$)")


@dataclass(frozen=True)
class ArchiveTexts:
    """The archive file's text at the merge base and at each side; `None` = unreadable."""

    base: str | None
    ours: str | None
    theirs: str | None


@functools.lru_cache(maxsize=16)
def _scan(text: str):
    return tuple((ln, frozenset(atoms(ln))) for ln in text.splitlines(keepends=True))


def _yielding(text: str, atom) -> list[tuple[str, str]]:
    """(yielding line, its block) for each line whose own atoms include `atom`. A `### ` line's
    block runs to the next `#`-`###` heading; any other line is its own block."""
    scanned = _scan(text)
    out = []
    for i, (line, keys) in enumerate(scanned):
        if atom not in keys:
            continue
        j = i + 1
        while line.startswith("### ") and j < len(scanned) and not _HEADING.match(scanned[j][0]):
            j += 1
        out.append((line, "".join(ln for ln, _ in scanned[i:j])))
    return out


def _unchanged_by(base_hits, y_live: str, atom) -> bool:
    """The other side's yielding blocks are exactly the base ones: equal count, equal bytes."""
    theirs = Counter(block for _, block in _yielding(y_live, atom))
    return bool(base_hits) and Counter(block for _, block in base_hits) == theirs


def _archived(atom, base_hits, x_live: str, x_arch: str, base_arch: str) -> bool:
    if atom in atoms(base_arch):
        return False
    if atom in atoms(x_arch) and len(_yielding(x_arch, atom)) >= len(base_hits):
        return True
    ids: Counter = Counter()
    for line, _ in base_hits:
        m = ID_HEADING.match(line)
        if m is None:
            return False
        ids[m.group(1)] += 1
    have, live, old = (Counter(ID_HEADING.findall(t)) for t in (x_arch, x_live, base_arch))
    return all(have[i] >= n and not live[i] and not old[i] for i, n in ids.items())


def moved_atoms(dropped, *, base: str, ours: str, theirs: str, archives) -> set:
    """The subset of `dropped` that one side moved from its living doc into its archive."""
    if archives is None or archives.base is None:
        return set()
    at_base, at_ours, at_theirs = atoms(base), atoms(ours), atoms(theirs)
    sides = ((at_theirs, theirs, archives.theirs, ours), (at_ours, ours, archives.ours, theirs))
    moved = set()
    for atom in dropped:
        if atom not in at_base:
            continue
        hits = _yielding(base, atom)
        for x_atoms, x_live, x_arch, y_live in sides:
            if (atom not in x_atoms and x_arch is not None and _unchanged_by(hits, y_live, atom)
                    and _archived(atom, hits, x_live, x_arch, archives.base)):
                moved.add(atom)
                break
    return moved


def verify_with_moves(base: str, ours: str, theirs: str, resolved: str, *,
                      mechanical_applied: bool, archives) -> VerifyResult:
    """`verify.verify` with the merge base, then drop the atoms a side moved into its archive. The
    base lets `verify` excuse a base atom one side retitled in place while the other left it alone,
    so only what is still dropped reaches the move rule. `archives` is a zero-argument loader
    returning `ArchiveTexts | None`, or None; it is called only when `verify` reports
    DROPS_DETECTED, and at most once."""
    r = verify(ours, theirs, resolved, base=base, mechanical_applied=mechanical_applied)
    if r.verdict != DROPS_DETECTED or archives is None:
        return r
    try:
        texts = archives()
    except Exception:  # a faulty loader must leave every drop in place, never crash the gate
        return r
    moved = moved_atoms(r.dropped, base=base, ours=ours, theirs=theirs, archives=texts)
    left = [atom for atom in r.dropped if atom not in moved]
    return dataclasses.replace(r, verdict=DROPS_DETECTED if left else VERIFIED, dropped=left)


def archives_at(path: str, revs, show):
    """`ArchiveTexts` of `path`'s archive at (base, ours, theirs) via `show(rev, archive_path)`
    (text, "" when absent, None on failure). None for a path with no archive or a failed read."""
    archive = ARCHIVES.get(path)
    if archive is None:
        return None
    texts = [show(rev, archive) for rev in revs]
    return None if any(t is None for t in texts) else ArchiveTexts(*texts)


def _strict(out: str):
    try:
        return out.encode("utf-8", "surrogateescape").decode("utf-8")
    except UnicodeError:
        return None


def _show(git):
    def show(rev: str, path: str):
        rc, out, _err = git(["ls-tree", "--full-tree", rev, "--", path])
        if rc != 0:
            return None
        if not out.strip():
            return ""                       # the archive does not exist at this rev
        if out.split("\t", 1)[0].split()[1:2] != ["blob"]:
            return None
        rc, out, _err = git(["show", f"{rev}:{path}"])
        return _strict(out) if rc == 0 else None
    return show


def seam_archives(git, path: str, sides):
    """Loader over the certifier's git seam `git(args) -> (rc, out, err)` for `sides` = (ours,
    theirs) revs and their single merge base. None when `sides` is None (the seam is not called)."""
    if sides is None:
        return None

    def load():
        if path not in ARCHIVES:
            return None
        rc, out, _err = git(["merge-base", "--all", *sides])
        shas = out.split()
        if rc != 0 or len(shas) != 1:
            return None
        return archives_at(path, (shas[0], *sides), _show(git))
    return load


def _repo_git(repo):
    def git(args):
        try:
            r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return (-1, "", "")
        return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
                r.stderr.decode("utf-8", "surrogateescape"))
    return git


def driver_archives(repo, path: str):
    """Loader for the merge driver: `HEAD`, `MERGE_HEAD` and their single merge base."""
    return seam_archives(_repo_git(repo), path, ("HEAD", "MERGE_HEAD"))
