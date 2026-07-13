"""test_iteration_lane.py — the iteration-vs-gate lane seam (design: fast-lane-worker-wiring).

Task 1.1: the dual capability probe (phase/fast + task/unit lanes), the lane command
shapes, the portability fallback to the discovered test command, the None-discovery
case, and the CLI.

The lane probes are FILE-based against the *target* repo root (an explicit repo_root
needs no git), so these build plain temp dirs — hermetic, no mocks. `find_project_root`
(the cwd-git-toplevel default, exercised via the CLI-from-cwd guard in the guardrail
test) is deliberately NOT anchored on `__file__`, so the plugin's own ci-local.sh can
never be probed for a consumer repo.
"""
from __future__ import annotations

import iteration_lane
from iteration_lane import (
    LaneResult,
    ci_local_path,
    discover_test_command,
    fast_lane_available,
    gate_command,
    iteration_command,
    main,
    unit_lane_available,
)

# --- hermetic target-repo builders (file-based capabilities, no git needed) ---

_CI_LOCAL_FAST = (
    '#!/usr/bin/env bash\n'
    'set -euo pipefail\n'
    'if [ "${1:-}" = "--fast" ]; then\n'
    '  echo fast\n'
    '  exit 0\n'
    'fi\n'
    'python3 skills/_shared/ci_local_stamp.py --write\n'
    'echo full\n'
)


def _make_fast_repo(root):
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "ci-local.sh").write_text(_CI_LOCAL_FAST)
    return root


def _make_unit_repo(root):
    (root / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    unit: pure-logic test — the <10s inner loop.\n"
    )
    shared = root / "skills" / "_shared"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "conftest.py").write_text(
        "_UNIT_MODULES = frozenset({'test_x'})\n"
        "def pytest_collection_modifyitems(config, items):\n    pass\n"
    )
    return root


def _make_makefile_repo(root):
    (root / "Makefile").write_text("test:\n\tpython -m pytest\n")
    return root


def _make_pyproject_repo(root):
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n"
    )
    return root


def _make_npm_repo(root):
    (root / "package.json").write_text('{"scripts": {"test": "jest"}}\n')
    return root


# --- (a) fast_lane_available -------------------------------------------------

def test_fast_lane_available_true_with_guard(tmp_path):
    _make_fast_repo(tmp_path)
    assert fast_lane_available(tmp_path) is True


def test_fast_lane_available_false_without_script(tmp_path):
    assert fast_lane_available(tmp_path) is False


