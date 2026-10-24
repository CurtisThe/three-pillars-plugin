"""rule_ledger_extract — the extraction kinds behind the D7 rule ledger.

design: skill-context-diet (Task 1.1)

A rule ledger (design D7) records every rule in the pre-diet text of a doc or
skill and where it survived in the condensed text. This module supplies the
kinds a ledger row is built from, so the ledger is derived from the text rather
than hand-copied:

  extract_rules(text)      imperative sentences and bullets (the D7 marker list)
  extract_items(text)      `###` headings, column-0 bullets, table data rows
  extract_headings(text)   `###` headings only
  extract_pins(old, paths) test string constants that occur verbatim in `old`
  pin_tests_for(src, root) tests that name a source file
  slices(text, count, within)  balanced line ranges covering a span once (1.2)
  span_lines(text, start, end) a `S..E` heading span as line numbers (1.2)

Fenced code blocks are skipped for rules, items and headings — a fence is
example text, not a rule. Pins deliberately ignore fences: a prose-pin test
literal can sit inside a fenced command and still pin the old wording.

stdlib-only: ast, re, pathlib.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

__all__ = [
    "IMPERATIVE_MARKERS",
    "extract_rules",
    "extract_items",
    "extract_headings",
    "extract_pins",
    "pin_tests_for",
    "slices",
    "span_lines",
]

# The imperative markers design D7 lists. Case-insensitive, word-bounded.
# skills/_shared/test_rule_ledger_extract.py pins this tuple against the D7 list.
IMPERATIVE_MARKERS = (
    "must",
    "never",
    "always",
    "refuse",
    "stop",
    "only",
    "do not",
    "don't",
    "cannot",
    "required",
    "at most",
    "at least",
)

_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in IMPERATIVE_MARKERS) + r")\b",
    re.IGNORECASE,
)

_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_DELIM_CELL_RE = re.compile(r"^:?-{1,}:?$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# A pin literal shorter than this is prose noise, not a pinned phrase.
_MIN_PIN_CHARS = 10


def _iter_lines(text: str):
    """Yield (line, in_fence) for every line; fence markers themselves are skipped."""
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        yield line, in_fence


def _split_sentences(unit: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(unit.strip()) if s.strip()]


def _paragraph_units(text: str) -> list[tuple[str, str]]:
    """Split `text` into (kind, content) units outside fences.

    kind is 'bullet', 'heading', 'row' or 'para'. Consecutive plain prose lines
    join into one 'para' unit, so a sentence wrapped across source lines stays
    one sentence.
    """
    units: list[tuple[str, str]] = []
    para: list[str] = []

    def flush():
        if para:
            units.append(("para", " ".join(para)))
            para.clear()

    for line, in_fence in _iter_lines(text):
        if in_fence:
            flush()
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        heading = _HEADING_RE.match(line)
        bullet = _BULLET_RE.match(line)
        if heading and not bullet:
            flush()
            units.append(("heading", heading.group(2).strip()))
        elif bullet:
            flush()
            units.append(("bullet", bullet.group(1).strip()))
        elif _TABLE_ROW_RE.match(line):
            flush()
            units.append(("row", stripped))
        else:
            para.append(stripped)
    flush()
    return units


def extract_rules(text: str) -> list[str]:
    """Return every imperative sentence or bullet in `text`, in document order.

    A sentence is imperative when it contains one of IMPERATIVE_MARKERS
    (case-insensitive). Non-imperative prose and fenced code are skipped.
    """
    rules: list[str] = []
    for kind, content in _paragraph_units(text):
        if kind in ("heading", "row"):
            continue
        for sentence in _split_sentences(content):
            if _MARKER_RE.search(sentence):
                rules.append(sentence)
    return rules


def _table_block_items(lines: list[str]) -> list[str]:
    """First cell of each data row of a table block (header and delimiters skipped)."""
    items: list[str] = []
    for index, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        if all(_DELIM_CELL_RE.match(cell) for cell in cells if cell):
            continue  # delimiter row: |---|---| or | --- | ---: |
        if index == 0:  # header row of the block
            continue
        items.append(cells[0])
    return items


def extract_items(text: str) -> list[str]:
    """Return `###` headings, column-0 bullets (first line) and table data rows
    (first cell), in document order. Table delimiter rows are never returned."""
    items: list[str] = []
    lines = text.splitlines()
    in_fence = False
    table: list[str] = []

    def flush_table():
        if table:
            items.extend(_table_block_items(table))
            table.clear()

    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            flush_table()
            continue
        if in_fence:
            flush_table()
            continue
        if _TABLE_ROW_RE.match(line):
            table.append(line)
            continue
        flush_table()
        stripped = line.strip()
        if not stripped:
            continue
        heading = _HEADING_RE.match(line)
        if heading and not _BULLET_RE.match(line):
            if len(heading.group(1)) == 3:
                items.append(heading.group(2).strip())
            continue
        if _BULLET_RE.match(line) and not line[:1].isspace():
            items.append(_BULLET_RE.match(line).group(1).strip())
    flush_table()
    return items


def extract_headings(text: str) -> list[str]:
    """Return the text of every `###` heading in `text`, in document order."""
    headings: list[str] = []
    for line, in_fence in _iter_lines(text):
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading and len(heading.group(1)) == 3:
            headings.append(heading.group(2).strip())
    return headings


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id()s of the Constant nodes that are docstrings (not rules, not pins)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.add(id(value))
    return out


def _test_literals(path: Path) -> list[str]:
    """String constants in a test file, in source order, docstrings excluded."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return []
    skip = _docstring_nodes(tree)
    literals: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        value = node.value
        if len(value) < _MIN_PIN_CHARS or value in seen:
            continue
        seen.add(value)
        literals.append(value)
    return literals


