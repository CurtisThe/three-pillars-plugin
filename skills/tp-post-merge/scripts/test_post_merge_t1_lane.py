"""Step 6.5 T1 of skills/tp-post-merge/SKILL.md runs the gate lane in the seat.

consumer-repo-parity Task 6.3 (L1, part C §M2): T1 no longer runs the framework's own
`skills/_shared/` suite behind a `framework-check.sh` guard. It resolves the repo's gate
lane through `iteration_lane.py --lane gate` (the framework repo still resolves to its
ci-local command; a consumer repo to its recorded or discovered test command) and records
`skipped (no test command recorded)` only when nothing resolves.

Split from test_post_merge_tripwires_md.py (past the soft cap); the T1 checks that lived
there moved here. Path, flag and status-token pins only, never sentences.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
_TP_ROOT = Path(__file__).resolve().parents[3]


def _t1_block() -> str:
    """The T1 sub-block of step 6.5 (up to T2)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.search(r"\*\*T1\s*—.*?(?=\*\*T2\s*—)", text, re.DOTALL)
    assert match, "Step 6.5 T1 sub-block not found in SKILL.md"
    return match.group(0)


def _fenced_lines(block: str) -> "list[str]":
    return [
        line.strip()
        for fence in re.findall(r"```.*?\n(.*?)```", block, re.DOTALL)
        for line in fence.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_t1_runs_the_gate_lane_resolver() -> None:
    block = _t1_block()
    assert "skills/_shared/iteration_lane.py" in block
    assert "--lane gate" in block
    commands = _fenced_lines(block)
    assert any("iteration_lane.py" in c and "--lane gate" in c for c in commands), (
        "T1's fenced command must resolve through iteration_lane.py --lane gate"
    )


def test_t1_records_the_no_command_skip_token() -> None:
    assert "skipped (no test command recorded)" in _t1_block()


def test_t1_no_longer_runs_the_framework_suite() -> None:
    block = _t1_block()
    assert '"$TP_ROOT"/skills/_shared/ -q' not in block
    assert "skipped (consumer install)" not in block


def test_t1_executes_the_lane_through_the_shell() -> None:
    """F3: the fenced command hands execution to `iteration_lane.py --exec` (shell
    semantics, one owner) instead of word-splitting a captured `$CMD`, and names the
    no-command exit status (78) so an empty resolution is never read as green."""
    block = _t1_block()
    commands = [c for c in _fenced_lines(block) if "iteration_lane.py" in c]
    assert commands and all("--exec" in c for c in commands)
    assert not any(re.search(r"&&\s*\$CMD\b", c) for c in _fenced_lines(block))
    assert "78" in block


def test_t1_runs_a_recorded_compound_command(tmp_path: Path) -> None:
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
    (command,) = [c for c in _fenced_lines(_t1_block()) if "iteration_lane.py" in c]
    proc = subprocess.run(
        ["bash", "-c", command], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "TESTS-RAN" in proc.stdout
    assert "too many arguments" not in proc.stderr
