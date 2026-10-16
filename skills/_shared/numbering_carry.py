"""numbering_carry.py -- certify a `number_issues.py --commit` commit as a no-op carry link.

design: basesync-autoresolve-coverage (Task 2.5). stdlib-only, total, never raises.

A numbering commit (subject ``chore(ids): number issue IDs``, trailer ``Numbered-against:
<sha>``) is mechanical: re-running ``number_issues.plan_numbering`` on its parent's tree
reproduces it byte for byte. ``certify_numbering_link`` re-derives that plan from git objects
alone and accepts the link only when the commit changed exactly the planned files to exactly
the planned bytes. The trailer picks the base the plan is rebuilt against, so (like a merge
commit's second parent in ``base_sync_cert._cond1_merge_shape``) it must be an ancestor of
``origin/<base_ref>`` -- a forged trailer cannot choose its own base. ``base_sync_cert`` calls
this ahead of its merge-shape condition, so the approval and proof chain crosses the commit.

``git`` is the seam of ``base_sync_cert``: ``git(args) -> (rc, out, err)``.
"""
from __future__ import annotations

import os
import re
import sys

_SHARED = os.path.dirname(os.path.abspath(__file__))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from base_sync_plumbing import _parse_dashz_names, _redecode_strict_utf8  # noqa: E402
from number_issues import LS_TREE_SCOPE, base_read_paths, plan_numbering  # noqa: E402

SUBJECT = "chore(ids): number issue IDs"
_TRAILER = "Numbered-against:"
_VALUE_RE = re.compile(r"^(none|[0-9a-f]{40}|[0-9a-f]{64})$")
_REGULAR_MODES = ("100644", "100755")


def numbering_trailer(git, h1: str):
    """The ``Numbered-against:`` value of ``h1`` when its subject is the numbering subject, else
    ``None``. A numbering-subject commit whose trailer is absent, repeated or not ``none`` /
    a full lowercase sha yields ``""`` so the caller still treats it as a (failing) numbering
    attempt rather than an ordinary commit."""
    try:
        rc, out, _err = git(["cat-file", "commit", h1])
        if rc != 0 or not isinstance(out, str) or "\n\n" not in out:
            return None
        message = out.split("\n\n", 1)[1]
        lines = message.split("\n")
        if lines[0] != SUBJECT:
            return None
        values = [ln[len(_TRAILER):].strip() for ln in lines[1:] if ln.startswith(_TRAILER)]
        if len(values) != 1:
            return ""
        value = values[0].lower()
        return value if _VALUE_RE.match(value) else ""
    except Exception:
        return None


def _tree_entries(git, rev: str) -> dict:
    """``{path: (mode, oid)}`` of the regular ``.md`` files anywhere in the tree at ``rev`` (the
    CLI's ``number_issues.LS_TREE_SCOPE``, so a placeholder cited outside ``three-pillars-docs``
    is planned here exactly as the CLI rewrote it). Raises ``ValueError`` on a git failure or an
    unrecognised ``ls-tree`` record."""
    rc, out, _err = git([*LS_TREE_SCOPE, "-z", rev])
    if rc != 0:
        raise ValueError("git error: ls-tree failed")
    entries: dict = {}
    for record in out.split("\x00"):
        if not record:
            continue
        meta, sep, path = record.partition("\t")
        fields = meta.split(" ")
        if not sep or len(fields) != 3:
            raise ValueError("ls-tree output shape unrecognized")
        mode, kind, oid = fields
        path = _redecode_strict_utf8(path)
        if kind == "blob" and mode in _REGULAR_MODES and path.endswith(".md"):
            entries[path] = (mode, oid)
    return entries


def _blob_bytes(git, oid: str) -> bytes:
    rc, out, _err = git(["cat-file", "blob", oid])
    if rc != 0:
        raise ValueError("git error: cat-file blob failed")
    return out.encode("utf-8", "surrogateescape")


def _texts(git, entries: dict, paths, cache: dict) -> dict:
    """Strict-UTF-8 text of each of ``paths`` present in ``entries``; ``cache`` keys on oid. A
    non-UTF-8 blob is skipped, as ``number_issues._show`` skips it, so both plan the same files."""
    docs: dict = {}
    for path in paths:
        if path not in entries:
            continue
        oid = entries[path][1]
        if oid not in cache:
            try:
                cache[oid] = _blob_bytes(git, oid).decode("utf-8")
            except UnicodeDecodeError:
                cache[oid] = None
        if cache[oid] is not None:
            docs[path] = cache[oid]
    return docs


def _merge_base_entries(git, h0: str, base: str) -> dict:
    rc, out, _err = git(["merge-base", h0, base])
    if rc == 1 and not out.strip():
        return {}               # no common ancestor: number_issues plans against {}
    if rc != 0:
        raise ValueError("git error: merge-base failed")
    return _tree_entries(git, out.strip())


def _certify(git, h0: str, h1: str, trailer: str, base_ref: str) -> tuple:
    rc, out, _err = git(["rev-list", "--parents", "-n1", h1])
    parents = out.strip().split()[1:] if rc == 0 else None
    if parents is None:
        return False, "git error: rev-list --parents failed"
    if len(parents) != 1 or parents[0].lower() != h0.lower():
        return False, "numbering: commit is not a single-parent child of h0"
    if not _VALUE_RE.match(trailer):
        return False, "numbering: malformed or missing Numbered-against trailer"
    if trailer != "none":
        rc2, _o, _e = git(["merge-base", "--is-ancestor", trailer, f"origin/{base_ref}"])
        if rc2 == 1:
            return False, "Numbered-against sha not on base branch"
        if rc2 != 0:
            return False, "git error: merge-base --is-ancestor failed"

    cache: dict = {}
    head_entries = _tree_entries(git, h0)
    head = _texts(git, head_entries, head_entries, cache)
    base: dict = {}
    merge_base: dict = {}
    if trailer != "none":
        # The CLI's base/merge-base read set: head's paths plus the issue files HEAD may lack.
        base_paths = base_read_paths(head_entries)
        base = _texts(git, _tree_entries(git, trailer), base_paths, cache)
        merge_base = _texts(git, _merge_base_entries(git, h0, trailer), base_paths, cache)
    plan = plan_numbering(head, base=base, merge_base=merge_base)
    if not plan:
        return False, "numbering: the parent tree yields an empty numbering plan"

    rc3, names, _e3 = git(["diff", "--name-only", "--no-renames", "-z", h0, h1])
    changed = _parse_dashz_names(names) if rc3 == 0 else None
    if changed is None:
        return False, "git error: diff failed"
    if set(changed) != set(plan):
        return False, "numbering: commit changed files other than the numbering plan's"
    result_entries = _tree_entries(git, h1)
    for path, text in plan.items():
        if path not in result_entries or result_entries[path][0] != head_entries[path][0]:
            return False, "numbering: planned file missing or mode changed at h1"
        if _blob_bytes(git, result_entries[path][1]) != text.encode("utf-8"):
            return False, "numbering: committed bytes differ from the numbering plan"
    return True, ""


def certify_numbering_link(git, h0: str, h1: str, trailer: str, base_ref: str) -> tuple:
    """``(ok, reason)``: ``h1`` is exactly the numbering commit the CLI makes on ``h0``. Never raises."""
    try:
        return _certify(git, h0, h1, trailer, base_ref)
    except (ValueError, UnicodeDecodeError):
        return False, "numbering: unreadable or non-UTF-8 content, or a git error"
    except Exception:
        return False, "internal error during numbering certification"
