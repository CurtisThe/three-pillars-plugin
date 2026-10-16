#!/usr/bin/env python3
"""command_shape_scan.py — advisory scan for command shapes no permission rule can match.

design: matchable-commands (Behavior 3). Permission rules match literal command text, so these shapes
stall unattended runs: `bash -c` / `sh -c` / `nohup` wrappers, `cd <dir> && git|pytest`, ad-hoc
`$VAR/script.py` paths and `export TP_ROOT=… &&` prefixes. See `matchable-commands.md` for the matchable
form of each. Scans shipped `skills/*/*.md` (SKILL.md, sibling docs, `_shared/*.md`); prints `file:line: [shape] text`.
ADVISORY: always exits 0. A line carrying `matchable: ok` is skipped; `matchable-commands.md` is not scanned.

    python3 skills/_shared/command_shape_scan.py [--root .] [--quiet]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

__all__ = ["SHAPES", "scan_text", "scan_tree", "main"]

SHAPES: dict[str, re.Pattern[str]] = {
    "shell-c-wrapper": re.compile(r"(?<![\w-])(?:bash|sh|zsh)(?: -\w+)* -c\b|(?<![\w-])nohup\b"),
    "cd-then-command": re.compile(r"\bcd\s+[^\s&;|`]+\s*&&\s*(?:git|pytest|python3 -m pytest)\b"),
    # `$TP_ROOT` is the framework's own sanctioned prefix; any other `$VAR/x.py` defeats allow rules.
    "var-script-path": re.compile(r"\$\{?(?!TP_ROOT\b)[A-Za-z_]\w*\}?/[\w./-]*\.py\b"),
    "export-prefix": re.compile(r"\bexport\s+TP_ROOT=[^&;\n]*&&"),
}
SKIP_MARK = "matchable: ok"
SELF_DOC = "matchable-commands.md"


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """Return `(line_no, shape, line)` for every flagged line of `text`."""
    hits = []
    for no, line in enumerate(text.splitlines(), 1):
        if SKIP_MARK in line:
            continue
        for shape, pat in SHAPES.items():
            if pat.search(line):
                hits.append((no, shape, line.strip()))
    return hits


def _files(root: Path) -> list[Path]:
    skills = root / "skills"
    found = sorted(skills.glob("*/*.md"))  # each skill's SKILL.md and sibling docs, plus _shared/*.md
    return [p for p in found if p.name != SELF_DOC]


def scan_tree(root: Path) -> list[str]:
    out = []
    for path in _files(root):
        for no, shape, line in scan_text(path.read_text(encoding="utf-8", errors="replace")):
            out.append(f"{path.relative_to(root)}:{no}: [{shape}] {line[:160]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="command_shape_scan.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repo root holding skills/ (default .)")
    ap.add_argument("--quiet", action="store_true", help="print only the hit lines, no summary")
    args = ap.parse_args(argv)
    hits = scan_tree(Path(args.root))
    for h in hits:
        print(h)
    if not args.quiet:
        print(f"command_shape_scan: {len(hits)} advisory hit(s); see skills/_shared/matchable-commands.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
