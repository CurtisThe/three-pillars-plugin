"""history_rollover.py — roll the oldest History entries of a living doc to
its archive, keeping the newest `keep` (default 15) live.

Pinned 'History shape' (authoritative): the History section is the first
`## ` heading whose title contains `History` (`## History`, `## Roadmap
History`, `## History (implementation ledger …)`). Entries are the
contiguous run that starts at the first column-0 `- ` bullet under the
heading. An entry is that bullet plus its continuation lines (indented
lines). Blank lines do not end the run; the run ends at the first non-blank
column-0 line that is neither a bullet nor indented, or at the next `## `.
Lines before the run (a `> …` preamble) and after it (the roadmap's
`*Newest-first…*` / `*Older history…*` lines and any bullet after them)
stay where they are.

Newest first: entries are listed newest at the top, so the rolled (oldest)
entries are the LAST entries of the live run. Rolled entries go to the TOP
of the archive's History section (immediately before its first entry, or
after its last non-blank line if it has none), so the archive stays
newest-first. When several entries roll, their relative order (newest-first)
is preserved in the archive.

The verifier (`verify_moves.verify_move`) runs in memory before anything is
written; on any problem nothing is written and the reason names the
problems. A missing archive is seeded from `living_doc_archive.ARCHIVE_HEADER`
plus a `## History` heading; an existing archive with no History heading
gets `## History` appended at EOF. `verify_moves.scaffold_lines` is passed so
a created header or an appended `## History` heading verifies.

CLI:
  history_rollover.py --doc <rel> [--keep 15] [--json] [--repo-root R]

Exit 0 on a clean roll or a no-op (with a reason), 1 on a verifier failure,
2 on usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import living_doc_archive
import verify_moves

DEFAULT_KEEP = 15


@dataclass
class RollResult:
    """Outcome of one rollover: `moved` entries moved to the archive,
    `live_count` entries left in the live doc's History run, and a human
    `reason` (None on a clean roll)."""
    moved: int
    live_count: int
    reason: str | None = None


@dataclass
class HistorySpan:
    """A parsed History section: the section's line list, its entries
    (each entry a list of its own lines, bullet first, in document order —
    newest first), and the line indices of the first entry's bullet and the
    last entry's last non-blank line."""
    heading: str
    entries: list[list[str]]
    lines: list[str]
    first_entry_idx: int
    last_entry_idx: int


def _is_bullet(line: str) -> bool:
    return line.startswith("- ")


