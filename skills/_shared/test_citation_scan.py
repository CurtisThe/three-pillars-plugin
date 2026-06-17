"""Number-cite regex match tests (one direction) for citation_scan.

Exclusion (non-match) cases live in test_citation_scan_exclusions.py; count-cite
allowlist tests live in test_citation_scan_count.py.

design: invariant-citation-coherence
"""

from __future__ import annotations

from citation_scan import find_number_cites_in_line


def _cites(line: str) -> list[int]:
    return find_number_cites_in_line(line)


# ------------------------------------------------------------------ #
# Keyword-led matches.
# ------------------------------------------------------------------ #


def test_invariant_hash_number():
    assert _cites("see invariant #21 for details") == [21]


def test_invariant_bare_number():
    assert _cites("see invariant 21 for details") == [21]


def test_inv_hash_number():
    assert _cites("per inv #30") == [30]


def test_inv_bare_number():
    assert _cites("per inv 30") == [30]


def test_plural_invariants():
    assert _cites("the invariants 21 battery") == [21]


# ------------------------------------------------------------------ #
# Bold / decorated forms in invariant context.
# ------------------------------------------------------------------ #


def test_bold_hash_number_keyword_led():
    assert _cites("the invariant **#27** rule") == [27]


def test_backtick_hash_number_keyword_led():
    assert _cites("the invariant `#27` rule") == [27]


def test_bold_number_first():
    assert _cites("the **#27** invariant") == [27]


def test_backtick_number_first():
    assert _cites("the `#27` invariant") == [27]


# ------------------------------------------------------------------ #
# Number-first forms.
# ------------------------------------------------------------------ #


def test_number_first_the_x_invariant():
    assert _cites("the #27 invariant guards commits") == [27]


def test_number_first_class_invariant():
    assert _cites("a #27-class invariant fires here") == [27]


def test_number_first_inv_keyword():
    assert _cites("the #30 inv block") == [30]


# ------------------------------------------------------------------ #
# Chained forms — context established BEFORE the /-split (reminder (a)).
# ------------------------------------------------------------------ #


def test_chained_keyword_led_two_members():
    # "invariant #31/#32" — invariant-context, both flagged.
    assert _cites("invariant #31/#32 interplay") == [31, 32]


def test_chained_keyword_led_three_members():
    assert _cites("invariant #25/#26/#27 all apply") == [25, 26, 27]


def test_chained_hash_only_in_invariant_context():
    # "#31/#32" inside an explicit invariant context still flags both, via the
    # keyword establishing context before the split.
    assert _cites("the invariant #31/#32 pair") == [31, 32]


def test_chained_with_decoration_members():
    assert _cites("invariant #25/`#26`/#27 apply") == [25, 26, 27]


# ------------------------------------------------------------------ #
# Out-of-range integration via scan_number_cites is covered in count file;
# here assert the line-level helper sees the integer regardless of validity.
# ------------------------------------------------------------------ #


def test_out_of_range_number_still_extracted_at_line_level():
    # The helper extracts the integer; range-checking is the scan's job.
    assert _cites("invariant #99 does not exist") == [99]
