#!/usr/bin/env python3
"""hardcap_backstop.py — the B3 hard-cap backstop over a merge report.

design: basesync-generator-catalog (B3, Behavior 11). An auto-resolved living doc can be STAGED over
its `file_size_guard` HARD cap, and then the commit hook only warns `rollover-due`. This module runs
once over the driver's report and acts on exactly one case: the MERGE pushed the doc over the cap, so
NEITHER input side was over it. Everything else keeps today's outcome (staged, no roll): a doc
already over the cap on either side is not this merge's doing, and neither is one whose side cannot
be read from git.

For an in-scope doc whose archive is not conflicted it snapshots the doc and its archive, rolls the
oldest History entries across (`doc_rollover.roll_to_cap`) and accepts only when the doc is then at
or under the cap AND `verify.verify` finds no drop over the doc plus archive pair; both files are
then staged and the outcome gains `hard-cap-rollover`. A roll that moves nothing (an empty
`## History`) is undone and the doc stays staged: deferring it would add a stall for no gain. Any
other failure, an exception included, restores both snapshots, puts git's unmerged stages and
markers back (`git checkout -m`, the resolve-undo `merge_driver.resolve_generated` uses) and moves
the path from `auto_resolved` to `deferred` with a reason naming the char count and the cap.

A Low part (`low_doc_parts.is_part_rel`) has no archive: when the merge pushed an auto-resolved part
over `low_doc_parts.CAP` with neither side over it, `low_doc_parts.split_part` moves its trailing
`### L` entries into the next part, and the split is accepted only when both parts fit, the heading
count over the pair is unchanged and `verify.verify` finds no drop; both parts are then staged and
the outcome gains `low-part-split`, otherwise both files are restored and the part is deferred.

An accepted roll keeps its archive snapshot on the report (`ROLLED_ATTR`, not a dataclass field, so
it never reaches the JSON). A later pass that hands the doc back (the 2.4 count check) calls
`undo_rollover` first: `git checkout -m` restores only the doc, and the rolled History would
otherwise sit in BOTH the restored doc and the staged archive.

It never raises and prints nothing (the driver's stdout is one JSON document). Stdlib only.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_moves  # noqa: E402  # `_show` (ls-tree, then show) and `_repo_git`
import verify  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import doc_rollover  # noqa: E402
import file_size_guard  # noqa: E402
import living_doc_archive  # noqa: E402
import low_doc_parts  # noqa: E402

RESOLVED_CLASS = "hard-cap-rollover"
LOW_SPLIT_CLASS = "low-part-split"
ROLLED_ATTR = "_hard_cap_rolled"    # {doc rel: (archive rel, archive bytes before the roll | None)}


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _read(path: Path):
    """The file's bytes, or None when it does not exist (a snapshot of an absent archive)."""
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, data) -> None:
    if data is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _in_scope(git, rel: str, cap: int) -> bool:
    """True when NEITHER side of the open merge is over `cap`. Ours is `HEAD`, theirs `MERGE_HEAD`,
    each read like `archive_moves._show`: an empty listing is an absent path (0 chars, in scope);
    any git failure is None and out of scope, so no roll runs on a state it could not read."""
    show = archive_moves._show(git)
    for rev in ("HEAD", "MERGE_HEAD"):
        side = show(rev, rel)
        if side is None or len(side) > cap:
            return False
    return True


def _outcome(report, rel: str):
    return next((o for o in getattr(report, "outcomes", []) or [] if o.get("path") == rel), None)


def _defer(report, rel: str, reason: str) -> None:
    """Move `rel` from `auto_resolved` to `deferred` and record why on its outcome."""
    if rel in report.auto_resolved:
        report.auto_resolved.remove(rel)
    if rel not in report.deferred:
        report.deferred.append(rel)
    o = _outcome(report, rel)
    if o is not None:
        o["action"], o["reason"] = "deferred", reason


