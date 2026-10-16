"""test_ste_lint_calibration.py — STE lint calibrated on real design prose.

Covers explainer-agent plan Task 3.3 (detailed-design §Test Strategy: "A
calibration test shows that design.md's Problem and Behaviors prose passes,
and a known non-STE paragraph fails."):
  - one envelope whose ste_summary and description items are the Problem
    sentences and whose list items are the eight Behaviors passes lint;
  - a paragraph of long sentences holding `leverage` and `seamless` fails.

This test ships to consumer repos, so it reads no three-pillars-docs/ file:
the prose is inlined below (skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ste_lint  # noqa: E402

# Copied verbatim from three-pillars-docs/completed-tp-designs/explainer-agent/design.md
# §Problem (its sentences, in order) at implement time.
PROBLEM = (
    ("The operator's decision bandwidth, not compute, caps how many runs "
     'they can shepherd (`vision.md` § the operator-bandwidth thesis).'),
    ('Today a PR reaches the merge click with a diff, a review digest and '
     'a decisions log, and the operator rebuilds the story by hand.'),
    ('Fable rulings made without the operator are buried in '
     '`decisions.md`.'),
    ('Dogfood 1 (PR #243) showed the fix works: a hand-written STE-80 '
     'brief with a diagram, the change placed in the whole system and '
     'every default stated, let the operator catch a wrong default at '
     'once.'),
    ('This design makes that brief, and the explained ruling, a product: '
     'one explainer that restates supplied evidence in STE-80 prose and '
     'safe diagrams, with deterministic gates and fail-open, visible '
     'delivery.'),
)

# Copied verbatim from three-pillars-docs/completed-tp-designs/explainer-agent/design.md
# §Behaviors (the eight items, without their list numbers) at implement time.
BEHAVIORS = (
    ('**Request.** The caller names the kind and subject; the system '
     'builds the evidence bundle with ref ids. The drafter never reads '
     'outside it.'),
    ('**Draft.** The `explainer` role resolves the drafter: '
     "`role_engines.explainer: local` (independent of the run's `--local` "
     'flag until one-cheap-engine) → Strata via the Strata-spawn '
     'discipline (busy → Sonnet at once); key unset or no backend → '
     'Sonnet; `role_engines.explainer: opus` → Opus drafts every kind. A '
     'per-kind config override can pin pr-brief or human-escalation '
     'drafting to Opus without code change, and wins for its kind.'),
    ('**Gate (every draft).** Schema + required sections for the kind; '
     'evidence-ref validator; STE lint; diagram sanitizer. One rewrite on '
     'any failure. Still failing: unsupported claims are dropped '
     'deterministically, a lint miss ships with a visible style note, an '
     'unusable diagram is omitted; if the summary itself is unsupported, a '
     'deterministic facts-only envelope is used, labelled as such.'),
    ('**Check.** pr-brief and human-escalation envelopes get one Opus '
     'check against the same bundle (judgment stays Opus); auto-rulings '
     'need only the gates. The outcome is recorded in telemetry; a report '
     'prints the rewrite rate per drafter engine.'),
    ('**Render.** Deterministic renderers produce HTML (offline-asserted), '
     'forge markdown, card text (question first, ELI5 options, recommended '
     'first, HTML link), and a log entry.'),
    ('**Deliver pr-brief.** At PR creation: draft, commit `brief.md` '
     '(stamped with the briefed head SHA) in the archival commit, open the '
     'PR, post the comment (marker-tagged), write the local HTML, '
     'optionally publish the artifact. Explainer failure never blocks the '
     'commit or the PR: it logs one line and the PR opens with a "brief '
     'unavailable" note.'),
    ('**Refresh.** When the PR head differs from the briefed SHA (Tier 7 '
     'end, or by hand before merge), re-draft from the new evidence and '
     'edit the comment and HTML in place. A refresh never commits, so it '
     'cannot move the head it describes; the committed `brief.md` stays '
     'the PR-open snapshot, labelled with its SHA.'),
    ('**Rolling rulings.** Each auto-ruling appends to the ledger; when a '
     'PR exists, the one rulings comment is rebuilt and edited in place '
     "(found by stored id, else by marker, else posted). Past the forge's "
     'comment cap, older rulings collapse to headlines plus the HTML link. '
     'Rulings made before the PR exists are posted when it opens (a '
     'rulings sync beside the brief post). A ruling made after the '
     'archival commit stays out of the tree, so it never moves the briefed '
     'head.'),
)

# A known non-STE paragraph: long sentences, jargon and filler.
NON_STE = (
    "In order to fully leverage the many capabilities that the new platform "
    "offers to every team across the whole organization, we have designed "
    "an approach that brings all of the existing tools together into one "
    "single place for everyone to use. The resulting experience is seamless "
    "for each and every user, because all of the many different moving "
    "parts that used to require manual work from several separate teams "
    "now happen automatically behind the scenes without any further effort."
)

_REFS = ["design:problem"]


def _cited(text, **extra):
    return {"text": text, "refs": list(_REFS), **extra}


def _envelope(summary, description_items, list_items):
    return {
        "schema": "explain-envelope/v1",
        "kind": "pr-brief",
        "ste_summary": _cited(summary),
        "sections": [
            {"id": "what-merging", "title": "What you are merging",
             "items": [_cited(t, form="description")
                       for t in description_items]},
            {"id": "whole-system", "title": "Where it sits",
             "items": [_cited(t) for t in list_items]},
        ],
        "diagram_specs": [],
        "confidence_note": _cited(""),
    }


def test_design_problem_and_behaviors_prose_passes():
    env = _envelope(PROBLEM[0], PROBLEM[1:], BEHAVIORS)
    result = ste_lint.lint(env)
    assert result["passed"] is True, result["issues"]


def test_known_non_ste_paragraph_fails():
    result = ste_lint.lint(_envelope(NON_STE, (), ()))
    assert result["passed"] is False
    rules = {issue["rule"] for issue in result["issues"]}
    assert {"banned", "hard-length"} <= rules
