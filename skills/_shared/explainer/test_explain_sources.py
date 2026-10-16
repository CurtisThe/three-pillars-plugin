"""test_explain_sources.py — the file-based evidence readers.

Covers explainer-agent plan Task 4.1 (detailed-design §Interfaces: "Ref ids
are closed and stable: design:problem|scope|dependencies|consumer-repo|forge|
loci, ..., audit:verdict, review:digest, decision:<n>, ruling:<id>,
subject:<field>. Every reader is best-effort: a missing source adds no item
and never raises."):
  - design_items reads the six design.md sections, in the closed order, from
    tp-designs/<slug>/ or from completed-tp-designs/<slug>/;
  - decision_items gives decision:<n> per "### " entry of decisions.md
    (1-based);
  - ruling_items gives ruling:<id> per row of the design-dir rulings.ndjson,
    each row storing its own id;
  - subject_items gives subject:<field> per top-level key;
  - audit_items gives audit:verdict from the first implementation-audit.md
    line holding "verdict" (any case); review_items gives review:digest from a
    review digest file (build_request's review_digest path);
  - with every source absent each reader returns [] and nothing raises.

Every input is built under tmp_path; no repo docs are read
(skills/_shared/test-fragility.md).
"""
import json
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_sources as es  # noqa: E402

SLUG = "demo"
DESIGN_REFS = [
    "design:problem", "design:scope", "design:dependencies",
    "design:consumer-repo", "design:forge", "design:loci",
]
# The closed ref grammar from detailed-design §Interfaces (file-based ids).
CLOSED_REF = re.compile(
    r"^(design:(problem|scope|dependencies|consumer-repo|forge|loci)"
    r"|audit:verdict|review:digest|decision:[1-9][0-9]*"
    r"|ruling:[^\s]+|subject:[^\s]+)$"
)

DESIGN_MD = """\
# demo — a design

## Problem
PROBLEM-BODY the operator rebuilds the story by hand.

## Scope
### In scope
SCOPE-IN the brief.
### Out of scope
SCOPE-OUT the SPA.

## Dependencies
DEPS-BODY forge-interface.

## Entities
ENTITIES-BODY not an evidence section.

## Consumer-repo behaviour
CONSUMER-BODY ships in core.

## Forge behaviour
FORGE-BODY GitHub and Gitea.

## State space
### Loci
LOCI-BODY the ledger.
### Dimensions
DIMENSIONS-BODY not an evidence section.
"""

DECISIONS_MD = """\
# Decisions log — schema v1

### [tp-design] Drafter strength
**Decided**: DECIDED-ONE

### [tp-design] Forge comment verbs
**Decided**: DECIDED-TWO

### [tp-plan] Phase order
**Decided**: DECIDED-THREE
"""


def _design_dir(root, tree="tp-designs"):
    d = root / "three-pillars-docs" / tree / SLUG
    d.mkdir(parents=True)
    return d


def _assert_item_shape(items):
    for item in items:
        assert set(item) == {"ref", "label", "text"}
        assert all(isinstance(item[k], str) for k in item)
        assert item["label"] and item["text"]


@pytest.mark.parametrize("tree", ["tp-designs", "completed-tp-designs"])
def test_design_items_give_the_six_sections_in_order(tmp_path, tree):
    (_design_dir(tmp_path, tree) / "design.md").write_text(DESIGN_MD)
    items = es.design_items(tmp_path, SLUG)
    assert [i["ref"] for i in items] == DESIGN_REFS
    _assert_item_shape(items)
    text = {i["ref"]: i["text"] for i in items}
    assert "PROBLEM-BODY" in text["design:problem"]
    assert "SCOPE-IN" in text["design:scope"]
    assert "SCOPE-OUT" in text["design:scope"]
    assert "DEPS-BODY" in text["design:dependencies"]
    assert "CONSUMER-BODY" in text["design:consumer-repo"]
    assert "FORGE-BODY" in text["design:forge"]
    assert "LOCI-BODY" in text["design:loci"]
    # A section stops at the next heading of its own level or higher.
    assert "ENTITIES-BODY" not in text["design:dependencies"]
    assert "DIMENSIONS-BODY" not in text["design:loci"]


def test_design_items_skip_a_missing_section(tmp_path):
    (_design_dir(tmp_path) / "design.md").write_text(
        "# demo\n\n## Problem\nPROBLEM-BODY\n\n## Forge behaviour\nFORGE-BODY\n"
    )
    refs = [i["ref"] for i in es.design_items(tmp_path, SLUG)]
    assert refs == ["design:problem", "design:forge"]


def test_decision_items_number_each_entry_from_one(tmp_path):
    (_design_dir(tmp_path) / "decisions.md").write_text(DECISIONS_MD)
    items = es.decision_items(tmp_path, SLUG)
    assert [i["ref"] for i in items] == ["decision:1", "decision:2", "decision:3"]
    _assert_item_shape(items)
    assert "DECIDED-ONE" in items[0]["text"]
    assert "DECIDED-TWO" in items[1]["text"]
    assert "DECIDED-THREE" in items[2]["text"]
    assert "DECIDED-TWO" not in items[0]["text"]


