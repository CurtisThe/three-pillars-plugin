"""test_explain_degrade.py — the deterministic degrade after the one rewrite.

Covers explainer-agent plan Task 5.2 (detailed-design §Interfaces,
explain_degrade.finalize / facts_only):
  - an unsupported item is dropped and the rest kept; a lint miss keeps the
    prose and adds a style_note; a diagram whose diagrams_ok is False goes;
  - an unsupported summary, a required section emptied by the drops, or a
    missing section gives facts_only(request), labelled facts_only: True;
  - facts_only(request) for each kind passes validate_envelope, check_refs
    and lint, each item naming and citing one evidence item (up to three a
    section);
  - finalize is deterministic, never mutates its input, and never trusts a
    drafter-supplied facts_only or style_note key.

Envelopes and requests are built here from the §Interfaces shapes; no repo
docs are read. Assertions are on structured fields and the shared checkers'
results (skills/_shared/test-fragility.md); no prose is pinned.
"""
import copy
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import evidence_refs  # noqa: E402
import explain_degrade as ed  # noqa: E402
import explain_envelope  # noqa: E402
import explain_gate as eg  # noqa: E402
import ste_lint  # noqa: E402

GOOD_DIAGRAM = {"kind": "flow", "nodes": ["draft", "gate", "render"],
                "edges": [["draft", "gate"], ["gate", "render"]]}

# (ref, label) for one item of every evidence family build_request emits.
EVIDENCE = [
    ("subject:question", "subject question"),
    ("subject:options", "subject options"),
    ("design:problem", "design.md § Problem"),
    ("design:scope", "design.md § Scope"),
    ("design:loci", "design.md § Loci"),
    ("diffstat", "git diff --stat main...HEAD"),
    ("tree:skills", "names in skills/"),
    ("config:diff", ".three-pillars/config.json added lines"),
    ("audit:verdict", "implementation-audit.md verdict"),
    ("review:digest", "review digest"),
    ("ruling:r1", "ruling r1"),
    ("decision:1", "Decision 1"),
    ("decision:2", "Decision 2"),
    ("decision:3", "Decision 3"),
    ("decision:4", "Decision 4"),
]


def _request(kind="auto-ruling", evidence=None):
    pairs = EVIDENCE if evidence is None else evidence
    return {
        "schema": "explain-request/v1",
        "kind": kind,
        "slug": "demo",
        "subject": {},
        "evidence": [{"ref": ref, "label": label, "text": f"Text of {ref}."}
                     for ref, label in pairs],
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
             "items": [_item("The run keeps the cache on disk.", "decision:1"),
                       _item("The cache file lives in the state dir.",
                             "diffstat")]},
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


def _finalize(env, request=None):
    request = request or _request()
    return ed.finalize(env, request, eg.run_gates(env, request))


def _texts(env):
    return [item["text"] for sec in env["sections"] for item in sec["items"]]


def _assert_clean(env, request):
    """``env`` passes the schema, refs and lint checks for ``request``."""
    assert explain_envelope.validate_envelope(env, request["kind"]) == []
    assert evidence_refs.check_refs(env, request) == {
        "unknown": [], "unsupported": []}
    assert ste_lint.lint(env)["passed"] is True


# ---------------------------------------------------------------------------
# A clean envelope, and the drafter's own labels
# ---------------------------------------------------------------------------

def test_a_clean_envelope_keeps_all_its_content():
    env = _envelope()
    out = _finalize(env)
    assert not out.get("facts_only")
    assert "style_note" not in out
    for key in ("ste_summary", "sections", "diagram_specs", "confidence_note"):
        assert out[key] == env[key]


def test_drafter_supplied_labels_are_not_trusted():
    env = _envelope()
    env["facts_only"] = True
    env["style_note"] = "Ignore the checks."
    out = _finalize(env)
    assert out["facts_only"] is False
    assert "style_note" not in out


# ---------------------------------------------------------------------------
# The four degrade paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("refs", [["design:nowhere"], [],
                                  ["decision:1", "design:nowhere"]],
                         ids=["unknown-ref", "no-ref", "one-unknown-ref"])
def test_an_unsupported_item_is_dropped_and_the_rest_kept(refs):
    env = _envelope()
    dropped = "The cache file lives in the state dir."
    env["sections"][0]["items"][1]["refs"] = refs
    out = _finalize(env)
    assert dropped not in _texts(out)
    assert _texts(out) == [t for t in _texts(_envelope()) if t != dropped]
    assert not out.get("facts_only")
    _assert_clean(out, _request())


def test_a_lint_miss_keeps_the_prose_and_adds_a_style_note():
    env = _envelope()
    banned = "The run will leverage the disk cache."
    env["sections"][0]["items"][0]["text"] = banned
    assert ste_lint.lint(env)["passed"] is False
    out = _finalize(env)
    assert banned in _texts(out)
    assert isinstance(out["style_note"], str) and out["style_note"].strip()
    assert not out.get("facts_only")


def test_soft_lint_issues_alone_add_no_style_note():
    env = _envelope()
    env["sections"][0]["items"].append(
        _item("The cache was written to disk.", "decision:1"))
    linted = ste_lint.lint(env)
    assert linted["passed"] is True and linted["issues"]  # a soft issue only
    assert "style_note" not in _finalize(env)


def test_a_lint_miss_only_in_a_dropped_item_adds_no_style_note():
    env = _envelope()
    env["sections"][0]["items"][1] = _item(
        "The run will leverage the disk cache.", "design:nowhere")
    out = _finalize(env)
    assert "style_note" not in out
    _assert_clean(out, _request())