def extract_pins(old: str, test_paths) -> list[str]:
    """Return the test literals (>= 10 chars) that occur verbatim in `old`.

    Ordered by first occurrence in `old`, deduplicated across files. Fences in
    `old` are not skipped: a pinned literal inside a fenced command still pins.
    """
    found: list[str] = []
    seen: set[str] = set()
    for path in test_paths:
        for literal in _test_literals(Path(path)):
            if literal in seen or literal not in old:
                continue
            seen.add(literal)
            found.append(literal)
    found.sort(key=old.index)
    return found


def pin_tests_for(src, root):
    """Return the `skills/**/test_*.py` files that name `src`; a `# pin-source: <path>` line declares one.

    A test names the source when its text contains the source's repo-relative
    path, `dir/basename` joined (literal or a path-join), its basename in a test
    inside the source's own dir, or (skill sources only, under `skills/`) its
    dir name plus `skill_text` — a test reading the skill.
    """
    root = Path(root)
    src_path = Path(src)
    if src_path.is_absolute():
        rel = src_path.resolve().relative_to(root.resolve())
    else:
        rel = src_path
    rel_text = rel.as_posix()
    basename = rel.name
    dir_name = rel.parent.name if rel.parent.name else basename
    join_re = re.compile(
        r"""["']""" + re.escape(dir_name) + r"""["']\s*[/,]\s*["']""" + re.escape(basename) + r"""["']"""
    )

    matches = []
    for test in sorted(root.glob("skills/**/test_*.py")):
        try:
            body = test.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        helper_arm = "skill_text" in body and rel_text.startswith("skills/")
        own_dir = (root / rel.parent).resolve() in test.resolve().parents
        if (
            rel_text in body
            or f"{dir_name}/{basename}" in body
            or join_re.search(body)
            or (own_dir and basename in body)
            or (dir_name in body and helper_arm)
        ):
            matches.append(test)
    return matches


# -------------------------------------------------------------------- #
# slices and span_lines — where to cut a source (plan Procedure S step 1)
# -------------------------------------------------------------------- #

# A cut may move onto a heading of these levels only (the plan names `## `/`### `).
SLICE_HEADING_LEVELS = (2, 3)
# How far a cut may move, as a fraction of the span's line count.
NUDGE_FRACTION = 0.15
# Span endpoints a caller can name instead of a heading prefix.
SPAN_START_TOP = "^"
SPAN_END_LAST = "EOF"


def _numbered_lines(text: str):
    """Yield (1-based line number, line, inside_a_fence) for every line."""
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            yield number, line, True
            continue
        yield number, line, in_fence


def _headings(text: str, levels=None) -> list[tuple[int, str]]:
    """(line number, stripped text) for every ATX heading outside a fence."""
    found: list[tuple[int, str]] = []
    for number, line, in_fence in _numbered_lines(text):
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match and (levels is None or len(match.group(1)) in levels):
            found.append((number, line.strip()))
    return found


