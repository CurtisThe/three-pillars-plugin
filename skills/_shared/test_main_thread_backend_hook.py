"""Prose pins for the main-thread backend check hook in first-run.md.

design: main-thread-direct-backend (S2)

The check is a separate `## Main-thread backend check` section after the
cheap-path early-exit (not a numbered cheap-path condition). It runs on every
invocation, cheap path included, and is fail-open.
"""
from __future__ import annotations

from pathlib import Path

FIRST_RUN_MD = Path(__file__).resolve().parent / "first-run.md"
HEADING = "## Main-thread backend check"


def _text() -> str:
    return FIRST_RUN_MD.read_text(encoding="utf-8")


def _section() -> str:
    text = _text()
    assert "\n" + HEADING in text, f"first-run.md has no {HEADING!r} section"
    return text.split("\n" + HEADING, 1)[1].split("\n## ", 1)[0]


def test_section_exists_and_names_the_check_command():
    assert "main_thread_backend.py check" in _section()


def test_section_says_it_also_runs_on_the_cheap_path():
    section = _section().lower()
    assert "cheap path" in section
    assert "every invocation" in section


def test_section_is_fail_open_and_never_blocks():
    section = _section().lower()
    assert "fail-open" in section
    assert "never blocks" in section


def test_section_follows_the_cheap_path_section():
    text = _text()
    assert text.index("\n## Cheap-path early-exit") < text.index("\n" + HEADING)


def test_helper_is_listed_in_the_failure_split_fail_open_line():
    text = _text()
    split = text.split("### Failure split", 1)[1]
    line = next(ln for ln in split.splitlines() if "Fail-open convenience helpers" in ln)
    assert "main_thread_backend.py" in line
