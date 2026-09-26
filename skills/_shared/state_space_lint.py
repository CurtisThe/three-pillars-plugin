#!/usr/bin/env python3
"""Warn-only lint for a design.md `## State space` section.

Per skills/_shared/state-space-protocol.md: warns when the map has fewer
than 2 loci or a `### Questions` bullet lacks a `flips:` target. Advisory
only — every read and parse path prints WARN lines and exits 0, so it never
blocks a commit or skill step. Only CLI misuse (wrong argument count) exits
non-zero (argparse's 2).

Usage: python3 "$TP_ROOT"/skills/_shared/state_space_lint.py <design_dir|file>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")  # any indent: list-item fences count
_SECTION = re.compile(r"^##\s+state\s+space\s*$", re.I)
_H2 = re.compile(r"^##\s")
_H3 = re.compile(r"^###\s+(.*?)\s*$")
_BULLET = re.compile(r"^[-*+]\s+\S")
_QUESTION = re.compile(r"^[-*+]\s+(\*\*)?Q\d+\b", re.I)
_FLIP = re.compile(r"flips:\s*\S", re.I)


def _fence_mask(lines: list[str]) -> list[bool]:
    """True for lines inside (or delimiting) a CLOSED fenced block.

    Pairs follow CommonMark: a closer uses the opener's character, is at least
    as long, and carries no info string, so a ``` line inside a ~~~ (or ````)
    block does not close it. An opener that is never closed is ignored and
    scanning resumes after it. A stray opener that a later bare fence does
    close masks the text between them, exactly as CommonMark renders it.
    """
    mask = [False] * len(lines)
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        start, char, width = i, m.group(1)[0], len(m.group(1))
        for j in range(start + 1, len(lines)):
            c = _FENCE.match(lines[j])
            if c and c.group(1)[0] == char and len(c.group(1)) >= width \
                    and not lines[j].strip()[len(c.group(1)):].strip():
                for k in range(start, j + 1):
                    mask[k] = True
                i = j + 1
                break
        else:
            i = start + 1  # never closed: ignore this opener, keep scanning after it
    return mask


def _unfenced_lines(text: str) -> list[tuple[str, bool]]:
    """Return (line, in_fence) pairs; fence delimiter lines count as fenced."""
    lines = text.lstrip("﻿").splitlines()
    return list(zip(lines, _fence_mask(lines)))


def _sections(text: str) -> list[list[tuple[str, bool]]]:
    """Every `## State space` body (case-insensitive heading), fence-aware."""
    found: list[list[tuple[str, bool]]] = []
    body: list[tuple[str, bool]] | None = None
    for line, fenced in _unfenced_lines(text):
        if not fenced and _SECTION.match(line.strip()):
            body = []
            found.append(body)
        elif body is not None and not fenced and _H2.match(line):
            body = None
        elif body is not None:
            body.append((line, fenced))
    return found


def extract_section(text: str) -> str | None:
    """Body of the first `## State space` up to the next `## ` heading, or None."""
    found = _sections(text)
    return None if not found else "\n".join(ln for ln, _ in found[0])


def _subsection(section: str, heading: str) -> list[str]:
    """Unfenced lines under `### <heading>` (case-insensitive)."""
    lines, inside = [], False
    for line, fenced in _unfenced_lines(section):
        if fenced:
            continue
        m = _H3.match(line)
        if m:
            inside = m.group(1).lower() == heading.lower()
            continue
        if inside:
            lines.append(line)
    return lines


def count_loci(section: str) -> int:
    return sum(1 for ln in _subsection(section, "Loci") if _BULLET.match(ln))


def _questions(section: str) -> list[str]:
    """Question bullets with wrapped continuation lines joined on."""
    out: list[str] = []
    open_q = False
    for ln in _subsection(section, "Questions"):
        if _QUESTION.match(ln):
            out.append(ln.strip())
            open_q = True
        elif _BULLET.match(ln) or not ln.strip():
            open_q = False  # another bullet or a blank line ends the question
        elif open_q:
            out[-1] += " " + ln.strip()
    return out


def questions_missing_flip(section: str) -> list[str]:
    return [q for q in _questions(section) if not _FLIP.search(q)]


def lint(text: str) -> list[str]:
    found = _sections(text)
    if not found:
        return []
    section = "\n".join(ln for ln, _ in found[0])
    warnings = []
    if len(found) > 1:
        warnings.append(f"{len(found)} ## State space sections; only the first is linted")
    n = count_loci(section)
    if n < 2:
        warnings.append(f"fewer than 2 loci ({n}) under ### Loci")
    for q in questions_missing_flip(section):
        warnings.append(f"question lacks a flips: target: {q}")
    return warnings


def _run(path: Path) -> list[str]:
    try:
        if path.is_dir():
            path = path / "design.md"
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read {path}: {getattr(exc, 'strerror', None) or exc}"]
    try:
        return lint(text)
    except Exception as exc:  # advisory: a lint bug must never block the caller
        return [f"lint error on {path}: {exc!r}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Warn-only lint for a design.md State space section.")
    parser.add_argument("path", help="design directory (reads design.md) or a file")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    for msg in _run(Path(args.path)):
        print(f"WARN state-space: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
