"""The `No guard claims.` sentinel is the whole section, never a substring of it.

design: audit-pass-does-not-bind (PR #162 proof round r1, test-quality finding 1).
`/tp-implementation-audit` Step 8b and `/tp-phase-review` Step 6b run
`certify.py run --artifact` BEFORE they fill `## Guards certified`, so at run time
the section still holds the shipped template placeholder, which quotes the sentinel
as one option. The placeholder must not declare "no claims": a tagged sentence for
a claim that binds stays matched and the audit is PASS.

Every artifact below is built from the real template line read out of the shipped
SKILL.md at test time; nothing here pastes a copy of it.
"""
# pin-source: skills/tp-implementation-audit/SKILL.md

from __future__ import annotations

from pathlib import Path

import pytest

import certify_cli
import certify_cli_checks
from cert_phrase_scan import NO_CLAIMS, SECTION_HEADING, parse_section, scan

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_SKILLS = ("tp-implementation-audit", "tp-phase-review")
CLAIMS = [{"id": "c1", "guard": "skills/x/test_y.py::test_z"}]
TAGGED = "The route test binds the rule [cert:c1]."


def section_of(text: str) -> str:
    """The body of the first `## Guards certified` section in `text`: every line after
    the heading up to the next heading or code fence, whatever its wording or layout."""
    lines = text[text.index(SECTION_HEADING + "\n") + len(SECTION_HEADING) + 1:].splitlines()
    body = []
    for line in lines:
        if line.startswith("#") or line.lstrip().startswith("```"):
            break
        body.append(line)
    return "\n".join(body).strip("\n")


def template_line(skill: str) -> str:
    """The shipped `## Guards certified` placeholder of `skill`'s report template: the
    section's body as written. The contract is only that it offers the sentinel as an
    option (quotes it), so an unfilled section is scanned while it still says so."""
    body = section_of((ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
    assert NO_CLAIMS in body, f"{skill}: the template section does not offer the sentinel"
    return body


def artifact(section_body: str, body: str = TAGGED) -> str:
    return (f"# Implementation audit\n\n{body}\n\n{SECTION_HEADING}\n{section_body}\n\n"
            "## Verdict\nPASS\n")


def binds_result() -> dict:
    return {"complete": True, "name": "impl-audit", "disposition": "verdict",
            "file_reasons": [], "statuses": ["binds"], "orphans": [], "tree_mutated": False,
            "claims": [{"id": "c1", "guard": CLAIMS[0]["guard"], "status": "binds",
                        "reasons": []}]}


# --- the unfilled template placeholder is not "no claims" ------------------------------
@pytest.mark.parametrize("skill", TEMPLATE_SKILLS)
def test_the_unfilled_placeholder_is_not_no_claims(skill):
    sec = parse_section(artifact(template_line(skill)))
    assert sec["present"] and sec["no_claims"] is False


@pytest.mark.parametrize("skill", TEMPLATE_SKILLS)
def test_a_tag_matches_while_the_section_still_holds_the_placeholder(skill):
    hits = scan(artifact(template_line(skill)), CLAIMS)
    # one hit, from the tagged body sentence (the placeholder adds none), and it matches
    assert [h["matched"] for h in hits] == [True] and hits[0]["text"] in TAGGED


@pytest.mark.parametrize("skill", TEMPLATE_SKILLS)
def test_run_artifact_passes_a_binding_claim_before_the_section_is_filled(skill):
    """End to end through `artifact_report` (the function behind `run --artifact`)."""
    report = certify_cli.artifact_report(binds_result(), artifact(template_line(skill)))
    assert [h["matched"] for h in report["hits"]] == [True], report["hits"]
    assert (report["verdict"], report["code"]) == ("PASS", 0), report


# --- the filled section ----------------------------------------------------------------
@pytest.mark.parametrize("section_body", [
    NO_CLAIMS, f"\n{NO_CLAIMS}\n", f"\n\n  {NO_CLAIMS}  \n\n", f"{NO_CLAIMS}\r\n"])
def test_exactly_the_sentinel_is_no_claims(section_body):
    """Blank lines around it and whitespace at the line's ends (incl. CR) are tolerated."""
    assert parse_section(artifact(section_body, body="Nothing in scope."))["no_claims"] is True


def test_the_sentinel_makes_a_tag_unmatched_and_a_clean_artifact_passes():
    hits = scan(artifact(NO_CLAIMS), CLAIMS)
    assert [h["matched"] for h in hits] == [False]
    clean = certify_cli_checks.scan_report(artifact(NO_CLAIMS, body="No guard is in scope."))
    assert (clean["hits"], clean["verdict"]) == ([], "PASS")


def test_a_filled_claim_list_is_not_no_claims_and_its_tag_matches():
    filled = "- [cert:c1] `skills/x/test_y.py::test_z` — rejects a bad rule — binds"
    assert parse_section(artifact(filled))["no_claims"] is False
    report = certify_cli.artifact_report(binds_result(), artifact(filled))
    assert [h["matched"] for h in report["hits"]] == [True] and report["verdict"] == "PASS"


@pytest.mark.parametrize("section_body", [
    f"{NO_CLAIMS} (the route test is out of scope)",
    f"{NO_CLAIMS}\n- [cert:c1] `skills/x/test_y.py::test_z` binds",
    f"Note: {NO_CLAIMS}",
    f"- {NO_CLAIMS}",
    f"`{NO_CLAIMS}`",
    NO_CLAIMS.lower(),
    f"{NO_CLAIMS}\n{NO_CLAIMS}",
])
def test_the_sentinel_with_other_text_is_not_no_claims(section_body):
    assert parse_section(artifact(section_body))["no_claims"] is False


def test_an_empty_section_is_not_no_claims():
    assert parse_section(artifact(""))["no_claims"] is False


# --- the template reader follows the section, not one wording or layout -----------------
@pytest.mark.parametrize("layout", [
    "{h}\n<mandatory: one line per claim, or exactly `{s}`>\n\n## Verdict\n",
    "{h}\n\n<required: one line per claim, or exactly `{s}`>\n\n## Verdict\n",
    "{h}\n- one line per claim\n- or exactly `{s}`\n```\n",
], ids=["as-shipped", "blank-line-reworded", "bulleted-in-fence"])
def test_the_template_reader_survives_a_contract_preserving_reword(layout):
    body = section_of("# Report\n\n" + layout.format(h=SECTION_HEADING, s=NO_CLAIMS))
    assert NO_CLAIMS in body and not body.startswith("\n")
    assert parse_section(artifact(body))["no_claims"] is False
    assert [h["matched"] for h in scan(artifact(body), CLAIMS)] == [True]
