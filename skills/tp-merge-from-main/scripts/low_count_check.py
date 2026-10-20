#!/usr/bin/env python3
"""low_count_check.py — the post-merge check on `known_issues.md`'s count line.

design: basesync-count-line-and-low-headroom (2.4)

`known_issues.md`'s count line (`keyed_classes.COUNT_LINE`, "249 Low issues → …") is the one line in
the Low-doc pair that BOTH sides rewrite, so the `low-count-line` class does not pick a side: it
computes `ours + theirs − base`. That arithmetic is the merge's own invention — neither input side
wrote the merged number. This check re-derives it from the thing the count describes: the `### L`
headings across the merged Low parts (`low_doc_parts.total_lows`). A count that does not match means
the merge lost, duplicated or mis-numbered an entry it should have kept, so the doc is handed back
(`hardcap_backstop._hand_back`: `git checkout -m` puts git's stages and markers back) and deferred —
a wrong count line is a silent drop of a whole Low, and the count is the only place it shows. The
hard-cap backstop runs first and may have rolled the doc's History into its archive; every hand-back
here undoes that roll first (`hardcap_backstop.undo_rollover`), or the rolled entries would sit in
both the restored doc and the staged archive.

Three arms leave the doc exactly as the resolve loop staged it: it was not auto-resolved (nothing of
ours to check); it has no count line or more than one (not this class's line); the merged line is
byte-identical to a line one of the sides wrote (that side's own text, not computed here). A Low part
that never resolved is its own arm: the count cannot be checked against a doc that is still
conflicted, so the doc defers rather than pass on an unchecked number.

It never raises and prints nothing (the driver's stdout is one JSON document). Stdlib plus siblings.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_moves  # noqa: E402  # `_show` (ls-tree, then show) and `_repo_git`
import hardcap_backstop  # noqa: E402  # `_hand_back`: markers back, then defer
import keyed_classes  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import low_doc_parts  # noqa: E402

KI_REL = "three-pillars-docs/known_issues.md"


def _count_lines(text: str) -> list[str]:
    """The lines of `text` that are count lines, in order."""
    return [ln for ln in text.splitlines() if keyed_classes.COUNT_LINE.match(ln)]


def _defer_ki(repo: str, git, report, reason: str) -> None:
    """Undo the backstop's roll of the doc (if any), then hand the doc back with `reason`."""
    try:
        reason += hardcap_backstop.undo_rollover(repo, report, KI_REL)
    except Exception as e:                              # noqa: BLE001 — the hand-back still runs
        reason += f" (hard-cap rollover undo raised {type(e).__name__}: {e})"
    hardcap_backstop._hand_back(git, report, KI_REL, reason)


def _check(repo: str, report, git) -> None:
    """The check itself, over a worktree whose KI was auto-resolved and staged."""
    merged = (Path(repo) / KI_REL).read_text(encoding="utf-8")
    merged_lines = _count_lines(merged)
    if len(merged_lines) != 1:
        return                                          # not this class's line: nothing computed here
    show = archive_moves._show(git)
    sides = [show(rev, KI_REL) for rev in ("HEAD", "MERGE_HEAD")]
    if any(side is None for side in sides):
        return                                          # a side we cannot read is not our doing
    line = merged_lines[0]
    if any(line in _count_lines(side) for side in sides):
        return                                          # a line one side wrote verbatim: theirs, not ours
    unresolved = [p for p in report.conflicted
                  if low_doc_parts.is_part_rel(p) and p not in report.auto_resolved]
    if unresolved:
        _defer_ki(repo, git, report, f"low-count-line: {', '.join(unresolved)} did not resolve, "
                                     f"so the merged count cannot be checked")
        return
    n = int(keyed_classes.COUNT_LINE.match(line).group(1))
    actual = low_doc_parts.total_lows(Path(repo))
    if n != actual:
        _defer_ki(repo, git, report, f"low-count-line: merged count {n} != {actual} "
                                     f"`### L` headings in the merged Low doc(s)")


def apply_low_count_check(repo, report) -> None:
    """Defer an auto-resolved `known_issues.md` whose merged count line does not match the merged
    Low doc. Never raises, never prints: a bug here defers the doc, it does not lose the report."""
    git = archive_moves._repo_git(repo)
    try:
        if KI_REL not in report.auto_resolved:
            return
        _check(str(repo), report, git)
    except Exception as e:                              # noqa: BLE001 — an unsure count defers
        try:
            _defer_ki(str(repo), git, report, f"low-count check raised — needs human "
                                              f"({type(e).__name__}: {e})")
        except Exception:                               # noqa: BLE001 — nothing may escape
            pass