def _write_rulings(design_dir, rows):
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    (design_dir / "rulings.ndjson").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("tree", ["tp-designs", "completed-tp-designs"])
def test_ruling_items_use_each_rows_stored_id(tmp_path, tree):
    _write_rulings(_design_dir(tmp_path, tree), [
        {"id": "r1", "decided": "RULING-ONE"},
        {"id": "r2", "decided": "RULING-TWO"},
    ])
    items = es.ruling_items(tmp_path, SLUG)
    assert [i["ref"] for i in items] == ["ruling:r1", "ruling:r2"]
    _assert_item_shape(items)
    assert "RULING-ONE" in items[0]["text"]
    assert "RULING-TWO" in items[1]["text"]


def test_ruling_items_skip_a_malformed_row(tmp_path):
    _write_rulings(_design_dir(tmp_path), [
        {"id": "r1", "decided": "RULING-ONE"},
        "{not json",
        {"decided": "no id"},
        {"id": "r3", "decided": "RULING-THREE"},
    ])
    refs = [i["ref"] for i in es.ruling_items(tmp_path, SLUG)]
    assert refs == ["ruling:r1", "ruling:r3"]


def test_subject_items_give_one_item_per_top_level_key():
    subject = {"question": "Which default?", "options": ["a", "b"], "pr": 7}
    items = es.subject_items(subject)
    assert sorted(i["ref"] for i in items) == sorted(
        f"subject:{k}" for k in subject)
    _assert_item_shape(items)
    text = {i["ref"]: i["text"] for i in items}
    assert "Which default?" in text["subject:question"]
    assert "b" in text["subject:options"]
    assert "7" in text["subject:pr"]


@pytest.mark.parametrize("line", [
    "**Verdict**: pass", "VERDICT: needs-work", "final verdict — pass"])
def test_audit_items_take_the_first_verdict_line(tmp_path, line):
    (_design_dir(tmp_path) / "implementation-audit.md").write_text(
        f"# Implementation audit\n\nScope line.\n{line}\nverdict: later\n")
    items = es.audit_items(tmp_path, SLUG)
    assert [i["ref"] for i in items] == ["audit:verdict"]
    _assert_item_shape(items)
    assert line in items[0]["text"]
    assert "later" not in items[0]["text"]


def test_audit_items_without_a_verdict_line_add_nothing(tmp_path):
    (_design_dir(tmp_path) / "implementation-audit.md").write_text(
        "# Implementation audit\n\nNo outcome yet.\n")
    assert es.audit_items(tmp_path, SLUG) == []


def test_review_items_read_the_digest_file(tmp_path):
    digest = tmp_path / "digest.md"
    digest.write_text("DIGEST-BODY two stable rounds\n")
    items = es.review_items(digest)
    assert [i["ref"] for i in items] == ["review:digest"]
    _assert_item_shape(items)
    assert "DIGEST-BODY" in items[0]["text"]
    assert es.review_items(str(digest))[0]["ref"] == "review:digest"


def test_every_absent_source_gives_nothing_and_never_raises(tmp_path):
    assert es.design_items(tmp_path, SLUG) == []
    assert es.decision_items(tmp_path, SLUG) == []
    assert es.ruling_items(tmp_path, SLUG) == []
    assert es.audit_items(tmp_path, SLUG) == []
    assert es.review_items(tmp_path / "no-digest.md") == []
    assert es.review_items(None) == []
    assert es.subject_items(None) == []
    assert es.subject_items({}) == []
    # The design dir exists but holds none of the files.
    _design_dir(tmp_path)
    assert es.design_items(tmp_path, SLUG) == []
    assert es.decision_items(tmp_path, SLUG) == []
    assert es.ruling_items(tmp_path, SLUG) == []
    assert es.audit_items(tmp_path, SLUG) == []


def test_an_unreadable_source_gives_nothing(tmp_path):
    d = _design_dir(tmp_path)
    for name in ("design.md", "decisions.md", "rulings.ndjson",
                 "implementation-audit.md"):
        (d / name).mkdir()  # a directory where a file is expected
    (d / "bad.md").write_bytes(b"\xff\xfe\xfa not utf-8")
    assert es.design_items(tmp_path, SLUG) == []
    assert es.decision_items(tmp_path, SLUG) == []
    assert es.ruling_items(tmp_path, SLUG) == []
    assert es.audit_items(tmp_path, SLUG) == []
    assert es.review_items(d / "bad.md") == []
    assert es.review_items(d) == []


def test_every_ref_is_in_the_closed_grammar(tmp_path):
    d = _design_dir(tmp_path)
    (d / "design.md").write_text(DESIGN_MD)
    (d / "decisions.md").write_text(DECISIONS_MD)
    _write_rulings(d, [{"id": "r1", "decided": "x"}])
    (d / "implementation-audit.md").write_text("Verdict: pass\n")
    digest = tmp_path / "digest.md"
    digest.write_text("digest\n")
    items = (es.design_items(tmp_path, SLUG) + es.decision_items(tmp_path, SLUG)
             + es.ruling_items(tmp_path, SLUG) + es.audit_items(tmp_path, SLUG)
             + es.review_items(digest) + es.subject_items({"pr": 1}))
    refs = [i["ref"] for i in items]
    assert len(refs) == 6 + 3 + 1 + 1 + 1 + 1
    assert len(set(refs)) == len(refs)
    assert all(CLOSED_REF.match(r) for r in refs), refs
