"""citation_rows — markdown row/cell helpers for design-table scanning.

Carved from citation_liveness.py (Task 3.1 — invariant-citation-coherence).
These are pure helpers: no subprocess, no git, no live-branch queries.

Public API:
  owner_slug_of_row(line, repo_root) -> str | None
  _split_table_cells(line) -> list[str]
  _strip_markup(text) -> str
  _quoted_spans(line, *, is_table_row) -> list[tuple[int, int]]
  _is_in_quoted_span(start, end, quoted_spans) -> bool

stdlib-only: re, pathlib.
"""

from __future__ import annotations

import re
from pathlib import Path


# ------------------------------------------------------------------ #
# Quote-span helpers
# ------------------------------------------------------------------ #


def _quoted_spans(line: str, *, is_table_row: bool = True) -> list[tuple[int, int]]:
    """Return list of (start, end) spans inside double-quote or backtick pairs.

    A match whose span falls entirely within one of these spans is prose — skip it.
    Handles non-overlapping pairs left-to-right.

    is_table_row=True (default): quote pairing is reset at unescaped cell separators
    ('|') so a stray unbalanced quote in one cell cannot swallow content in a
    subsequent cell.

    is_table_row=False (bullet rows): '|' is ordinary prose — quote pairing is NOT
    reset at '|', so a quoted fragment containing a pipe retains its full span.
    """
    spans = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in ('"', "`"):
            close = -1
            j = i + 1
            while j < n:
                if line[j] == ch:
                    close = j
                    break
                # Cell separator terminates quote search ONLY on table rows
                if is_table_row and line[j] == "|" and (j == 0 or line[j - 1] != "\\"):
                    break
                j += 1
            if close != -1:
                spans.append((i, close + 1))
                i = close + 1
            else:
                i += 1
        else:
            i += 1
    return spans


def _is_in_quoted_span(
    start: int, end: int, quoted_spans: list[tuple[int, int]]
) -> bool:
    """Return True if the match [start, end) falls entirely within any quoted span."""
    for qs, qe in quoted_spans:
        if start >= qs and end <= qe:
            return True
    return False


# ------------------------------------------------------------------ #
# Markup stripping
# ------------------------------------------------------------------ #


def _strip_markup(text: str) -> str:
    """Strip markdown markup from a cell: bold **..**, backticks, links [x](y)->x.

    Also replaces escaped pipes (\\|) with a space to prevent mid-token
    concatenation: cell 'f\\|oo' (renders as f|oo, not a slug) must NOT
    strip to 'foo' and falsely attribute to a slug named 'foo'.
    Using a space instead of deletion means trailing artifacts like 'my-slug \\|'
    strip correctly (the trailing space is removed by .strip() at the end).
    """
    # Strip **bold** (possibly nested with backticks)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    # Strip backticks
    text = text.replace("`", "")
    # Strip link syntax [display](url) -> display
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Replace escaped pipes with a space (not deletion) to prevent mid-token
    # concatenation: 'f\|oo' → 'f oo' (not 'foo')
    text = text.replace("\\|", " ")
    return text.strip()


# ------------------------------------------------------------------ #
# Slug regex + bullet-lead regex
# ------------------------------------------------------------------ #

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Regex for bullet rows: anchored at start of bullet, captures first bold/backtick token.
#
# Fix for prefix-slug backtracking (F2): the captured slug token is greedy and anchored
# by requiring a non-slug boundary (?![a-z0-9-]) immediately after the capture group.
# This ensures '- tp-merge-split currently ...' captures 'tp-merge-split' (full slug),
# not 'tp-merge' (using the internal '-' as the delimiter).
#
# The trailing context requires EITHER:
#   — an explicit delimiter pattern (for backtick/bold-marked slugs):
#       `?(?:\*\*)?  closes any decoration first, then:
#       (?![a-z0-9-])  non-slug boundary
#       (?:...)  one of: whitespace+dash/em-dash/colon, em-dash, colon, end-of-line,
#                space+paren, or plain whitespace (prose continuation)
#
# For decorated slugs (with backticks): the backtick/asterisk closes the token, and
# the delimiter can be `(?:\s*[—\-:]|\s*$|\s+\()` as before, but with the lookahead
# protecting against prefix issues.
# For plain slugs (no decoration): we simply need (?![a-z0-9-]) to anchor; any
# following whitespace or delimiter is acceptable.
_BULLET_LEAD_RE = re.compile(
    r"^\s*[-*]\s+"
    r"(?:\*\*)?"
    r"`?"
    r"([a-z0-9][a-z0-9-]*)"
    r"`?"
    r"(?:\*\*)?"
    r"(?![a-z0-9-])"          # non-slug boundary — prevents prefix-slug backtrack
    r"(?:\s*[—:]|\s*$|\s+\(|\s)"  # delimiter: em-dash, colon, EOL, paren, or space
)


