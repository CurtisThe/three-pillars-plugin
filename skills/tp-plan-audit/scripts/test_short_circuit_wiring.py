#!/usr/bin/env python3
"""Wiring test for the Round-2 short-circuit helper that SKILL.md Step 3.5 names.

The helper callable and CLI the skill documents are checked against the real
module (structured), not against the skill's wording.
"""

import inspect
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = _SCRIPTS.parent / "SKILL.md"


def _helper():
    sys.path.insert(0, str(_SCRIPTS))
    return pytest.importorskip("round2_short_circuit")


def test_documented_callable_exists():
    mod = _helper()
    fn = getattr(mod, "should_short_circuit", None)
    assert callable(fn)
    assert len(inspect.signature(fn).parameters) == 1
    assert fn([])["short_circuit"] is False


def test_documented_cli_runs_on_two_round1_files(tmp_path, capsys):
    mod = _helper()
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("nothing notable here\n", encoding="utf-8")
    b.write_text("also nothing notable\n", encoding="utf-8")
    assert mod.main([str(a), str(b)]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert set(verdict) >= {"short_circuit", "converged_topic", "evidence"}


def test_interactive_mode_always_runs_round_2():
    # Kept on purpose: should_short_circuit takes only the Round-1 outputs (no
    # mode), so the --auto-only gating has no structured owner; a check on the
    # Step 3.5 heading or spans would pin the same wording.
    body = SKILL_MD.read_text(encoding="utf-8")
    # tp-allow-fragile: the interactive-always-runs-Round-2 contract lives only in SKILL.md Step 3.5; round2_short_circuit is mode-agnostic
    assert "interactive mode always runs Round 2" in body


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
