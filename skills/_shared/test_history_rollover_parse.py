"""Tests for history_rollover.parse_history — the pinned History-span run rule
(split out of test_history_rollover.py to keep each test file under the soft cap).

The run starts at the first column-0 `- ` bullet; indented lines continue an
entry; blank lines do not end it; the first non-blank column-0 line that is
neither a bullet nor indented ends it, as does the next `## `. The History
heading must be an h2 whose title contains `History`; the first one wins.

Run with: python -m pytest skills/_shared/test_history_rollover_parse.py -q
"""
from __future__ import annotations

from history_rollover import parse_history




def _firsts(span):
    return [entry[0].rstrip("\n") for entry in span.entries]


def test_parse_run_starts_at_first_column0_bullet_and_collects_indented_continuations():
    span = parse_history("## History\n- a\n  - sub\n- b\n")
    assert _firsts(span) == ["- a", "- b"]
    assert span.entries[0][1].rstrip("\n") == "  - sub"


def test_parse_blank_lines_inside_the_run_do_not_end_it():
    assert _firsts(parse_history("## History\n- a\n\n- b\n")) == ["- a", "- b"]


def test_parse_run_ends_at_first_nonbullet_column0_line_and_next_heading():
    assert _firsts(parse_history("## History\n- a\n\n*Newest-first*\n- stray\n")) == ["- a"]
    assert _firsts(parse_history("## History\n- a\n## Next\n- other\n")) == ["- a"]


def test_parse_history_heading_must_be_h2_and_first_wins():
    assert parse_history("### History\n- a\n") is None
    assert parse_history("## Roadmap History\n- a\n").heading is not None
    span = parse_history("## History (old ledger)\n- kept\n## History\n- other\n")
    assert _firsts(span) == ["- kept"]


def test_parse_returns_none_when_no_history_heading_exists():
    assert parse_history("# Known Issues — RESOLVED archive\n\n> preamble\n\n- entry\n") is None