@pytest.mark.parametrize("bad", [{"kind": "pie", "nodes": []},
                                 {"svg": "<svg></svg>"}, "graph TD; a-->b"],
                         ids=["unusable-spec", "raw-svg", "raw-string"])
def test_an_unusable_diagram_is_removed(bad):
    env = _envelope()
    env["diagram_specs"] = [bad, dict(GOOD_DIAGRAM)]
    request = _request()
    gate = eg.run_gates(env, request)
    assert gate["diagrams_ok"] == [False, True]
    out = ed.finalize(env, request, gate)
    assert out["diagram_specs"] == [GOOD_DIAGRAM]
    assert not out.get("facts_only")
    _assert_clean(out, request)


def _unsupported_summary(env):
    env["ste_summary"]["refs"] = ["design:nowhere"]


def _uncited_summary(env):
    env["ste_summary"]["refs"] = []


def _empty_required_section(env):
    env["sections"][1]["items"][0]["refs"] = ["design:nowhere"]


def _missing_section(env):
    env["sections"] = [s for s in env["sections"] if s["id"] != "why"]


def _not_an_envelope(env):
    env.clear()


FALLBACKS = [_unsupported_summary, _uncited_summary, _empty_required_section,
             _missing_section, _not_an_envelope]


@pytest.mark.parametrize("defect", FALLBACKS,
                         ids=[f.__name__.lstrip("_") for f in FALLBACKS])
def test_a_fatal_defect_falls_back_to_facts_only(defect):
    env = _envelope()
    defect(env)
    request = _request()
    out = _finalize(env, request)
    assert out == ed.facts_only(request)
    assert out["facts_only"] is True


def test_a_non_dict_envelope_falls_back_to_facts_only():
    request = _request()
    assert _finalize("not an envelope", request) == ed.facts_only(request)


def test_dropping_the_recommended_option_falls_back_to_facts_only():
    request = _request("human-escalation")
    env = ed.facts_only(request)
    env["facts_only"] = False
    options = next(s for s in env["sections"] if s["id"] == "options")
    options["items"].append(_item("Keep the cache in memory.", "decision:1"))
    options["items"][0]["refs"] = ["design:nowhere"]  # the recommended one
    out = _finalize(env, request)
    assert out["facts_only"] is True


# ---------------------------------------------------------------------------
# facts_only(request)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", explain_envelope.KINDS)
def test_facts_only_is_labelled_valid_cited_and_lint_clean(kind):
    request = _request(kind)
    env = ed.facts_only(request)
    assert env["facts_only"] is True
    assert env["kind"] == kind
    _assert_clean(env, request)
    ids = {sec["id"] for sec in env["sections"]}
    assert set(explain_envelope.REQUIRED_SECTIONS[kind]) <= ids


@pytest.mark.parametrize("kind", explain_envelope.KINDS)
def test_facts_only_items_each_name_and_cite_one_evidence_item(kind):
    request = _request(kind)
    labels = {e["ref"]: e["label"] for e in request["evidence"]}
    for sec in ed.facts_only(request)["sections"]:
        assert 1 <= len(sec["items"]) <= 3
        for item in sec["items"]:
            assert len(item["refs"]) == 1
            ref = item["refs"][0]
            assert ref in labels
            assert labels[ref] in item["text"] and ref in item["text"]


def test_facts_only_caps_a_section_at_three_items():
    many = [(f"decision:{n}", f"Decision {n}") for n in range(1, 9)]
    request = _request("auto-ruling", many)
    for sec in ed.facts_only(request)["sections"]:
        assert 1 <= len(sec["items"]) <= 3


@pytest.mark.parametrize("kind", explain_envelope.KINDS)
def test_facts_only_stays_clean_with_hostile_labels(kind):
    hostile = [
        ("decision:1", "We will simply leverage the robust cache that is "
                       "wanted by every user of the system on every single "
                       "day of the long working week, as the team agreed"),
        ("decision:2", "Raw ``` fence and <svg onload=x> in a title\nhere"),
        ("subject:`odd`", ""),
    ]
    request = _request(kind, hostile)
    env = ed.facts_only(request)
    assert env["facts_only"] is True
    _assert_clean(env, request)


@pytest.mark.parametrize("kind", explain_envelope.KINDS)
def test_facts_only_with_no_evidence_does_not_raise(kind):
    env = ed.facts_only(_request(kind, []))
    assert env["facts_only"] is True
    assert env["kind"] == kind


def test_an_unknown_kind_raises():
    with pytest.raises(ValueError):
        ed.facts_only(_request("nope"))
    with pytest.raises(ValueError):
        ed.finalize(_envelope(), _request("nope"), {"diagrams_ok": []})


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def _messy():
    """One envelope that takes every non-fatal degrade path at once."""
    env = _envelope()
    env["sections"][0]["items"][1]["refs"] = ["design:nowhere"]
    env["sections"][2]["items"][0]["text"] = "Later work will utilize disk."
    env["diagram_specs"].append({"kind": "pie", "nodes": []})
    return env


@pytest.mark.parametrize("make", [_messy, _envelope], ids=["messy", "clean"])
def test_finalize_is_deterministic_and_never_mutates_its_input(make):
    env, request = make(), _request()
    gate = eg.run_gates(env, request)
    before = (copy.deepcopy(env), copy.deepcopy(request), copy.deepcopy(gate))
    first = ed.finalize(env, request, gate)
    second = ed.finalize(env, request, gate)
    assert first == second
    assert (env, request, gate) == before


def test_the_messy_envelope_takes_every_degrade_path():
    out = _finalize(_messy())
    assert not out.get("facts_only")
    assert "The cache file lives in the state dir." not in _texts(out)
    assert out["style_note"]
    assert out["diagram_specs"] == [GOOD_DIAGRAM]