def _split_span(within: str) -> tuple[str, str]:
    start, _, end = within.partition("..")
    return start, end


def _unique_heading(headings, prefix: str, which: str) -> int:
    """The one line number whose heading starts with `prefix`."""
    key = prefix.strip()
    hits = [number for number, text in headings if text.startswith(key)]
    if not hits:
        raise ValueError(f"span {which} {prefix!r} matches no heading")
    if len(hits) > 1:
        raise ValueError(f"span {which} {prefix!r} is ambiguous: lines {hits}")
    return hits[0]


def span_lines(text: str, start: str, end: str) -> tuple[int, int]:
    """Resolve a `S..E` heading span to an inclusive 1-based line range.

    `start` is the heading line beginning with it ("^" = line 1); `end` is the
    first *later* heading beginning with it and the span stops on the line
    before it ("EOF" = last line). A fenced heading is example text, never a
    boundary. A missing or ambiguous `start`, and an `end` with no later
    heading, raise: guessing would slice the wrong section.
    """
    headings = _headings(text)
    lo = 1 if start.strip() == SPAN_START_TOP else _unique_heading(headings, start, "start")
    if end.strip() in (SPAN_END_LAST, ""):
        return lo, len(text.splitlines())
    later = [n for n, body in headings if n > lo and body.startswith(end.strip())]
    if not later:
        raise ValueError(f"span end {end!r} matches no heading after line {lo}")
    return lo, later[0] - 1


def _balanced_cuts(weights: list[int], lo: int, hi: int, count: int) -> list[int]:
    """Cut-after line numbers minimising the widest segment (chars, not lines)."""
    total = sum(weights[lo - 1:hi])
    low, high = max(weights[lo - 1:hi]), total

    def segments(limit: int) -> int:
        used, cur = 0, lo
        while cur <= hi:
            acc = 0
            while cur <= hi and acc + weights[cur - 1] <= limit:
                acc += weights[cur - 1]
                cur += 1
            used += 1
        return used

    while low < high:
        mid = (low + high) // 2
        if segments(mid) > count:
            low = mid + 1
        else:
            high = mid
    limit = low
    cuts: list[int] = []
    cur = lo
    for index in range(count - 1):
        room = hi - (count - index - 1)  # leave one line per remaining segment
        acc, best = 0, cur
        for line in range(cur, room + 1):
            if acc + weights[line - 1] > limit:
                break
            acc += weights[line - 1]
            best = line
        cuts.append(best)
        cur = best + 1
    return cuts


def _nudge_to_headings(cuts, headings, lo: int, hi: int) -> list[int]:
    """Move each cut onto the nearest `## `/`### ` heading inside the window."""
    window = NUDGE_FRACTION * (hi - lo + 1)
    starts = [n - 1 for n, _ in headings if lo < n <= hi]
    nudged: list[int] = []
    for index, cut in enumerate(cuts):
        ceiling = cuts[index + 1] if index + 1 < len(cuts) else hi - 1
        floor = nudged[-1] if nudged else lo - 1
        near = [c for c in starts if floor < c < ceiling and abs(c - cut) <= window]
        nudged.append(min(near, key=lambda c: (abs(c - cut), c)) if near else cut)
    return nudged


def slices(text: str, count: int, within: str | None = None) -> list[tuple[int, int]]:
    """Cut `text` into `count` contiguous 1-based line ranges, each line once.

    The span is the whole text, or the heading span `within` ("S..E", see
    span_lines). Cuts sit on line boundaries and balance **chars**, then each
    cut moves onto a `## `/`### ` heading when one starts within ±15% of the
    span, so a section rarely straddles a slice boundary.
    """
    lines = text.splitlines()
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    lo, hi = (1, len(lines)) if within is None else span_lines(text, *_split_span(within))
    if count > hi - lo + 1:
        raise ValueError(f"count {count} exceeds the {hi - lo + 1} lines of the span")
    weights = [len(line) + 1 for line in lines]  # +1 for the newline
    level_headings = _headings(text, SLICE_HEADING_LEVELS)
    balanced = _balanced_cuts(weights, lo, hi, count)
    cuts = _nudge_to_headings(balanced, level_headings, lo, hi)
    bounds = [lo - 1] + cuts + [hi]
    return [(bounds[i] + 1, bounds[i + 1]) for i in range(len(bounds) - 1)]
