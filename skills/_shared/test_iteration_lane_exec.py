"""test_iteration_lane_exec.py — `iteration_lane.py --exec` owns lane execution.

consumer-repo-parity impl-audit F3: a recorded `test.command` / `ci.gate_command` is an
arbitrary shell string (`ci_gate_run.py` runs it with `shell=True`). The skills used to
run the resolved lane as `CMD=$(...) && $CMD` — bare word-splitting with no shell
parsing, so `cd app && make test`, pipes, quoted `-k` expressions and `VAR=val`
prefixes all broke in the iteration lane while working in the gate lane.

`--exec` resolves the lane and runs it through the shell itself (one execution owner):
  * a compound recorded command runs as the shell would run it;
  * the command's own exit status passes through unchanged;
  * nothing resolved -> exit `EXEC_NO_LANE_EXIT` (78, sysexits EX_CONFIG) with the
    stderr diagnostic and NO command run, so a caller can tell "no command recorded"
    apart from "the tests failed".

Hermetic: plain temp dirs in `tmp_path`, schema-valid config fixtures. Stdlib only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import iteration_lane  # noqa: E402

_SCRIPT = _SHARED_DIR / "iteration_lane.py"


def _write_config(root: Path, config: dict) -> None:
    cfg_dir = root / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _record(root: Path, command: str) -> None:
    _write_config(root, {"schema_version": 1, "test": {"command": command}})


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(root), "--exec", *args],
        cwd=str(root), capture_output=True, text=True, timeout=60,
    )


def test_exec_runs_a_compound_recorded_command_through_the_shell(tmp_path: Path) -> None:
    _record(tmp_path, "cd . && echo TESTS-RAN")
    for lane in (("--lane", "iteration", "--granularity", "phase"),
                 ("--lane", "iteration", "--granularity", "task"),
                 ("--lane", "gate")):
        proc = _run(tmp_path, *lane)
        assert proc.returncode == 0, (lane, proc.stderr)
        assert "TESTS-RAN" in proc.stdout, lane
        assert "too many arguments" not in proc.stderr


def test_exec_parses_quotes_and_env_prefixes(tmp_path: Path) -> None:
    _record(tmp_path, "MARK='a or b' sh -c 'echo \"K=$MARK\"' | tr a-z A-Z")
    proc = _run(tmp_path, "--lane", "iteration")
    assert proc.returncode == 0, proc.stderr
    assert "K=A OR B" in proc.stdout


def test_exec_passes_the_command_exit_status_through(tmp_path: Path) -> None:
    _record(tmp_path, "echo failing && exit 3")
    proc = _run(tmp_path, "--lane", "gate")
    assert proc.returncode == 3
    assert "failing" in proc.stdout


def test_exec_runs_in_the_repo_root(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here\n", encoding="utf-8")
    _record(tmp_path, "cat marker.txt")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(tmp_path), "--exec"],
        cwd=str(_SHARED_DIR), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "here" in proc.stdout


def test_exec_with_nothing_resolved_exits_ex_config_and_runs_nothing(tmp_path: Path) -> None:
    proc = _run(tmp_path, "--lane", "gate")
    assert iteration_lane.EXEC_NO_LANE_EXIT == 78
    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "/tp-test-setup" in proc.stderr


def test_resolve_mode_is_unchanged(tmp_path: Path) -> None:
    """Without --exec the CLI still only prints the command (exit 1 when none)."""
    _record(tmp_path, "cd . && echo TESTS-RAN")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(tmp_path), "--lane", "gate"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "cd . && echo TESTS-RAN"
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(empty)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1 and proc.stdout == ""
