"""test_fragility_name_kill.py — the `name-kill` gating rule, both file kinds.

design: no-kill-by-name (Task 1.5). Source strings only: nothing is executed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fragility_lint import lint_source  # noqa: E402
from fragility_registry import RULES  # noqa: E402

TEST_PATH = "skills/_shared/test_sample.py"
PROD_PATH = "skills/_shared/sample.py"
KILL = 'import subprocess\n\nsubprocess.run(["pkill", "-x", "claude"])\n'
SEARCH = ('import os, subprocess\n\n\ndef f():\n    out = subprocess.check_output(["pgrep", "x"])\n'
          '    for pid in out.split():\n        os.kill(int(pid), 9)\n')


def _name_kill(path, src):
    return [h for h in lint_source(path, src) if h.rule_id == "name-kill"]


def test_registry_row_is_gating_on_both_sides():
    (rule,) = [r for r in RULES if r.id == "name-kill"]
    assert (rule.side, rule.family, rule.gating) == ("any", "gating", True)


@pytest.mark.parametrize("path", [TEST_PATH, PROD_PATH])
@pytest.mark.parametrize("src,line", [(KILL, 3), (SEARCH, 7)])
def test_flags_on_test_and_production_files(path, src, line):
    hits = _name_kill(path, src)
    assert [(h.line, h.gating, h.waived) for h in hits] == [(line, True, False)]


def test_waiver_marks_the_hit_waived():
    src = KILL.replace("])\n", "])  # tp-allow-fragile: fixture for the guard\n")
    (hit,) = _name_kill(TEST_PATH, src)
    assert hit.waived


@pytest.mark.parametrize("src", [
    'CASES = [("pkill -x claude", "deny")]\n',
    'import subprocess\np = subprocess.Popen(["sleep", "9"])\np.kill()\n',
])
def test_data_and_own_pids_pass(src):
    assert _name_kill(PROD_PATH, src) == []
