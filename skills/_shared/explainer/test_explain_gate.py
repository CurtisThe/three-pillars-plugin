"""test_explain_gate.py — the draft gate and the one-rewrite prompt.

Covers explainer-agent plan Task 5.1 (detailed-design §Interfaces:
"explain_gate.run_gates(env, request) -> {"pass": bool, "failures": [...],
"diagrams_ok": [bool]} runs schema, refs, lint, then sanitize_spec per
diagram. rewrite_prompt(failures) -> str (one rewrite only; the caller counts
attempts)"):
  - a valid, cited, lint-clean envelope with one good diagram passes with no
    failures and diagrams_ok [True];
  - one defect at a time (a missing section, an unknown ref, a banned word, a
    raw-markup diagram) fails with its code: missing-section:<id>,
    unknown-ref:<id>, lint:<rule>, raw-diagram / diagram:<i>; only the bad
    diagram is False in diagrams_ok;
  - every failure is reported (no short-circuit), in gate order: schema,
    refs, lint, diagrams;
  - lint is decided on the lint result's "passed", never on "any issue";
  - rewrite_prompt names every failure code and says it is the only rewrite.

Every envelope and request is built here from the §Interfaces shapes; no repo
docs are read. Assertions are on the returned codes and fields
(skills/_shared/test-fragility.md); the only pinned text is the one-rewrite
sentence the plan's Red names.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_gate as eg  # noqa: E402
import ste_lint  # noqa: E402

ONLY_REWRITE = "This is your only rewrite."
GOOD_DIAGRAM = {"kind": "flow", "nodes": ["draft", "gate", "render"],
                "edges": [["draft", "gate"], ["gate", "render"]]}


def _request():
    return {
        "schema": "explain-request/v1",
        "kind": "auto-ruling",
        "slug": "demo",
        "subject": {},
        "evidence": [
            {"ref": "decision:1", "label": "Decision 1", "text": "Disk cache."},
            {"ref": "design:problem", "label": "Problem", "text": "Restarts."},
            {"ref": "diffstat", "label": "Diffstat", "text": "cache.py +40"},
        ],
        "evidence_head": "abc1234",
    }


def _item(text, ref):
    return {"text": text, "refs": [ref]}


def _envelope():
    """A valid, cited, lint-clean auto-ruling with one good diagram."""
    return {
        "schema": "explain-envelope/v1",
        "kind": "auto-ruling",
        "ste_summary": _item("The run picks the second option for the cache.",
                             "decision:1"),
        "sections": [
            {"id": "decided", "title": "Decided",
             "items": [_item("The run keeps the cache on disk.",
                             "decision:1")]},
            {"id": "why", "title": "Why",
             "items": [_item("A disk cache survives a restart.",
                             "design:problem")]},
            {"id": "commits-to", "title": "Commits to",
             "items": [_item("Later work reads the cache from disk.",
                             "diffstat")]},
        ],
        "diagram_specs": [dict(GOOD_DIAGRAM)],
        "confidence_note": _item("The diffstat shows the cache change.",
                                 "diffstat"),
    }


# ---------------------------------------------------------------------------
# The four single defects named by the plan's Red
# ---------------------------------------------------------------------------

def _drop_why(env):
    env["sections"] = [s for s in env["sections"] if s["id"] != "why"]


def _unknown_ref(env):
    env["sections"][0]["items"][0]["refs"] = ["design:nowhere"]


def _banned_word(env):
    env["ste_summary"]["text"] = "The run will leverage the disk cache."


def _raw_diagram(env):
    env["diagram_specs"] = [{"svg": "<svg></svg>"}]


DEFECTS = [
    (_drop_why, ["missing-section:why"], [True]),
    (_unknown_ref, ["unknown-ref:design:nowhere"], [True]),
    (_banned_word, ["lint:banned"], [True]),
    (_raw_diagram, ["raw-diagram", "diagram:0"], [False]),
]


def test_clean_envelope_passes():
    assert eg.run_gates(_envelope(), _request()) == {
        "pass": True, "failures": [], "diagrams_ok": [True], "diagram_reasons": [None]}


@pytest.mark.parametrize("defect,codes,diagrams_ok", DEFECTS,
                         ids=["missing-section", "unknown-ref", "banned",
                              "raw-diagram"])
def test_each_defect_fails_with_its_code(defect, codes, diagrams_ok):
    env = _envelope()
    defect(env)
    result = eg.run_gates(env, _request())
    assert result["pass"] is False
    for code in codes:
        assert code in result["failures"]
    assert result["diagrams_ok"] == diagrams_ok


def test_only_the_bad_diagram_is_false():
    env = _envelope()
    env["diagram_specs"] = [dict(GOOD_DIAGRAM), {"kind": "pie", "nodes": []}]
    result = eg.run_gates(env, _request())
    assert result["pass"] is False
    assert result["diagrams_ok"] == [True, False]
    assert "diagram:1" in result["failures"]
    assert "diagram:0" not in result["failures"]
    # An unusable spec that is not raw markup fails only the sanitizer step.
    assert "raw-diagram" not in result["failures"]


def test_an_item_with_no_ref_is_unsupported():
    env = _envelope()
    env["sections"][1]["items"][0]["refs"] = []
    result = eg.run_gates(env, _request())
    assert result["pass"] is False
    assert "unsupported:sections[1].items[0]" in result["failures"]


def test_every_failure_is_reported_in_gate_order():
    env = _envelope()
    for defect, _, _ in DEFECTS:
        defect(env)
    failures = eg.run_gates(env, _request())["failures"]
    expected = ["missing-section:why", "raw-diagram",
                "unknown-ref:design:nowhere", "lint:banned", "diagram:0"]
    for code in expected:
        assert code in failures
    # schema codes, then refs, then lint, then the per-diagram sanitizer.
    order = [failures.index(code) for code in
             ("missing-section:why", "unknown-ref:design:nowhere",
              "lint:banned", "diagram:0")]
    assert order == sorted(order)
    assert len(failures) == len(set(failures))


def test_lint_is_decided_on_passed_not_on_any_issue():
    env = _envelope()
    env["sections"][0]["items"].append(
        _item("The cache was written to disk.", "decision:1"))
    linted = ste_lint.lint(env)
    assert linted["passed"] is True and linted["issues"]  # a soft issue only
    assert eg.run_gates(env, _request()) == {
        "pass": True, "failures": [], "diagrams_ok": [True], "diagram_reasons": [None]}


def test_a_non_dict_envelope_fails_without_raising():
    result = eg.run_gates("not an envelope", _request())
    assert result["pass"] is False
    assert result["failures"]
    assert result["diagrams_ok"] == []


def test_rewrite_prompt_names_every_failure_and_the_one_rewrite():
    env = _envelope()
    for defect, _, _ in DEFECTS:
        defect(env)
    failures = eg.run_gates(env, _request())["failures"]
    prompt = eg.rewrite_prompt(failures)
    for code in failures:
        assert code in prompt
    assert ONLY_REWRITE in prompt
