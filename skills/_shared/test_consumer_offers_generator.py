"""Tests for the generator-item keys added to `merge_from_main.generators[]`.

design: basesync-generator-catalog (Task 2.4). A generator item declares how
long its `write` argv may run (`timeout`), which files' conflicts it can
resolve (`inputs`) and the directory it runs in (`cwd`). The schema is the
entry point: it must accept a well-formed item and reject a malformed one.
Run with: python3 -m pytest skills/_shared/test_consumer_offers_generator.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
Draft202012Validator = jsonschema.Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "repo-config.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def _gen(**extra) -> dict:
    item = {"path": "web/generated/routes.ts", "write": ["node", "gen.js"]}
    item.update(extra)
    return {"schema_version": 1, "merge_from_main": {"generators": [item]}}


def _errors(cfg) -> list:
    return list(VALIDATOR.iter_errors(cfg))


def test_generator_item_accepts_timeout_inputs_cwd():
    assert _errors(_gen(timeout=300, inputs=["package.json"], cwd="web")) == []


def test_generator_item_timeout_must_be_positive_integer():
    for bad in (0, -1, "300", 1.5, None, True):
        assert _errors(_gen(timeout=bad)), f"timeout={bad!r} accepted"


def test_generator_item_inputs_must_be_non_empty_strings():
    assert _errors(_gen(inputs=["package.json", "src/router.ts"])) == []
    for bad in ([""], ["ok", ""], "", 300, None, ["x", 5]):
        assert _errors(_gen(inputs=bad)), f"inputs={bad!r} accepted"


def test_generator_item_cwd_must_be_non_empty_string():
    for bad in ("", 5, None, ["web"]):
        assert _errors(_gen(cwd=bad)), f"cwd={bad!r} accepted"


def test_generator_item_still_rejects_unknown_keys():
    assert _errors(_gen(output="web/generated/routes.ts"))


def _catalog_module():
    """`generator_catalog` from the tp-merge-from-main scripts dir, or a clean skip when the
    shipped tree has no such module (never a dev-only import of this test)."""
    import importlib
    import sys

    scripts = Path(__file__).resolve().parents[1] / "tp-merge-from-main" / "scripts"
    if not scripts.is_dir():
        pytest.skip(f"no generator_catalog in the shipped tree: {scripts} absent")
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("generator_catalog")
    except ImportError:
        pytest.skip("generator_catalog module absent from the shipped tree")


def test_schema_accepts_config_entry_and_offer_record():
    """Everything `generator_catalog` writes into `.three-pillars/config.json` must validate:
    the `config_entry` item under `merge_from_main.generators` and the `offer_record` block
    under `merge_from_main.generator_offer` (design: basesync-generator-catalog Task 3.2)."""
    cat = _catalog_module()
    tracked = ["package-lock.json", "package.json", "web/package-lock.json", "web/package.json"]
    matches = cat.detect(tracked, {})
    assert len(matches) == 2, matches
    for m in matches:
        cfg = {
            "schema_version": 1,
            "merge_from_main": {
                "generators": [cat.config_entry(m)],
                "generator_offer": cat.offer_record({}, [m.path], accepted=False,
                                                   now="2026-10-17T00:00:00Z"),
            },
        }
        assert [e.message for e in _errors(cfg)] == [], cfg


# --- the shipped offer prose (Task 6.1) ---------------------------------------

OFFERS = Path(__file__).resolve().parent / "consumer-offers.md"


def test_offer_f_heading_present():
    """`consumer-offers.md` carries the offer (f) section beside (a)-(e)."""
    headings = [ln for ln in OFFERS.read_text(encoding="utf-8").splitlines()
                if ln.startswith("## ")]
    assert any(h.startswith("## Offer (f)") for h in headings), (
        f"consumer-offers.md has no `## Offer (f)` heading; headings are {headings}")


def test_consumer_offers_refs_clean(tmp_path):
    """Every path and `python3` invocation the offers doc names still resolves
    (`skill_refs` is dev-only, so it is imported here, never at module top)."""
    skill_refs = pytest.importorskip("skill_refs")
    root = Path(__file__).resolve().parents[2]
    assert skill_refs.check(root, [OFFERS], cache_dir=tmp_path).issues == []


def test_merge_skill_refs_clean(tmp_path):
    """The `tp-merge-from-main` skill text stays reference-clean: every path and
    `python3` invocation it names resolves, so a new generator call parses."""
    skill_refs = pytest.importorskip("skill_refs")
    skill_text = pytest.importorskip("skill_text")
    root = Path(__file__).resolve().parents[2]
    files = skill_text.skill_paths("tp-merge-from-main")
    assert skill_refs.check(root, files, cache_dir=tmp_path).issues == []
