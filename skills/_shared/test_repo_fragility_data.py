"""test_repo_fragility_data.py — this repo's fragility rules file and triage ledger are valid data.

design: fragile-test-prevention (detailed-design-devrepo §This repo's per-repo rules, §Phase 15)

The rules file loads through `fragility_repo_rules.load` with no error and its
`forbidden-read-assert` globs cover the prose-pin targets; the ledger parses, its keys are
unique and every verdict and action is one of the ledger module's enums. Gating flags and
verdict counts are not asserted: later phases change both. The ledger module is dev-only, so
it is `importorskip`ped: in a consumer repo (no ledger module, no ledger) this module skips.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fragility_repo_rules import load as load_rules

fragility_ledger = pytest.importorskip("fragility_ledger")

ROOT = Path(__file__).resolve().parents[2]
PROSE_PIN_GLOBS = {"skills/*/SKILL.md", "skills/*/*.md", "agents/*.md", "CLAUDE.md"}


def test_rules_file_loads_without_errors():
    rules = load_rules(ROOT)
    assert rules.errors == []
    assert rules.rules


def test_rules_cover_the_prose_pin_globs():
    globs = {rule.params["path_glob"] for rule in load_rules(ROOT).rules
             if rule.kind == "forbidden-read-assert"}
    assert PROSE_PIN_GLOBS <= globs


def test_ledger_parses_with_unique_keys():
    assert (ROOT / fragility_ledger.LEDGER_PATH).is_file()
    keys = [row["key"] for row in fragility_ledger.load(ROOT)["rows"]]
    assert len(keys) == len(set(keys))


def test_ledger_verdicts_and_actions_are_in_the_enums():
    rows = fragility_ledger.load(ROOT)["rows"]
    assert {row["verdict"] for row in rows} <= set(fragility_ledger.VERDICTS)
    assert {row["action"] for row in rows} <= set(fragility_ledger.ACTIONS)
