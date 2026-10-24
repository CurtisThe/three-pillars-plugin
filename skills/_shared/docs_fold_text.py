"""docs_fold_text.py — line helpers shared by the fragment fold (``docs_fold`` / ``docs_fold_issues``).

design: living-doc-fragments, Task 1.3. Owns ``FoldError`` and the markdown-section arithmetic: find a
heading, the span it owns (to the next heading of the same or a higher level), where an append or a
prepend lands, the ``{pr}`` token and the ``*Last updated:`` stamp. Pure text in, text out. Stdlib only.
"""
from __future__ import annotations

import re

PR_TOKEN = "{pr}"
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_STAMP = re.compile(r"^(\*Last updated: )\d{4}-\d{2}-\d{2}", re.M)
PREPEND_HEADINGS = ("Recent completions",)  # plus every heading ending in "History" (newest-first)


class FoldError(Exception):
    """A fragment section that does not apply to the docs; ``section`` names the fragment section."""

    def __init__(self, section: str, reason: str):
        super().__init__(f"{section}: {reason}")
        self.section = section
        self.reason = reason


def heading_of(line: str) -> tuple[int, str] | None:
    """``(level, text)`` for an ATX heading line, else None."""
    match = _HEADING.match(line)
    return (len(match.group(1)), match.group(2)) if match else None


def find_heading(lines: list[str], text: str, level: int | None = None) -> int | None:
    """Index of the first heading whose text is ``text`` (and, when given, of ``level``)."""
    for i, line in enumerate(lines):
        head = heading_of(line)
        if head and head[1] == text and (level is None or head[0] == level):
            return i
    return None


def section_end(lines: list[str], start: int) -> int:
    """End (exclusive) of the section headed at ``start``: the next heading of level <= its own."""
    level = heading_of(lines[start])[0]
    for i in range(start + 1, len(lines)):
        head = heading_of(lines[i])
        if head and head[0] <= level:
            return i
    return len(lines)


def entry_end(lines: list[str], start: int) -> int:
    """End (exclusive) of the ``### `` entry at ``start``: the next heading of any level, or EOF."""
    for i in range(start + 1, len(lines)):
        if heading_of(lines[i]):
            return i
    return len(lines)


def append_point(lines: list[str], start: int, end: int) -> int:
    """Index just after the last non-blank line of the section ``[start, end)`` (heading included)."""
    point = start + 1
    for i in range(start + 1, end):
        if lines[i].strip():
            point = i + 1
    return point


def prepend_point(lines: list[str], start: int, end: int) -> int:
    """Before the first ``- `` entry of the section; its append point when it holds none."""
    for i in range(start + 1, end):
        if lines[i].startswith("- "):
            return i
    return append_point(lines, start, end)


def is_prepend_heading(text: str) -> bool:
    return text in PREPEND_HEADINGS or text.endswith("History")


def insert_block(lines: list[str], point: int, block: list[str]) -> None:
    """Insert ``block`` at ``point`` separated by one blank line before it, and after it when a
    heading follows directly."""
    after = [""] if point < len(lines) and lines[point].strip() else []
    lines[point:point] = [""] + block + after


def append_to_text(text: str, block: list[str]) -> str:
    """``block`` appended at the end of ``text`` after one blank line."""
    body = text.rstrip("\n")
    return (body + "\n\n" if body else "") + "\n".join(block) + "\n"


def expand_pr(text: str, pr: int | None) -> str:
    return text.replace(PR_TOKEN, f"PR #{pr}" if pr is not None else "completion PR")


def stamp(text: str, date: str) -> str:
    """Re-stamp the ``*Last updated: YYYY-MM-DD`` line with ``date`` (the fragment's, never today)."""
    return _STAMP.sub(lambda m: m.group(1) + date, text, count=1)


def split(text: str) -> list[str]:
    return text.splitlines()


def join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n" if lines else ""
