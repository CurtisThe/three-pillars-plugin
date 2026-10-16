"""md_transforms.py — CommonMark-flavoured block splitter and behaviour-preserving
markdown transforms (design: fragile-test-prevention, detailed-design-stages.md
Part C3).

`blocks(text)` splits markdown text into blocks: frontmatter, fenced code (a
heading-looking line inside a fence stays code, never a heading block), ATX
heading, list item, table, blockquote, HTML, blank and paragraph. Each block
keeps its raw lines, and `"\\n".join` of every block's lines, in order,
reconstructs the original text exactly.

`reflow` and `reorder_sections` are the two transforms `refactor_invariance.py`
(Part C3) replays against a phase's changed files: each changes only what it
claims to change, so a test that still fails after the transform is pinning
something other than behaviour.
"""
from __future__ import annotations

import re
import textwrap

_ATX_RE = re.compile(r"^#{1,6}(\s|$)")
_FENCE_RE = re.compile(r"^(```+|~~~+)")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_HTML_RE = re.compile(r"^\s*<[a-zA-Z!/]")
_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _is_table_delim(line: str) -> bool:
    return bool(_TABLE_DELIM_RE.match(line))


def _fence_marker(line: str):
    m = _FENCE_RE.match(line.strip())
    return line.strip()[: len(m.group(1))] if m else None


def _starts_special(line: str) -> bool:
    stripped = line.strip()
    return bool(
        _ATX_RE.match(line)
        or _FENCE_RE.match(stripped)
        or _LIST_RE.match(line)
        or _BLOCKQUOTE_RE.match(line)
        or _HTML_RE.match(line)
    )


def blocks(text: str) -> list[dict]:
    """Split `text` into CommonMark-flavoured blocks; each keeps its raw lines.

    `"\\n".join(line for b in blocks(text) for line in b["lines"])` reconstructs
    `text` exactly (including a missing or trailing final newline).
    """
    lines = text.split("\n")
    n = len(lines)
    result: list[dict] = []
    i = 0
    if n and lines[0].strip() == "---":
        closed_at = None
        for j in range(1, n):
            if lines[j].strip() in ("---", "..."):
                closed_at = j
                break
        if closed_at is not None:
            result.append({"kind": "frontmatter", "lines": lines[0 : closed_at + 1]})
            i = closed_at + 1
    while i < n:
        line = lines[i]
        if _is_blank(line):
            j = i
            while j < n and _is_blank(lines[j]):
                j += 1
            result.append({"kind": "blank", "lines": lines[i:j]})
            i = j
            continue
        marker = _fence_marker(line)
        if marker is not None:
            j = i + 1
            while j < n and not lines[j].strip().startswith(marker):
                j += 1
            j = j + 1 if j < n else n
            result.append({"kind": "fenced_code", "lines": lines[i:j]})
            i = j
            continue
        if _ATX_RE.match(line):
            result.append({"kind": "atx_heading", "lines": [line]})
            i += 1
            continue
        if "|" in line and i + 1 < n and _is_table_delim(lines[i + 1]):
            j = i
            while j < n and "|" in lines[j] and not _is_blank(lines[j]):
                j += 1
            result.append({"kind": "table", "lines": lines[i:j]})
            i = j
            continue
        if _BLOCKQUOTE_RE.match(line):
            j = i
            while j < n and _BLOCKQUOTE_RE.match(lines[j]):
                j += 1
            result.append({"kind": "blockquote", "lines": lines[i:j]})
            i = j
            continue
        if _HTML_RE.match(line):
            j = i
            while j < n and not _is_blank(lines[j]):
                j += 1
            result.append({"kind": "html", "lines": lines[i:j]})
            i = j
            continue
        if _LIST_RE.match(line):
            j = i + 1
            while j < n and not _is_blank(lines[j]) and not _starts_special(lines[j]):
                j += 1
            result.append({"kind": "list_item", "lines": lines[i:j]})
            i = j
            continue
        j = i
        while j < n and not _is_blank(lines[j]) and not _starts_special(lines[j]):
            j += 1
        if j == i:
            j = i + 1
        result.append({"kind": "paragraph", "lines": lines[i:j]})
        i = j
    return result


def _join(block_list: list[dict]) -> str:
    out: list[str] = []
    for b in block_list:
        out.extend(b["lines"])
    return "\n".join(out)


def reflow(text: str, width: int) -> str:
    """Re-wrap paragraph blocks only, at `width`. Every other block is untouched."""
    out = []
    for b in blocks(text):
        if b["kind"] == "paragraph":
            joined = " ".join(" ".join(line.split()) for line in b["lines"]).strip()
            # break_long_words/break_on_hyphens=False: a rewrapped line never
            # splits *inside* a word (hyphenated or not), so joining wrapped
            # lines back with spaces always recovers the exact original words.
            wrapped = (
                textwrap.wrap(
                    joined, width=max(width, 1), break_long_words=False, break_on_hyphens=False
                )
                if joined
                else []
            )
            out.append({"kind": "paragraph", "lines": wrapped or [""]})
        else:
            out.append(b)
    return _join(out)


def _heading_level(b: dict) -> int:
    line = b["lines"][0]
    return len(line) - len(line.lstrip("#"))


def reorder_sections(text: str) -> str:
    """Reverse sibling sections at the shallowest heading level with 2+ headings.

    Frontmatter and the preamble (everything before the first section-level
    heading) stay first. Headings inside a fenced code block are never seen
    here — `blocks()` already folded the fence into one `fenced_code` block.
    """
    bl = blocks(text)
    heading_idxs = [i for i, b in enumerate(bl) if b["kind"] == "atx_heading"]
    if not heading_idxs:
        return text
    levels = [_heading_level(bl[i]) for i in heading_idxs]
    chosen = next((level for level in range(1, 7) if levels.count(level) >= 2), None)
    if chosen is None:
        return text
    starts = [i for i in heading_idxs if _heading_level(bl[i]) == chosen]
    preamble = bl[: starts[0]]
    sections = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(bl)
        sections.append(bl[start:end])
    flat = list(preamble)
    for section in reversed(sections):
        flat.extend(section)
    return _join(flat)
