"""prose_question.py — spot a question left to the operator as prose (pure core).

design: seat-escalate-first 3.1. The Stop hook hands over a session's last assistant
message; `question_text` says whether it ends in a question for the operator and, when it
does, returns a one-line summary of it. `question_block` (design:
seat-scope-interactive-questions 1.4 B3) returns the same question as its own contiguous
lines — the question line plus its option lines — the span the seat's prose classifier
reads. Pure and stdlib-only: a string in, a string or None out; no I/O, no environment, no
pane chrome.

A message ends in a question for the operator when, over its last `tail` non-blank lines
(bold `**` stripped, indentation measured and then stripped):

- it ends in an options run (two or more numbered or lettered options of one marker
  family; a line indented deeper than its marker continues the option above) that sits
  directly under a line ending in `?` or carrying "Needs your decision"; or
- it ends in an options run followed by exactly one final line ending in `?`; or
- its last line carries "Needs your decision" and ends in `?`; or
- it ends in a `-` / `*` bullet run directly under a line carrying "Needs your decision"
  (bullets never match under a plain `?` line: that is usually an explanatory list).

A marker preceded within a few characters by a negation ("None of these needs your
decision:") is not a marker.

An options run followed by more prose, a numbered summary with no question line, and a
plain closing question in running prose are not matched.
"""
from __future__ import annotations

import re

SUMMARY_MAX = 200
_MARKER = "needs your decision"

# One family per alternative: 1. / 1)  ·  (a) / a. / a)  ·  (A) / A. / A)
_FAMILIES = (
    re.compile(r"\d+[.)]\s+\S"),
    re.compile(r"\(?[a-z][.)]\s+\S"),
    re.compile(r"\(?[A-Z][.)]\s+\S"),
    re.compile(r"[-*•]\s+\S"),
)
_BULLET = 3
_NEGATED = re.compile(r"\b(?:no|none|nothing|not|nobody|never)\b|n't")

_Line = tuple[int, str]  # (indent width, text with indentation stripped)


def _lines(message: str, tail: int) -> list[_Line]:
    """The last `tail` non-blank lines as (indent, text), bold markup removed."""
    out: list[_Line] = []
    for raw in message.replace("**", "").splitlines():
        raw = raw.expandtabs(4)
        text = raw.strip()
        if text:
            out.append((len(raw) - len(raw.lstrip()), text))
    return out[-tail:] if tail > 0 else []


def _family(text: str) -> int | None:
    for index, pattern in enumerate(_FAMILIES):
        if pattern.match(text):
            return index
    return None


def _run_end(lines: list[_Line], start: int) -> int | None:
    """End (exclusive) of the options run opening at `start`, or None when it has fewer
    than two options. Option lines share one marker family and one indent; lines indented
    deeper than the markers continue the option above."""
    indent, text = lines[start]
    family = _family(text)
    if family is None:
        return None
    count, end = 1, start + 1
    while end < len(lines):
        line_indent, line_text = lines[end]
        if line_indent > indent:
            end += 1
        elif line_indent == indent and _family(line_text) == family:
            count += 1
            end += 1
        else:
            break
    return end if count >= 2 else None


def _marker(text: str) -> bool:
    """The line carries "Needs your decision", not negated just before it."""
    before, found, _ = text.lower().partition(_MARKER)
    return bool(found) and not _NEGATED.search(before[-25:])


def _asks(text: str, bullets: bool) -> bool:
    return _marker(text) if bullets else text.endswith("?") or _marker(text)


def _from_options(lines: list[_Line]) -> tuple[int, int, int] | None:
    """(question line, run start, run end) for an options run that ends the message."""
    i = 0
    while i < len(lines):
        end = _run_end(lines, i)
        if end is None:
            i += 1
            continue
        bullets = _family(lines[i][1]) == _BULLET
        if end == len(lines):  # the run ends the message: question directly above
            if i > 0 and _asks(lines[i - 1][1], bullets):
                return i - 1, i, end
        elif not bullets and end == len(lines) - 1 and lines[-1][1].endswith("?"):
            return len(lines) - 1, i, end  # the run, then one final question line
        i = end
    return None


def _span(lines: list[_Line]) -> tuple[int, int, int] | None:
    """(question line, block start, block end) for the question the message ends in."""
    found = _from_options(lines)
    if found is not None:
        return found
    last = lines[-1][1]
    if _marker(last) and last.endswith("?"):
        return len(lines) - 1, len(lines) - 1, len(lines)  # the marker line alone
    return None


def _span_of(message: str | None, tail: int):
    """(lines, span) for a message, or None when it ends in no question for the operator."""
    if not isinstance(message, str) or not message.strip():
        return None
    lines = _lines(message, tail)
    if not lines:
        return None
    span = _span(lines)
    return None if span is None else (lines, span)


def _summarise(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > SUMMARY_MAX:
        text = text[: SUMMARY_MAX - 1].rstrip() + "…"
    return text


def _block(lines: list[_Line], q: int, start: int, end: int) -> str:
    """The question block in message order: the question line directly above the run plus
    the run, or the run plus the one final question line, or the marker line alone."""
    if q == start - 1:
        part = lines[start - 1:end]
    elif q >= end:
        part = lines[start:]
    else:
        part = lines[start:end]
    return "\n".join(text for _, text in part)


def question_block(message: str | None, tail: int = 16) -> str | None:
    """The question the message ends in as contiguous lines, else None (design B3): the
    seat's prose classifier reads this and nothing else of the message."""
    found = _span_of(message, tail)
    if found is None:
        return None
    lines, (q, start, end) = found
    return _block(lines, q, start, end)


def question_text(message: str | None, tail: int = 16) -> str | None:
    """One-line summary of the question the message leaves for the operator, else None."""
    found = _span_of(message, tail)
    if found is None:
        return None
    lines, (q, _, _) = found
    return _summarise(lines[q][1])
