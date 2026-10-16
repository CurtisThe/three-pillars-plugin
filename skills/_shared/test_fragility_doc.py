"""test_fragility_doc.py — ``test-fragility.md`` names the oracle registry.

design: fragile-test-prevention (detailed-design-stages Part A)

The rule doc never keeps a second copy of the oracle types: it names each
registered type as an inline code span and points at the registry module. The
checks run on the doc's parsed code spans (a CommonMark backtick-run scan that
skips fenced blocks), never on the wording of the prose.
"""
from __future__ import annotations

import re
from pathlib import Path

import task_oracle

DOC = Path(__file__).resolve().parent / "test-fragility.md"
REPO = Path(task_oracle.__file__).resolve().parents[2]
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_RUN = re.compile(r"`+")


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks of ``text`` outside fenced code blocks."""
    blocks: list[str] = []
    cur: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            blocks.append("\n".join(cur))
            cur = []
            continue
        if line.strip():
            cur.append(line)
        else:
            blocks.append("\n".join(cur))
            cur = []
    blocks.append("\n".join(cur))
    return [b for b in blocks if b]


def code_spans(text: str) -> set[str]:
    """Inline code spans: a backtick run closes at the next run of equal length."""
    spans: set[str] = set()
    for block in _paragraphs(text):
        runs = list(_RUN.finditer(block))
        i = 0
        while i < len(runs):
            n = len(runs[i].group())
            close = next((j for j in range(i + 1, len(runs))
                          if len(runs[j].group()) == n), None)
            if close is None:
                i += 1
                continue
            body = block[runs[i].end():runs[close].start()].replace("\n", " ")
            if body.strip(" ") and body.startswith(" ") and body.endswith(" "):
                body = body[1:-1]
            spans.add(body)
            i = close + 1
    return spans


def test_scanner_reads_single_and_double_backtick_spans():
    assert code_spans("a `x` b ``y ` z`` c") == {"x", "y ` z"}


def test_scanner_ignores_fenced_blocks_and_unclosed_runs():
    text = "```py\n`hidden`\n```\nan `` unclosed run and `shown`\n"
    assert code_spans(text) == {"shown"}


def test_scanner_joins_a_span_across_a_line_break():
    assert code_spans("see `a\nb` end") == {"a b"}


def test_doc_names_every_registered_oracle_type():
    spans = code_spans(DOC.read_text(encoding="utf-8"))
    assert set(task_oracle.ORACLE_TYPES) <= spans


def test_doc_references_the_registry_module_by_path():
    spans = code_spans(DOC.read_text(encoding="utf-8"))
    target = Path(task_oracle.__file__).resolve()
    assert any((REPO / s).resolve() == target for s in spans)