def test_fast_lane_available_false_without_guard(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ci-local.sh").write_text("#!/usr/bin/env bash\necho no-fast-guard\n")
    assert fast_lane_available(tmp_path) is False


# --- (b) unit_lane_available -------------------------------------------------

def test_unit_lane_available_true_with_infra(tmp_path):
    _make_unit_repo(tmp_path)
    assert unit_lane_available(tmp_path) is True


def test_unit_lane_available_false_without_marker(tmp_path):
    # conftest present but pytest.ini registers no `unit:` marker
    shared = tmp_path / "skills" / "_shared"
    shared.mkdir(parents=True)
    (shared / "conftest.py").write_text("_UNIT_MODULES = frozenset()\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    assert unit_lane_available(tmp_path) is False


def test_unit_lane_available_false_without_conftest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    unit: x\n")
    assert unit_lane_available(tmp_path) is False


# --- (c) iteration_command task granularity (unit lane + degrade) ------------

def test_iteration_task_uses_unit_lane_when_present(tmp_path):
    _make_unit_repo(tmp_path)
    r = iteration_command(tmp_path, granularity="task")
    assert r.command == "python -m pytest -m unit -n0"
    assert r.writes_stamp is False


def test_iteration_task_degrades_to_discovered_when_unit_absent(tmp_path):
    _make_makefile_repo(tmp_path)  # unit infra absent, Makefile present
    r = iteration_command(tmp_path, granularity="task")
    assert r.command == discover_test_command(tmp_path) == "make test"
    assert r.writes_stamp is False


# --- (d) iteration_command phase granularity (fast lane + degrade) -----------

def test_iteration_phase_uses_fast_lane_when_present(tmp_path):
    _make_fast_repo(tmp_path)
    r = iteration_command(tmp_path, granularity="phase")
    assert r.command.endswith("scripts/ci-local.sh --fast")
    assert r.writes_stamp is False


def test_iteration_phase_degrades_to_discovered_when_fast_absent(tmp_path):
    _make_npm_repo(tmp_path)  # no ci-local.sh, package.json test script present
    r = iteration_command(tmp_path, granularity="phase")
    assert r.command == "npm test"
    assert r.writes_stamp is False


# --- (e) gate_command (full ci-local, no --fast; degrade) --------------------

def test_gate_command_is_full_ci_local_when_present(tmp_path):
    _make_fast_repo(tmp_path)
    r = gate_command(tmp_path)
    assert r.command.endswith("scripts/ci-local.sh")
    assert not r.command.endswith("--fast")
    assert r.writes_stamp is True


def test_gate_command_degrades_to_discovered_without_stamp(tmp_path):
    _make_pyproject_repo(tmp_path)
    r = gate_command(tmp_path)
    assert r.command == "python -m pytest"
    assert r.writes_stamp is False  # a discovered fallback is NOT the stamp source


# --- (f) discover_test_command ordering + None ------------------------------

def test_discover_makefile(tmp_path):
    _make_makefile_repo(tmp_path)
    assert discover_test_command(tmp_path) == "make test"


def test_discover_pyproject_pytest(tmp_path):
    _make_pyproject_repo(tmp_path)
    assert discover_test_command(tmp_path) == "python -m pytest"


def test_discover_pyproject_without_pytest_is_none(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 88\n")
    assert discover_test_command(tmp_path) is None


def test_discover_npm(tmp_path):
    _make_npm_repo(tmp_path)
    assert discover_test_command(tmp_path) == "npm test"


def test_discover_npm_without_test_script_is_none(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}\n')
    assert discover_test_command(tmp_path) is None


def test_discover_none_when_nothing(tmp_path):
    assert discover_test_command(tmp_path) is None


# --- (g) lane unavailable AND discovery None -> command is None --------------

def test_iteration_none_when_no_lane_and_no_discovery(tmp_path):
    for gran in ("task", "phase"):
        r = iteration_command(tmp_path, granularity=gran)
        assert isinstance(r, LaneResult)
        assert r.command is None
        assert r.lane == "none"
        assert r.writes_stamp is False


def test_gate_none_when_no_lane_and_no_discovery(tmp_path):
    r = gate_command(tmp_path)
    assert r.command is None
    assert r.lane == "none"


# --- (h) CLI ------------------------------------------------------------------

def test_cli_prints_resolved_command_and_exits_zero(tmp_path, capsys):
    _make_fast_repo(tmp_path)
    rc = main(["--lane", "iteration", "--granularity", "phase", "--repo-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip().endswith("scripts/ci-local.sh --fast")


def test_cli_gate_lane_prints_full_ci_local(tmp_path, capsys):
    _make_fast_repo(tmp_path)
    rc = main(["--lane", "gate", "--repo-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip().endswith("scripts/ci-local.sh")


def test_cli_unresolvable_prints_nothing_to_stdout_and_exits_nonzero(tmp_path, capsys):
    # empty repo: no fast lane, no discoverable command -> command None
    rc = main(["--lane", "iteration", "--granularity", "phase", "--repo-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == ""  # NEVER an empty stdout line a tee-pipe swallows as green
    assert captured.err.strip()  # a diagnostic goes to stderr


def test_ci_local_path_shape(tmp_path):
    assert ci_local_path(tmp_path) == tmp_path / "scripts" / "ci-local.sh"


def test_module_importable_defaults(tmp_path):
    # iteration_command with no repo_root must not raise (cwd/find_project_root default).
    r = iteration_command(granularity="phase")
    assert isinstance(r, iteration_lane.LaneResult)


def test_iteration_command_rejects_unknown_granularity():
    """A bad granularity fails LOUD (ValueError) rather than silently coercing to the
    phase/fast lane — the seam encodes the lane decision in one place (code-review #4)."""
    import pytest
    from iteration_lane import iteration_command
    with pytest.raises(ValueError):
        iteration_command(granularity="bogus")