def _is_indented(line: str) -> bool:
    return line != line.lstrip()


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _history_heading_idx(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if line.startswith("## ") and "History" in line:
            return i
    return None


def _split_entries(lines: list[str], start: int, end: int) -> list[list[str]]:
    """Group `lines[start:end]` into entries: each column-0 `- ` bullet
    opens an entry; indented lines and blank lines continue it. Trailing
    blank lines at the end of each entry are dropped."""
    entries: list[list[str]] = []
    current: list[str] | None = None
    for line in lines[start:end]:
        if _is_bullet(line):
            if current is not None:
                entries.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
        # else: non-bullet chrome before the first bullet — stays in place
    if current is not None:
        entries.append(current)
    for entry in entries:
        while entry and _is_blank(entry[-1]):
            entry.pop()
    return [entry for entry in entries if entry]


def parse_history(text: str) -> HistorySpan | None:
    """Parse the History section of `text`. Returns None when there is no
    `## …History…` heading; otherwise a HistorySpan whose `entries` is empty
    when the run holds no entries. Entries are in document order (newest
    first), each entry a list of its own lines."""
    lines = text.splitlines(keepends=True)
    heading_idx = _history_heading_idx(lines)
    if heading_idx is None:
        return None
    run_start: int | None = None
    run_end = len(lines)
    for i in range(heading_idx + 1, len(lines)):
        line = lines[i]
        if _is_bullet(line):
            if run_start is None:
                run_start = i
            continue
        if _is_blank(line) or _is_indented(line):
            continue  # blank lines and continuations never end the run
        if run_start is not None:
            run_end = i  # first non-blank column-0 non-bullet line ends it
            break
        # non-bullet chrome before the first bullet stays where it is
    if run_start is None:
        return HistorySpan(lines[heading_idx], [], lines, heading_idx, heading_idx)
    entries = _split_entries(lines, run_start, run_end)
    if not entries:
        return HistorySpan(lines[heading_idx], [], lines, run_start, run_start)
    last_idx = run_end - 1
    while last_idx > run_start and _is_blank(lines[last_idx]):
        last_idx -= 1
    return HistorySpan(lines[heading_idx], entries, lines, run_start, last_idx)


def _rolled_entry_lines(span: HistorySpan, keep: int) -> list[str]:
    """The flat lines of the entries that roll (the last `len - keep`
    entries, in their original newest-first order)."""
    n_roll = len(span.entries) - keep
    rolled = span.entries[len(span.entries) - n_roll:]
    out: list[str] = []
    for entry in rolled:
        out.extend(entry)
    return out


def _rebuild_live(span: HistorySpan, rolled: list[str]) -> str:
    """Rebuild the live doc with the rolled entries' lines removed. The
    rolled entries are the LAST entries of the run, so delete from the
    first rolled entry's bullet line through the last entry's last non-blank
    line; blank lines before the run's end and everything after the run
    (the section's trailer) stay put."""
    lines = list(span.lines)
    first_bullet = rolled[0].rstrip("\n")
    idx = None
    for i in range(span.first_entry_idx, span.last_entry_idx + 1):
        if lines[i].rstrip("\n") == first_bullet:
            idx = i
            break
    if idx is None:  # defensive: fall back to line-wise removal
        dropped = {line.rstrip("\n") for line in rolled}
        return "".join(line for line in lines if line.rstrip("\n") not in dropped)
    del lines[idx:span.last_entry_idx + 1]
    return "".join(lines)


def _rebuild_archive(before: str, rolled: list[str], archive_rel: str) -> str:
    """The archive's after-text with the rolled entries at the top of its
    History section: before its first entry, after the section's last
    non-blank line if it has none, appended as a new `## History` section at
    EOF when the archive has no History heading, or seeded from
    ARCHIVE_HEADER when the archive file is missing."""
    if not before:
        return living_doc_archive.ARCHIVE_HEADER[archive_rel] + "## History\n\n" + "".join(rolled)
    span = parse_history(before)
    if span is None or not span.entries:
        base = before if before.endswith("\n") else before + "\n"
        return base + "## History\n\n" + "".join(rolled)
    lines = before.splitlines(keepends=True)
    insert_at = span.first_entry_idx
    return "".join(lines[:insert_at] + rolled + lines[insert_at:])


def roll(repo_root, live_rel: str, keep: int = DEFAULT_KEEP) -> RollResult:
    """Roll the oldest History entries of `live_rel` (repo-relative) into
    its archive, keeping the newest `keep` live. The verifier runs in memory
    before anything is written; on problems nothing is written and the
    reason names them. `KeyError` if `live_rel` is not a known living doc."""
    root = Path(repo_root)
    archive_rel = living_doc_archive.archive_for(live_rel)  # KeyError for unknown docs
    live_path = root / live_rel
    if not live_path.is_file():
        return RollResult(0, 0, f"live doc not found: {live_rel}")
    before_live = live_path.read_text(encoding="utf-8")

    span = parse_history(before_live)
    if span is None:
        return RollResult(0, 0, "no History section found")
    if not span.entries:
        return RollResult(0, 0, "no entries in the History section")
    if len(span.entries) <= keep:
        return RollResult(0, len(span.entries), f"only {len(span.entries)} entries (keep {keep})")

    rolled = _rolled_entry_lines(span, keep)
    archive_path = root / archive_rel
    before_archive = archive_path.read_text(encoding="utf-8") if archive_path.is_file() else ""

    after_live = _rebuild_live(span, rolled)
    after_archive = _rebuild_archive(before_archive, rolled, archive_rel)
    problems = verify_moves.verify_move(
        before_live, after_live, before_archive, after_archive,
        scaffold=verify_moves.scaffold_lines(archive_rel, after_archive),
    )
    if problems:
        return RollResult(0, len(span.entries), "verifier: " + "; ".join(problems))

    live_path.write_text(after_live, encoding="utf-8")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(after_archive, encoding="utf-8")
    return RollResult(len(span.entries) - keep, keep, None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Roll the oldest History entries of a living doc into its archive.",
    )
    parser.add_argument("--doc", required=True, metavar="REL",
                        help="repo-relative living doc path")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, metavar="N",
                        help=f"entries to keep live (default {DEFAULT_KEEP})")
    parser.add_argument("--repo-root", default=".", metavar="R",
                        help="repo root (default: .)")
    parser.add_argument("--json", action="store_true",
                        help="print the RollResult as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = roll(args.repo_root, args.doc, keep=args.keep)
    except KeyError as exc:
        print(f"history_rollover: unknown live doc: {exc.args[0] if exc.args else exc}",
              file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(
            {"moved": result.moved, "live_count": result.live_count,
             "reason": result.reason},
            indent=2,
        ))
    elif result.reason:
        print(f"history_rollover: no entries rolled — {result.reason}")
    else:
        print(f"history_rollover: rolled {result.moved} entries; {result.live_count} live")
    if result.reason and result.reason.startswith("verifier:"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
