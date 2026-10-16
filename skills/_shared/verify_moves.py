"""verify_moves.py — the verbatim move verifier for living-doc archival.

Guards a live-doc -> archive move (history rollover, inventory row move) so
content is provably preserved: every non-blank line dropped from the live doc
must appear in the archive the same number of times, nothing pre-existing may
be deleted from the archive, and every other archive-side addition must be a
declared scaffold line (the `living_doc_archive.ARCHIVE_HEADER` text, a
markdown heading, a table delimiter row, or the header row sitting directly
above a delimiter row). Lines added to the live doc (e.g. an archive pointer)
are always allowed. A separate reflow mode proves a whitespace-only rewrite
kept the non-whitespace content byte-identical.

Problem strings name the offending line:
  lost: <line>  duplicated: <line>  archive-removed: <line>
  unexpected-archive-line: <line>  reflow-changed: <detail>

CLI:
  verify_moves.py --base REV --live P --archive Q [--repo-root R] [--json]
  verify_moves.py --base REV --reflow --file P [--repo-root R] [--json]

The before texts come from `git -C R show REV:path` (a path absent at REV
counts as empty); the after texts come from the working tree. Exit 0 with no
problems, 1 with any, 2 on usage error. `--json` prints
`{"problems": [...], "ok": bool}`.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from living_doc_archive import ARCHIVE_HEADER
from task_scope import _git_env  # the shipped scrub (git_env is dev-only)

_HEADING_RE = re.compile(r"^#{1,6} ")
_DELM_CELL_RE = re.compile(r":?-{3,}:?")


def _nonblank(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() != ""]


def _is_table_delimiter(line: str) -> bool:
    """True for a markdown table delimiter row: `|---|---|` with cells of
    `---`, `:---` or `---:` (blank cells allowed)."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and len(s) > 2):
        return False
    cells = [cell.strip() for cell in s.strip("|").split("|")]
    return any(cells) and all(cell == "" or _DELM_CELL_RE.fullmatch(cell) for cell in cells)


def scaffold_lines(archive_rel: str, after_archive: str) -> frozenset[str]:
    """The declared scaffold lines of an archive: the ARCHIVE_HEADER non-blank
    lines for `archive_rel`, every markdown heading line, every table
    delimiter row, and the non-blank row directly above each delimiter row.
    Blank lines never qualify. Everything else in the archive must be moved
    content (per `verify_move`)."""
    lines = _nonblank(after_archive)
    scaffold = {line for line in ARCHIVE_HEADER.get(archive_rel, "").splitlines() if line.strip() != ""}
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            scaffold.add(line)
        if _is_table_delimiter(line):
            scaffold.add(line)
            if i > 0:
                scaffold.add(lines[i - 1])
    return frozenset(scaffold)


def verify_move(
    before_live: str,
    after_live: str,
    before_archive: str,
    after_archive: str,
    scaffold: frozenset[str] = frozenset(),
) -> list[str]:
    """Verify a verbatim live->archive move over non-blank line Counters.

    Returns a list of human-readable problems (empty when the move is clean):
    lines lost in transit, lines the archive holds more copies of than the
    live doc dropped, archive lines deleted, and undeclared archive
    additions. Lines added to the live doc are allowed.
    """
    problems: list[str] = []
    removed = Counter(_nonblank(before_live)) - Counter(_nonblank(after_live))
    added = Counter(_nonblank(after_archive)) - Counter(_nonblank(before_archive))
    for line, count in removed.items():
        if added[line] < count:
            problems.append(f"lost: {line}")
        if added[line] > count:
            problems.append(f"duplicated: {line}")
    for line in Counter(_nonblank(before_archive)) - Counter(_nonblank(after_archive)):
        problems.append(f"archive-removed: {line}")
    for line, count in added.items():
        if line in removed or line in scaffold:
            continue
        problems.append(f"unexpected-archive-line: {line}")
    return problems


def verify_reflow(before: str, after: str) -> list[str]:
    """Prove a whitespace-only reflow: the non-whitespace content of `before`
    and `after` must be byte-identical. Returns problems (empty when clean)."""
    stripped_before = re.sub(r"\s", "", before)
    stripped_after = re.sub(r"\s", "", after)
    if stripped_before == stripped_after:
        return []
    return [
        "reflow-changed: non-whitespace content differs "
        f"({len(stripped_before)} -> {len(stripped_after)} chars)"
    ]


def _git_show(repo: str, rev: str, rel: str) -> str:
    """The text of `repo/rel` at revision `rev`; a path absent at the rev
    counts as empty text."""
    proc = subprocess.run(
        ["git", "-C", repo, "show", f"{rev}:{rel}"],
        capture_output=True, text=True, check=False, env=_git_env(),
    )
    return proc.stdout if proc.returncode == 0 else ""


def _worktree_text(repo: Path, rel: str) -> str:
    path = repo / rel
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a verbatim live-doc -> archive move, or a whitespace-only reflow.",
    )
    parser.add_argument("--base", required=True, metavar="REV",
                        help="revision holding the before texts (git show REV:path)")
    parser.add_argument("--live", metavar="P", help="repo-relative live doc path (move mode)")
    parser.add_argument("--archive", metavar="Q", help="repo-relative archive path (move mode)")
    parser.add_argument("--reflow", action="store_true",
                        help="reflow mode: compare non-whitespace content of one file")
    parser.add_argument("--file", metavar="P", help="repo-relative file (reflow mode)")
    parser.add_argument("--repo-root", default=".", metavar="R", help="git repo root (default: .)")
    parser.add_argument("--json", action="store_true",
                        help='print {"problems": [...], "ok": bool}')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo = Path(args.repo_root).resolve()

    if args.reflow:
        if not args.file:
            print("verify_moves: --reflow requires --file", file=sys.stderr)
            return 2
        problems = verify_reflow(_git_show(str(repo), args.base, args.file), _worktree_text(repo, args.file))
    else:
        if not (args.live and args.archive):
            print("verify_moves: move mode requires --live and --archive", file=sys.stderr)
            return 2
        after_live = _worktree_text(repo, args.live)
        after_archive = _worktree_text(repo, args.archive)
        problems = verify_move(
            _git_show(str(repo), args.base, args.live),
            after_live,
            _git_show(str(repo), args.base, args.archive),
            after_archive,
            scaffold=scaffold_lines(args.archive, after_archive),
        )

    if args.json:
        print(json.dumps({"problems": problems, "ok": not problems}, indent=2))
    elif problems:
        for problem in problems:
            print(f"verify_moves: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