def _hand_back(git, report, rel: str, reason: str) -> None:
    """`git checkout -m` re-creates the unmerged stages and the markers that `git add` cleared, then
    the path is deferred. When git refuses, the reason says the markers are NOT back."""
    rc, _out, err = git(["checkout", "-m", "--", rel])
    if rc != 0:
        reason += f" (could not restore the conflict markers: {err.strip()[:200]})"
    _defer(report, rel, reason)


def undo_rollover(repo: str, report, rel: str) -> str:
    """Put back the archive an accepted roll of `rel` wrote: its pre-roll bytes (or its absence),
    re-staged with `git add -A` so the index matches, and drop `hard-cap-rollover` from the doc's
    outcome. Call it BEFORE `_hand_back(rel)`. Returns a note for the deferral reason ('' when no
    roll ran or the undo was clean)."""
    entry = (getattr(report, ROLLED_ATTR, None) or {}).pop(rel, None)
    if entry is None:
        return ""
    archive_rel, pre_arch = entry
    _restore(Path(repo) / archive_rel, pre_arch)
    rc, _out, err = archive_moves._repo_git(repo)(["add", "-A", "--", archive_rel])
    o = _outcome(report, rel)
    if o is not None and RESOLVED_CLASS in (o.get("resolved_classes") or []):
        o["resolved_classes"].remove(RESOLVED_CLASS)
    if rc != 0:
        return f" (could not re-stage the restored {archive_rel}: {err.strip()[:200]})"
    return f" (hard-cap rollover into {archive_rel} undone)"


def _roll(repo: str, rel: str):
    with contextlib.redirect_stdout(io.StringIO()):     # the roll prints CONDENSE-NEEDED
        return doc_rollover.roll_to_cap(repo, rel)


def _split_failure(repo: str, rel: str, nxt: str, pre, pre_next, note: str):
    """Run the split and judge it: None when accepted (both parts fit, the `### L` count over the
    pair is unchanged, zero-drop re-verify clean, pair staged), else the reason it failed."""
    cap, root = low_doc_parts.CAP, Path(repo)
    low_doc_parts.split_part(root, rel)
    post, post_next = _read(root / rel) or b"", _read(root / nxt) or b""
    if len(_text(post)) > cap or len(_text(post_next)) > cap:
        return (f"Low part split left {len(_text(post))} and {len(_text(post_next))} chars, "
                f"over the {cap}-char hard cap ({note})")
    before = _text(pre) + "\n" + _text(pre_next or b"")
    after = _text(post) + "\n" + _text(post_next)
    if low_doc_parts.count_lows(before) != low_doc_parts.count_lows(after):
        return f"Low part split changed the '### L' heading count ({note})"
    result = verify.verify(before, "", after, base=None, mechanical_applied=True)
    if not result.ok:
        return f"Low part split failed the zero-drop re-verify ({len(result.dropped)} dropped; {note})"
    rc, _out, err = archive_moves._repo_git(repo)(["add", "--", rel, nxt])
    if rc != 0:
        return f"Low part split could not stage the pair ({err.strip()[:200]}; {note})"
    return None


def _backstop_low_part(repo: str, report, rel: str) -> None:
    """The Low arm: split the over-cap part into the next part (see the module docstring)."""
    path, cap = Path(repo) / rel, low_doc_parts.CAP
    pre = _read(path)
    if pre is None or len(_text(pre)) <= cap:
        return                                          # at or under the cap: nothing to do
    git = archive_moves._repo_git(repo)
    if not _in_scope(git, rel, cap):
        return                                          # today's outcome: staged, hook warns
    note = f"{len(_text(pre))} chars, over the {cap}-char hard cap"
    nxt = low_doc_parts.next_part_rel(rel)
    if nxt is None:
        _hand_back(git, report, rel, f"{rel} is the last Low part, so no split ran ({note})")
        return
    if nxt in report.conflicted and nxt not in report.auto_resolved:
        _hand_back(git, report, rel, f"{nxt} is conflicted, so no Low part split ran ({note})")
        return
    nxt_path = Path(repo) / nxt
    pre_next = _read(nxt_path)                          # None when the next part does not exist yet
    try:
        failure = _split_failure(repo, rel, nxt, pre, pre_next, note)
    except Exception as e:                              # noqa: BLE001 — totality, snapshots below
        failure = f"Low part split raised {type(e).__name__}: {e} ({note})"
    if failure is not None:
        _restore(path, pre)
        _restore(nxt_path, pre_next)
        _hand_back(git, report, rel, failure)
        return
    o = _outcome(report, rel)
    if o is not None:
        o.setdefault("resolved_classes", []).append(LOW_SPLIT_CLASS)