# ------------------------------------------------------------------ #
# Table cell splitting
# ------------------------------------------------------------------ #


def _split_table_cells(line: str) -> list[str]:
    """Split a markdown table row into cells, handling escaped pipes and margins.

    Rules:
    - Split on unescaped '|' only ((?<!\\)\\| splits on pipe not preceded by backslash).
    - Only discard the leading/trailing margin parts when the stripped line actually
      starts and ends with '|' (standard GFM table).  For pipeless-margin rows
      (e.g. 'foo | bar | status') the first cell IS the owner — keep it.
    """
    stripped = line.rstrip("\n")
    # Split on unescaped pipe only
    parts = re.split(r"(?<!\\)\|", stripped)
    has_leading_pipe = stripped.lstrip().startswith("|")
    # Use the same (?<!\\) rule as the split: a row ending in \| has an escaped
    # pipe at its tail — that is NOT a GFM trailing margin pipe.
    has_trailing_pipe = bool(re.search(r"(?<!\\)\|\s*$", stripped))
    if has_leading_pipe and has_trailing_pipe and len(parts) >= 3:
        # Standard GFM: | cell | cell | — discard margin fragments
        return parts[1:-1]
    elif has_leading_pipe and len(parts) >= 2:
        # Leading pipe only: | cell | cell (no trailing pipe)
        return parts[1:]
    else:
        # Pipeless-margin or trailing-pipe-only: keep all cells
        return parts


# ------------------------------------------------------------------ #
# Owner-slug resolution
# ------------------------------------------------------------------ #


def owner_slug_of_row(line: str, repo_root) -> str | None:
    """Determine the owner slug of a markdown row by directory-resolution.

    Dispatch order: bullet anchor is checked BEFORE the pipe/table test so that
    a bullet whose prose contains '|' is not routed to the table branch.

    For bullet rows (starts with optional whitespace then '- ' or '* '):
      The owner is the first directory-resolving slug token in the LEADING
      marker only — parse the bold/backtick token(s) at the START of the
      bullet text. Tokens appearing later in bullet prose never attribute.

    For table rows (contains '|' after bullet check fails):
      Split into cells using _split_table_cells (handles pipeless-margin rows
      and escaped pipes). For each cell in order: strip markdown markup (bold,
      backticks, link syntax). The owner is the FIRST cell whose stripped
      content is exactly a slug-shaped token that directory-resolves:
      three-pillars-docs/tp-designs/{token}/ or
      three-pillars-docs/completed-tp-designs/{token}/ exists under repo_root.
      Empty/markup-only cells are skipped. A slug in a later cell can only
      attribute if no earlier cell resolves.

    Everything else -> None. No whole-line fallback anywhere.
    """
    root = Path(repo_root)
    completed = root / "three-pillars-docs" / "completed-tp-designs"
    tp_designs = root / "three-pillars-docs" / "tp-designs"

    def _resolves(token: str) -> bool:
        return (completed / token).is_dir() or (tp_designs / token).is_dir()

    stripped_line = line.rstrip("\n")

    # --- Bullet rows — checked FIRST (before '|' test) ---
    # This ensures a bullet whose prose contains '|' is not routed to table branch.
    if re.match(r"^\s*[-*]\s", stripped_line):
        m = _BULLET_LEAD_RE.match(stripped_line)
        if m:
            token = m.group(1)
            if _SLUG_RE.match(token) and _resolves(token):
                return token
        return None

    # --- Table rows ---
    if "|" in stripped_line:
        cells = _split_table_cells(stripped_line)
        for cell in cells:
            stripped = _strip_markup(cell)
            if not stripped:
                # Empty or markup-only cell — skip without shifting ownership
                continue
            # Non-empty cell: check if it's slug-shaped and directory-resolves
            if _SLUG_RE.match(stripped) and _resolves(stripped):
                return stripped
            # Non-empty but either not slug-shaped or doesn't resolve —
            # this cell is NOT the owner; continue to next cell
            # (do NOT return None here — a bold/styled non-slug cell like
            # "**Done (2026-06-08)**" or "seeded" should not block later cells)
        return None

    # --- Everything else ---
    return None
