"""The fragility lint's own modules must pass the fragility lint."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fragility_lint  # noqa: E402


def test_fragility_modules_are_lint_clean():
    modules = sorted(HERE.glob("fragility_*.py"))
    assert modules, "glob skills/_shared/fragility_*.py matched nothing"
    result = fragility_lint.scan([str(p) for p in modules])
    bad = [h for h in result.hits if h.gating and not h.waived]
    assert not bad, f"unwaived gating hits: {bad}"
