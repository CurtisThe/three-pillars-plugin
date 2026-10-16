"""Tests for context_scout.trim and needs_refresh (design: local-role-routing, Task 5.2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_scout  # noqa: E402

HEADER = "context scout"
NO_DESIGN = "no design dir found"
SLOT_LOST = "scout unavailable: slot-lost"


def _cited(n):
    return "\n".join(f"fact {i} (docs/file{i}.md:{i})" for i in range(n))


def test_trim_keeps_first_25_cited_lines_plus_header():
    out = context_scout.trim(_cited(30)).splitlines()
    assert out[0] == HEADER
    assert len(out) == 26
    assert "fact 24 (docs/file24.md:24)" in out
    assert not any("fact 25 " in line for line in out)


def test_trim_drops_uncited_lines():
    out = context_scout.trim("chatter with no file\nkeep (a/b.py:3)\nmore chatter")
    assert out.splitlines() == [HEADER, "keep (a/b.py:3)"]


def test_trim_empty_returns_header_only_and_never_raises():
    assert context_scout.trim("") == HEADER
    assert context_scout.trim(None) == HEADER


def test_trim_known_header_no_design_is_kept():
    out = context_scout.trim(f"{NO_DESIGN}\n{_cited(30)}").splitlines()
    assert out[0] == NO_DESIGN
    assert len(out) == 26


def test_trim_known_header_slot_lost_is_kept():
    assert context_scout.trim(SLOT_LOST) == SLOT_LOST


def test_trim_max_lines_parameter():
    assert len(context_scout.trim(_cited(10), max_lines=3).splitlines()) == 4


def test_needs_refresh_same_files_false():
    assert context_scout.needs_refresh({"files": ["a.py"]}, ["a.py"]) is False


def test_needs_refresh_new_file_true():
    assert context_scout.needs_refresh({"files": ["a.py"]}, ["a.py", "b.py"]) is True


def test_needs_refresh_bad_meta_true_never_raises():
    assert context_scout.needs_refresh(None, ["a.py"]) is True
    assert context_scout.needs_refresh({}, ["a.py"]) is True
    assert context_scout.needs_refresh({"files": "a.py"}, ["a.py"]) is True
