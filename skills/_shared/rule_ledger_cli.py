#!/usr/bin/env python3
"""rule_ledger_cli — the command line over the D7 rule ledger.

design: skill-context-diet (Task 1.4)

    slices    cut a source into balanced line ranges (ranges.json)
    extract   write a skeleton ledger (every row `todo`) and an empty fragment
    check     run the ledger check over ledgers (--final-only, --live)
    coverage  prove the ledgers' ranges cover each source exactly once
    snapshot  append a doc's old text, headings demoted two levels, to an archive
    seal      write final_blob (+ peer_blobs) into ledger headers, after the swap
    assemble  concatenate the ledgers' fragments, in order, into a destination

Every path is relative to `--root` (default: the current directory), which must
be the git repository the ledgers belong to. Exit 0 means clean and 1 means
problems, one printed line per problem; a clean run prints nothing. The logic
is in `rule_ledger` (ledgers) and `rule_ledger_extract` (slices and spans).

stdlib-only; it ships with the consumer helpers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import rule_ledger as rl
from rule_ledger_extract import slices, span_lines

__all__ = ["main", "demote", "snapshot", "assemble"]

_HEADING_LINE = re.compile(r"^#+(?=\s|$)")
_HEADING_AT = re.compile(r"(?m)^#+(?=\s|$)")
_LINES_PART = re.compile(r"^(\d+)(?:-(\d+))?$")


def _text_of(root, rel, what="source") -> str:
    try:
        return (Path(root) / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{what} {str(rel)!r} is not a readable file ({exc.__class__.__name__})")


def _write_text(root, rel, text) -> None:
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _lines(text) -> list:
    """`text` split on newlines only (a trailing newline adds no empty line)."""
    parts = text.split("\n")
    return parts[:-1] if parts and parts[-1] == "" else parts


# ------------------------------------------------------------------ #
# slices / extract
# ------------------------------------------------------------------ #


def _parse_lines(spec, total) -> list:
    """`a-b[,c-d]` as inclusive 1-based ranges inside a source of `total` lines."""
    ranges = []
    for part in spec.split(","):
        match = _LINES_PART.match(part.strip())
        if not match:
            raise ValueError(f"bad --lines {spec!r}: expected a-b[,c-d]")
        lo = int(match.group(1))
        hi = int(match.group(2) or lo)
        if not 1 <= lo <= hi <= total:
            raise ValueError(f"--lines {lo}-{hi} is outside the source's lines 1-{total}")
        ranges.append([lo, hi])
    return ranges


def _ranges_file(root, rel, index) -> list:
    if index is None:
        raise ValueError("--ranges needs --index")
    try:
        data = json.loads(_text_of(root, rel, "ranges file"))
        picked = data[index - 1] if 1 <= index <= len(data) else None
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"ranges file {rel!r} is not a JSON list of [a, b] ranges ({exc})")
    if picked is None:
        raise ValueError(f"--index {index} is outside the {len(data)} ranges in {rel}")
    return [[int(picked[0]), int(picked[1])]]


def _span_range(text, spec) -> list:
    start, sep, end = spec.partition("..")
    if not sep:
        raise ValueError(f'--span {spec!r} needs the form "START..END"')
    return list(span_lines(text, start, end))


def _selected_ranges(args, text) -> list:
    if args.lines:
        return _parse_lines(args.lines, len(text.splitlines()))
    if args.ranges:
        return _ranges_file(args.root, args.ranges, args.index)
    return [_span_range(text, spec) for spec in args.span]


def _cmd_slices(args) -> list:
    text = _text_of(args.root, args.source)
    cuts = json.dumps([list(cut) for cut in slices(text, args.count, args.within)])
    if args.out:
        _write_text(args.root, args.out, cuts + "\n")
    else:
        print(cuts)
    return []


def _cmd_extract(args) -> list:
    if args.index is not None and not args.ranges:
        raise ValueError("--index belongs with --ranges")
    text = _text_of(args.root, args.source)
    kinds = [kind.strip() for kind in args.kinds.split(",") if kind.strip()]
    header, rows = rl.skeleton(
        args.root, args.source, _selected_ranges(args, text), kinds, args.fragment,
        args.final, args.budget, args.base_ref or rl.head_ref(args.root))
    rl.dump(Path(args.root) / args.out, header, rows)
    _write_text(args.root, args.fragment, "")
    return []


# ------------------------------------------------------------------ #
# snapshot
# ------------------------------------------------------------------ #


def demote(text, levels=2) -> str:
    """`text` with every ATX heading line pushed down `levels` levels.

    Any run of `#` followed by whitespace or the end of the line counts, fenced
    or not: a snapshot must hold no line that opens a `## ` or `# ` section,
    and a `#` comment inside a fence is only archived text.
    """
    return _HEADING_AT.sub(lambda match: "#" * levels + match.group(0), text)


def _snapshot_problems(old, block, levels) -> list:
    """What the written `block` lost or changed relative to the `old` text."""
    want, got = _lines(old), _lines(block)
    problems = [f"snapshot: line missing from the snapshot: {line!r}"
                for line in (Counter(x for x in want if not _HEADING_LINE.match(x))
                             - Counter(x for x in got if not _HEADING_LINE.match(x)))]
    heads = [x for x in want if _HEADING_LINE.match(x)]
    if [x for x in got if _HEADING_LINE.match(x)] != ["#" * levels + x for x in heads]:
        problems.append(f"snapshot: the {len(heads)} headings were not each demoted {levels} levels")
    problems += [f"snapshot: a snapshot line opens a section: {x!r}" for x in got
                 if re.match(r"#{1,2}(\s|$)", x)]
    return problems


def snapshot(root, source, archive, title) -> list:
    """Append `## <title>` and the old `source` text, demoted two levels, to `archive`.

    The title must contain `History`: the whole snapshot then sits in one
    `## ...History...` section, which the pending-flip, stale-status and ID
    scans skip. The written text is read back and checked line by line; on any
    problem the archive is restored and nothing is left behind.
    """
    if "History" not in title:
        return [f"snapshot: title {title!r} must contain 'History' so the snapshot "
                "sits inside one History section"]
    old = _text_of(root, source)
    src_path, arch_path = Path(root) / source, Path(root) / archive
    if arch_path.exists() and src_path.resolve() == arch_path.resolve():
        return [f"snapshot: source and archive are the same file ({source})"]
    body = demote(old, 2)
    body += "" if body.endswith("\n") or not body else "\n"
    before = arch_path.read_text(encoding="utf-8") if arch_path.exists() else None
    prefix = before or ""
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n" if prefix.endswith("\n") else "\n\n"
    head = f"## {title}\n\n"
    _write_text(root, archive, prefix + head + body)
    written = arch_path.read_text(encoding="utf-8")
    problems = []
    if not written.startswith(prefix + head):
        problems.append("snapshot: the archive does not start with its previous text and the title")
    problems += _snapshot_problems(old, written[len(prefix) + len(head):], 2)
    if problems:
        if before is None:
            arch_path.unlink()
        else:
            arch_path.write_text(before, encoding="utf-8")
    return problems


# ------------------------------------------------------------------ #
# assemble
# ------------------------------------------------------------------ #


def assemble(root, ledger_paths, out, header=None) -> list:
    """Write the ledgers' fragments, in the order given, to `out`; return problems.

    Every ledger's `final` must be `out`. A fragment that ends without a newline
    gets one; no blank line is added at a seam (seams are joined by hand). The
    optional `header` file's text comes first. Nothing is written on a problem.
    """
    problems, parts = [], []
    if header:
        try:
            parts.append(_text_of(root, header, "header file"))
        except ValueError as exc:
            problems.append(f"assemble: {exc}")
    for path in ledger_paths:
        name = rl.ledger_label(root, path)
        try:
            head = rl.load(Path(root) / path)["header"]
        except rl.LOAD_ERRORS as exc:
            problems.append(f"{name}: assemble: {exc}")
            continue
        if os.path.normpath(str(head["final"])) != os.path.normpath(out):
            problems.append(f"assemble: {name} has final {head['final']!r}, not {out!r}")
            continue
        try:
            text = _text_of(root, head["fragment"], "fragment")
        except ValueError as exc:
            problems.append(f"assemble: {name}: {exc}")
            continue
        parts.append(text if not text or text.endswith("\n") else text + "\n")
    if not problems:
        _write_text(root, out, "".join(parts))
    return problems


# ------------------------------------------------------------------ #
# the command line
# ------------------------------------------------------------------ #


def _cmd_check(args) -> list:
    return rl.check_files(args.ledgers, args.root, args.final_only, args.live)


def _cmd_coverage(args) -> list:
    return rl.coverage(args.root, args.ledgers)


def _cmd_snapshot(args) -> list:
    return snapshot(args.root, args.source, args.archive, args.title)


def _cmd_seal(args) -> list:
    return rl.seal(args.root, args.ledgers)


def _cmd_assemble(args) -> list:
    return assemble(args.root, args.ledgers, args.out, args.header)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rule_ledger_cli", description="Rule-ledger tool (skill-context-diet D7). "
        "Exit 0 = clean, 1 = problems (one line each); a clean run prints nothing.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    root = argparse.ArgumentParser(add_help=False)
    root.add_argument("--root", default=".", help="the git repository (default: cwd)")

    def command(name, func, help_text, *parents):
        sub_parser = sub.add_parser(name, parents=[root, *parents], help=help_text,
                                    description=help_text)
        sub_parser.set_defaults(run=func)
        return sub_parser

    cut = command("slices", _cmd_slices, "cut a source into balanced line ranges (JSON)")
    cut.add_argument("--source", required=True)
    cut.add_argument("--count", type=int, required=True)
    cut.add_argument("--within", help='heading span "S..E" to cut instead of the whole file')
    cut.add_argument("--out", help="write the ranges here (default: print them)")

    ext = command("extract", _cmd_extract,
                  "write a skeleton ledger (every row todo) and an empty fragment")
    ext.add_argument("--source", required=True)
    pick = ext.add_mutually_exclusive_group(required=True)
    pick.add_argument("--lines", help="a-b[,c-d] (1-based, inclusive)")
    pick.add_argument("--ranges", help="a ranges.json from `slices`; needs --index")
    pick.add_argument("--span", action="append", help='heading span "S..E" (repeatable)')
    ext.add_argument("--index", type=int, help="1-based slice of --ranges")
    ext.add_argument("--kinds", required=True, help=f"comma list of {', '.join(rl.KINDS)}")
    ext.add_argument("--fragment", required=True, help="the staged fragment (created empty)")
    ext.add_argument("--final", required=True, help="the destination of the swap")
    ext.add_argument("--budget", type=int, help="max chars of the fragment")
    ext.add_argument("--base-ref", help="provenance ref (default: HEAD)")
    ext.add_argument("--out", required=True, help="the ledger to write")

    chk = command("check", _cmd_check, "check ledgers")
    chk.add_argument("--final-only", action="store_true", help="committed posture: ignore the "
                     "fragment, an unsealed ledger is a problem")
    chk.add_argument("--live", action="store_true",
                     help="swap-time: read needles from the live files and re-hash them")
    chk.add_argument("ledgers", nargs="+")

    cov = command("coverage", _cmd_coverage, "the ledgers' ranges cover each source once")
    cov.add_argument("ledgers", nargs="+")

    snap = command("snapshot", _cmd_snapshot,
                   "append the old text, headings demoted two levels, under a History title")
    snap.add_argument("--source", required=True)
    snap.add_argument("--archive", required=True)
    snap.add_argument("--title", required=True, help="the `## ` title; must contain 'History'")

    seal = command("seal", _cmd_seal, "write final_blob and peer_blobs into the ledgers")
    seal.add_argument("ledgers", nargs="+")

    asm = command("assemble", _cmd_assemble, "concatenate the fragments into the destination")
    asm.add_argument("ledgers", nargs="+")
    asm.add_argument("--out", required=True, help="the destination (each ledger's final)")
    asm.add_argument("--header", help="a file whose text goes first")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        problems = args.run(args)
    except (ValueError, OSError) as exc:
        problems = [f"{args.command}: {exc}"]
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
