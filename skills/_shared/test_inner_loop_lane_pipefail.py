"""The tee'd inner-loop lane fences keep the lane's exit status (impl-audit A2-F3).

`tp-phase-implement` step 6 and `tp-task-cycle` step 8 run
`iteration_lane.py ... --exec 2>&1 | tee <log>`. Without `pipefail` the pipeline's
status is tee's 0, masking both a failing test run and the nothing-resolved exit
(78). Both fences must set `pipefail`, and the prose must identify the
nothing-resolved case by the `iteration_lane: no test command resolved`
diagnostic, not by the exit status alone (a resolved command may itself exit 78).

Mirrors skills/tp-post-merge/scripts/test_post_merge_t1_lane.py: path, flag and
diagnostic-token pins plus the exact fenced command run by bash in a scratch repo.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

_TP_ROOT = Path(__file__).resolve().parents[2]
_SKILLS = _TP_ROOT / "skills"
_DIAGNOSTIC = "iteration_lane: no test command resolved"

# (SKILL.md, region start marker, region end marker)
_SITES = {
    "phase-implement-step-6": (
        _SKILLS / "tp-phase-implement" / "SKILL.md",
        "6. **After all tasks in the phase complete**",
        "7. **Integration review**",
    ),
    "task-cycle-step-8": (
        _SKILLS / "tp-task-cycle" / "SKILL.md",
        "8. **Run the broader test suite**",
        "### Refactor",
    ),
}


def _region(site: str) -> str:
    path, start, end = _SITES[site]
    text = path.read_text(encoding="utf-8")
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


def _lane_command(site: str) -> str:
    """The one iteration_lane.py command the region runs (fenced or inline code)."""
    region = _region(site)
    snippets = re.findall(r"```.*?\n(.*?)```", region, re.DOTALL)
    snippets += re.findall(r"`([^`\n]*iteration_lane\.py[^`\n]*)`", region)
    lines = [ln.strip() for s in snippets for ln in s.splitlines()
             if "iteration_lane.py" in ln and "| tee" in ln]
    assert len(lines) == 1, f"{site}: expected one tee'd lane command, got {lines}"
    return lines[0]


@pytest.mark.parametrize("site", sorted(_SITES))
def test_tee_fence_sets_pipefail_and_exec(site: str) -> None:
    command = _lane_command(site)
    assert command.startswith("set -o pipefail;"), command
    assert "--exec" in command


@pytest.mark.parametrize("site", sorted(_SITES))
def test_nothing_resolved_is_named_by_the_diagnostic(site: str) -> None:
    assert _DIAGNOSTIC in _region(site)


def _run_fence(site: str, repo: Path, tmp_path: Path) -> "subprocess.CompletedProcess[str]":
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["TP_ROOT"] = str(_TP_ROOT)
    subprocess.run(["git", "init", "-q", str(repo)], env=env, check=True)
    # Keep the tee log inside tmp_path: rewrite only the mktemp template argument.
    command, n = re.subn(r"mktemp [^)\"]+", f"mktemp {tmp_path}/lane.XXXXXX.log",
                         _lane_command(site))
    assert n == 1, command
    return subprocess.run(["bash", "-c", command], cwd=str(repo), env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("site", sorted(_SITES))
def test_fence_surfaces_the_nothing_resolved_status(site: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = _run_fence(site, repo, tmp_path)
    assert proc.returncode == 78, (proc.returncode, proc.stdout, proc.stderr)
    assert _DIAGNOSTIC in proc.stdout  # 2>&1 | tee: the diagnostic reaches the log


@pytest.mark.parametrize("site", sorted(_SITES))
def test_fence_surfaces_a_failing_test_run(site: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".three-pillars").mkdir(parents=True)
    (repo / ".three-pillars" / "config.json").write_text(
        json.dumps({"schema_version": 1, "test": {"command": "echo RAN && exit 3"}}),
        encoding="utf-8",
    )
    proc = _run_fence(site, repo, tmp_path)
    assert "RAN" in proc.stdout
    assert proc.returncode == 3, (proc.returncode, proc.stdout, proc.stderr)
