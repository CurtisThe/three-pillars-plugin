"""The orchestrator's candidate test run stops clearly when no test command resolves.

consumer-repo-parity Task 6.3 (M2, part C §M2): the regression check that re-runs the
project suite on the candidate branch (`### Step 1 — Regression check`, the plan's
"Tier 3 :584-589" anchor) captures the command `iteration_lane.py` resolves and, when the
resolver exits 1, stops with its message pointing at `/tp-test-setup`. The old claim that
the seam discovers the command from `CLAUDE.md` is gone (the resolver never reads it).

Path, flag and token pins only, never sentences.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
_TP_ROOT = Path(__file__).resolve().parents[3]
_START = "### Step 1 — Regression check"
_END = "### Step 2 —"


def _region() -> str:
    text = skill_text.read_skill_text("tp-run-full-design")
    start = text.index(_START)
    return text[start:text.index(_END, start)]


def _fenced_lines(region: str) -> "list[str]":
    return [
        line.strip()
        for fence in re.findall(r"```.*?\n(.*?)```", region, re.DOTALL)
        for line in fence.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_regression_check_resolves_through_iteration_lane() -> None:
    region = _region()
    assert "skills/_shared/iteration_lane.py" in region
    assert "/tp-test-setup" in region


def test_regression_check_executes_the_lane_through_the_shell() -> None:
    """F3: the fenced command hands execution to `iteration_lane.py --exec` (shell
    semantics, one owner) instead of word-splitting a captured `$CMD`, and names the
    no-command exit status (78) so an empty resolution is never read as green."""
    block = _region()
    commands = [c for c in _fenced_lines(block) if "iteration_lane.py" in c]
    assert commands and all("--exec" in c for c in commands)
    assert not any(re.search(r"&&\s*\$CMD\b", c) for c in _fenced_lines(block))
    assert "78" in block


def test_regression_check_runs_a_recorded_compound_command(tmp_path: Path) -> None:
    """The exact fenced invocation, run by bash in a consumer repo whose recorded
    `test.command` is a compound shell string, runs it (no `cd: too many arguments`)."""
    cfg = tmp_path / ".three-pillars"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        json.dumps({"schema_version": 1, "test": {"command": "cd . && echo TESTS-RAN"}}),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["TP_ROOT"] = str(_TP_ROOT)
    subprocess.run(["git", "init", "-q", str(tmp_path)], env=env, check=True)
    (command,) = [c for c in _fenced_lines(_region()) if "iteration_lane.py" in c]
    proc = subprocess.run(
        ["bash", "-c", command], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "TESTS-RAN" in proc.stdout
    assert "too many arguments" not in proc.stderr


def test_regression_check_drops_the_claude_md_discovery_claim() -> None:
    assert "CLAUDE.md" not in _region()


def test_regression_check_names_the_declared_gate_command() -> None:
    """F5 (post-H1): the one mandatory full run is the repo's declared gate command run
    by `ci_gate_run.py` (only when `ci.gate_command` is declared), feeding the /tp-merge
    `ci_local_stamp` predicate at land — not the dev repo's `scripts/ci-local.sh`."""
    region = _region()
    for token in ("ci_gate_run.py", "ci.gate_command", "/tp-merge", "ci_local_stamp"):
        assert token in region, token
    assert "scripts/ci-local.sh" not in region