def _backstop_one(repo: str, report, rel: str) -> None:
    if low_doc_parts.is_part_rel(rel):
        _backstop_low_part(repo, report, rel)
        return
    archive_rel = living_doc_archive.ARCHIVES.get(rel)
    if archive_rel is None:
        return
    live, archive = Path(repo) / rel, Path(repo) / archive_rel
    pre_live = _read(live)
    cap = file_size_guard.char_caps(rel, False)[1]
    if pre_live is None or len(_text(pre_live)) <= cap:
        return                                          # at or under the cap: nothing to do
    git = archive_moves._repo_git(repo)
    if not _in_scope(git, rel, cap):
        return                                          # today's outcome: staged, hook warns
    note = f"{len(_text(pre_live))} chars, over the {cap}-char hard cap"
    if archive_rel in report.conflicted and archive_rel not in report.auto_resolved:
        _hand_back(git, report, rel, f"{archive_rel} is conflicted, so no hard-cap rollover ran "
                                     f"({note})")
        return
    pre_arch = _read(archive)
    try:
        rolled = _roll(repo, rel)
        if rolled.moved == 0:                           # nothing to roll: keep today's outcome
            _restore(live, pre_live)
            _restore(archive, pre_arch)
            return
        post_live, post_arch = _read(live) or b"", _read(archive) or b""
        failure = None
        if len(_text(post_live)) > cap:
            failure = (f"hard-cap rollover moved {rolled.moved} entries and left "
                       f"{len(_text(post_live))} chars, over the {cap}-char hard cap")
        else:
            result = verify.verify(_text(pre_live) + "\n" + _text(pre_arch or b""), "",
                                   _text(post_live) + "\n" + _text(post_arch),
                                   base=None, mechanical_applied=True)
            if not result.ok:
                failure = (f"hard-cap rollover failed the zero-drop re-verify "
                           f"({len(result.dropped)} dropped; {note})")
        if failure is None:
            rc, _out, err = git(["add", "--", rel, archive_rel])
            if rc != 0:
                failure = f"hard-cap rollover could not stage the pair ({err.strip()[:200]}; {note})"
    except Exception as e:                              # noqa: BLE001 — totality, snapshots below
        failure = f"hard-cap rollover raised {type(e).__name__}: {e} ({note})"
    if failure is not None:
        _restore(live, pre_live)
        _restore(archive, pre_arch)
        _hand_back(git, report, rel, failure)
        return
    rolled = getattr(report, ROLLED_ATTR, None)
    if rolled is None:
        rolled = {}
        setattr(report, ROLLED_ATTR, rolled)
    rolled[rel] = (archive_rel, pre_arch)               # `undo_rollover` if a later pass hands back
    o = _outcome(report, rel)
    if o is not None:
        o.setdefault("resolved_classes", []).append(RESOLVED_CLASS)


def apply_hard_cap_backstop(repo, report) -> None:
    """Roll-and-re-verify every auto-resolved living doc the MERGE pushed over its hard cap, and
    defer the ones that cannot be made to fit. Never raises, never prints."""
    try:
        paths = list(report.auto_resolved)
    except Exception:                                   # noqa: BLE001 — nothing may escape
        return
    for rel in paths:
        try:
            _backstop_one(str(repo), report, rel)
        except Exception as e:                          # noqa: BLE001 — a bug here defers, not raises
            try:
                _defer(report, rel, f"hard-cap backstop raised — needs human "
                                    f"({type(e).__name__}: {e})")
            except Exception:                           # noqa: BLE001
                pass
