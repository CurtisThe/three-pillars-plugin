"""Tests for cert_phrase_scan.scan / parse_section — the certifying-phrase blocklist.

design: audit-pass-does-not-bind (Task 5.1; detailed-design.md §Interfaces [F5][R8][R9]).
A hit is `{text, field, matched}`; only `matched is False` hits escalate (the
fold's P5 rule). A nearby negator suppresses nothing (amended 2026-09-25).
"""

from __future__ import annotations

import pytest

from cert_phrase_scan import PHRASES, parse_section, scan, scan_field

SECTION = "## Guards certified\n\n- `skills/x/test_g.py` [cert:c1]\n"
CLAIMS = [{"id": "c1", "guard": "skills/x/test_g.py::test_binds"},
          {"id": "c2", "guard": "scripts/check.sh"}]


def doc(body: str, section: str = SECTION) -> str:
    return f"# Audit\n\n{body}\n\n{section}"


def counted(hits: list[dict]) -> list[dict]:
    return [h for h in hits if h["matched"] is False]


# --- literals and proximity ------------------------------------------------- #
@pytest.mark.parametrize("phrase", PHRASES)
def test_each_literal_hits(phrase):
    hits = scan_field(f"The new guard is {phrase} after the change.", "summary", [])
    assert len(counted(hits)) == 1
    assert phrase.lower() in hits[0]["text"].lower()
    assert hits[0]["field"] == "summary" and hits[0]["matched"] is False


@pytest.mark.parametrize("text", [
    "the tests catch it", "guards bind", "The guard binds the install route.",
    "this check really catches the regression", "the lint would catch a bare except",
    "the assertion went red before the fix", "both invariants goes red when broken",
    "the pin caught the drift", "the gate will go red", "Tests now bind.",
])
def test_proximity_forms_hit(text):
    assert len(counted(scan_field(text, "summary", []))) == 1


@pytest.mark.parametrize("text", [
    "the server binds 127.0.0.1 on start", "a reviewer would catch that",
    "binds", "we caught the bus", "the contest binds nobody",
])
def test_bare_verbs_are_not_hits(text):
    assert scan_field(text, "summary", []) == []


# --- negators suppress nothing (amended 2026-09-25) ------------------------ #
@pytest.mark.parametrize("text", [
    "no test catches X", "the lint does not bind", "the check never catches it",
    "there is nothing the guard catches", "the test doesn't bind",
    "the test can't catch this", "the test cannot catch a rename",
    "No flake, the guard binds.", "No flake--the guard binds.", "not, the guard binds",
    "it is never not vacuous", "the pin is not vacuous",
])
def test_a_phrase_near_a_negator_is_still_a_counted_hit(text):
    assert len(counted(scan_field(text, "summary", []))) == 1


# --- [cert:<id>] tags [R9, amended 2026-09-25: the tag alone binds] --------- #
def test_tag_and_guard_path_in_the_same_field_match():
    text = "The guard binds [cert:c1] (`skills/x/test_g.py`)."
    assert [h["matched"] for h in scan_field(text, "summary", CLAIMS)] == [True]


def test_a_tag_alone_matches_its_claim():
    """The tagged sentence need not name the claim's guard path (nor any path)."""
    for text in ("The guard binds [cert:c1].", "The guard binds [cert:c1] (see scripts/check.sh)."):
        assert [h["matched"] for h in scan_field(text, "summary", CLAIMS)] == [True], text


def test_unknown_id_is_unmatched():
    text = "The guard binds [cert:c9] skills/x/test_g.py."
    assert [h["matched"] for h in scan_field(text, "summary", CLAIMS)] == [False], \
        "a tag for an id with no returned claim must stay unmatched"


def test_untagged_hit_is_unmatched():
    assert [h["matched"] for h in scan_field("the guards bind", "s", CLAIMS)] == [False]


# --- markdown section ------------------------------------------------------- #
def test_parse_section_finds_body_and_rest():
    sec = parse_section(doc("The tests catch it."))
    assert sec["present"] and not sec["no_claims"]
    assert "[cert:c1]" in sec["body"] and "[cert:c1]" not in sec["rest"]
    assert "The tests catch it." in sec["rest"]


def test_missing_section_is_a_synthetic_hit():
    hits = scan("# Audit\n\nAll good.\n", CLAIMS)
    assert len(counted(hits)) == 1 and hits[0]["field"] == "section", \
        "an absent certified-guards section must escalate"


def test_section_body_is_excluded_from_the_scan():
    section = "## Guards certified\n\n- The guard binds [cert:c1] somewhere else.\n"
    assert scan(doc("Nothing to see.", section), CLAIMS) == []


def test_no_guard_claims_makes_every_hit_unmatched():
    body = "The guard binds [cert:c1] `skills/x/test_g.py`."
    assert [h["matched"] for h in scan(doc(body), CLAIMS)] == [True]
    no_claims = "## Guards certified\n\nNo guard claims.\n"
    assert [h["matched"] for h in scan(doc(body, no_claims), CLAIMS)] == [False]


def test_section_ends_at_the_next_heading():
    text = doc("Intro.", SECTION + "\n## Notes\n\nThe tests catch it.\n")
    assert len(counted(scan(text, CLAIMS))) == 1


def test_matching_is_per_paragraph_in_markdown():
    body = "The guard binds.\n\nSee [cert:c1]."
    assert [h["matched"] for h in scan(doc(body), CLAIMS)] == [False]
    assert [h["matched"] for h in scan(doc("See [cert:c1]: the guard binds."), CLAIMS)] == [True]


# --- KNOWN BYPASS: a rephrase escapes -------------------------------------- #
def test_pinned_rephrase_escapes_the_scan():
    rephrase = "We showed the check fails on the broken input and passes on the fix."
    assert scan(doc(rephrase), CLAIMS) == []


# --- Task 5.4 measurement pins (N14, P13) ----------------------------------- #
# Strings are paraphrased from the archived corpus (plan-notes 5.4); the numbers
# live in the design's measurements.md.
MEASURED_FALSE_POSITIVES = [
    # Slot 8 council member field: an imperative ("keep ... non-vacuous"), not a claim.
    "Pin the var list, keep case 1.2(a) non-vacuous after the scrub.",
]


def test_measured_false_positives():
    """Both slots logged insufficient-sample (P13), so no false positive was tuned
    away: each judged false positive is pinned as a still-counted hit. A later
    tuning flips its pin to a non-hit deliberately (one pinned non-hit per fix)."""
    for text in MEASURED_FALSE_POSITIVES:
        assert len(counted(scan_field(text, "members[x].argument_summary", []))) == 1
