"""Pure-unit tests for `living_doc_carry.regenerate_preamble_date` (task 1.3).

Derives the preamble's `*Last updated:*` **date** from the doc's most-recent `## History`
bullet — the ONLY byte-deterministic part of a preamble conflict (the `Most recent: …`
summary is a human paraphrase and is never fabricated). Total: absent / empty / no-match /
malformed all → `None` → defer. Split from `test_living_doc_carry.py` (pre-decided axis) to
keep each file under the 300-line cap.

The dated-bullet shape mirrors `verify.LOG` / `classify.LOG_ENTRY`: a bold ISO date followed
by an em-dash (U+2014). A bare bold date without the trailing em-dash is deliberately NOT a
match.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from living_doc_carry import regenerate_preamble_date  # noqa: E402

EM = "—"  # em-dash, the atom-bullet anchor


def _doc(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# ---- present → the History date ---------------------------------------------


def test_history_with_dated_bullet_returns_date():
    text = _doc(
        "# known_issues",
        "",
        "## History",
        "",
        f"- **2026-07-09** {EM} triaged M18 residual",
    )
    assert regenerate_preamble_date(text) == "2026-07-09"


def test_roadmap_history_heading_contains_history_matches():
    # Heading TEXT contains "History" (roadmap's `## Roadmap History`) → matches, per
    # reconcile_docs._is_in_history's contains-semantics.
    text = _doc(
        "# product_roadmap",
        "",
        "## Roadmap History",
        "",
        f"- **2026-06-30** {EM} shipped the carry primitive",
    )
    assert regenerate_preamble_date(text) == "2026-06-30"


def test_multiple_dated_bullets_returns_topmost():
    text = _doc(
        "## History",
        "",
        f"- **2026-07-09** {EM} newest (prepended)",
        f"- **2026-07-01** {EM} older",
        f"- **2026-06-15** {EM} oldest",
    )
    assert regenerate_preamble_date(text) == "2026-07-09"


# ---- F4 bounded scan: a later section's date must never leak in --------------


def test_bounded_scan_returns_history_date_not_later_section():
    text = _doc(
        "## History",
        "",
        f"- **2026-07-09** {EM} the History date",
        "",
        "## Roadmap",
        "",
        f"- **2026-08-01** {EM} a later, unrelated dated bullet",
    )
    assert regenerate_preamble_date(text) == "2026-07-09"


def test_bounded_scan_empty_history_does_not_borrow_later_date():
    # History section is empty (next ATX heading immediately follows); the later section
    # HAS a dated bullet — it must NOT leak across the heading boundary.
    text = _doc(
        "## History",
        "## Roadmap",
        "",
        f"- **2026-08-01** {EM} later-section date",
    )
    assert regenerate_preamble_date(text) is None


# ---- F4 em-dash required: a bare bold date is not an atom bullet -------------


def test_bare_bold_date_without_em_dash_not_matched():
    text = _doc(
        "## History",
        "",
        "- **2026-07-09** did a thing with a hyphen - not an em-dash",
    )
    assert regenerate_preamble_date(text) is None


# ---- absent / empty / no-match → None ---------------------------------------


def test_history_absent_returns_none():
    text = _doc("# vision", "", "## Principles", "", "- be excellent")
    assert regenerate_preamble_date(text) is None


def test_history_present_but_empty_returns_none():
    text = _doc("## History", "## Next Section", "", "some prose")
    assert regenerate_preamble_date(text) is None


def test_history_present_no_dated_bullet_returns_none():
    text = _doc(
        "## History",
        "",
        "Some prose but no dated bullet lives here.",
        "- a plain bullet, no bold date",
    )
    assert regenerate_preamble_date(text) is None


# ---- total: malformed / raising input → None, never raises ------------------


def test_malformed_input_returns_none_never_raises():
    for bad in (None, 123, 4.5, ["## History"], {"a": 1}, object()):
        assert regenerate_preamble_date(bad) is None, repr(bad)


def test_empty_string_returns_none():
    assert regenerate_preamble_date("") is None
