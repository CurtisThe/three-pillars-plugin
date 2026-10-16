"""test_iteration_lane_test_command.py — Task 6.1: discover_test_command reads config first.

`iteration_lane.discover_test_command(repo_root)` resolves, in order (consumer-repo-parity
M2, part C §M2):
  1. a recorded `test.command` (non-empty string, via `load_repo_config`) — the operator's
     canonical command wins over every probe; `null` / absent means none recorded and
     falls through;
  2. the existing Makefile / pyproject / package.json probes — unchanged;
  3. `task_scope_runner`'s pytest-config markers (`pytest.ini`, `tox.ini [pytest]`,
     `setup.cfg [tool:pytest]`, ...) → `python3 -m pytest` (reuses
     `task_scope_runner.pytest_config` so the two sites cannot drift);
  none → `None`.

The CLI's "discover the command from CLAUDE.md" text becomes a `/tp-test-setup` pointer.
This file pins the `/tp-test-setup` TOKEN only — never the surrounding sentence.

Hermetic: plain temp dirs in `tmp_path` (the lane probes and the config read are file-
based and need no git). Config fixtures are schema-valid (a `schema_version` + only
schema keys). Stdlib only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure _shared/ is on sys.path for bare sibling imports (matches the sibling test files).
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from iteration_lane import discover_test_command, main  # noqa: E402


def _write_config(root: Path, config: dict) -> None:
    """Write a schema-valid `.three-pillars/config.json` under `root`."""
    cfg_dir = root / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _makefile(root: Path) -> None:
    (root / "Makefile").write_text("test:\n\tpython -m pytest\n")


def _pyproject_pytest(root: Path) -> None:
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = \"-q\"\n")


def _npm(root: Path) -> None:
    (root / "package.json").write_text('{"scripts": {"test": "jest"}}\n')


def _pytest_ini(root: Path) -> None:
    (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n")


def _tox_pytest(root: Path) -> None:
    (root / "tox.ini").write_text("[pytest]\naddopts = -q\n")


def _setup_cfg_pytest(root: Path) -> None:
    (root / "setup.cfg").write_text("[tool:pytest]\naddopts = -q\n")


# --- (1) a recorded test.command wins over every probe -----------------------

def test_config_command_wins_over_makefile_probe(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "test": {"command": "make check"}})
    _makefile(tmp_path)  # the probe that would otherwise resolve `make test`
    assert discover_test_command(tmp_path) == "make check"


def test_config_command_wins_over_marker_probe(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "test": {"command": "make check"}})
    _pytest_ini(tmp_path)  # the marker probe that would otherwise resolve pytest
    assert discover_test_command(tmp_path) == "make check"


# --- (2) `null` (none recorded) falls through to the existing probes ---------

def test_config_null_falls_through_to_makefile_probe(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "test": {"command": None}})
    _makefile(tmp_path)
    assert discover_test_command(tmp_path) == "make test"


def test_config_null_falls_through_to_npm_probe(tmp_path):
    _write_config(tmp_path, {"schema_version": 1, "test": {"command": None}})
    _npm(tmp_path)
    assert discover_test_command(tmp_path) == "npm test"


# --- (3) the existing Makefile / pyproject / package.json probes are unchanged --

def test_makefile_probe_still_make_test(tmp_path):
    _makefile(tmp_path)
    assert discover_test_command(tmp_path) == "make test"


def test_pyproject_probe_still_python_pytest(tmp_path):
    # Step 2 (pyproject) fires before the marker probe and keeps its `python` form.
    _pyproject_pytest(tmp_path)
    assert discover_test_command(tmp_path) == "python -m pytest"


def test_npm_probe_still_npm_test(tmp_path):
    _npm(tmp_path)
    assert discover_test_command(tmp_path) == "npm test"


# --- (4) the pytest-config marker fallback → `python3 -m pytest` --------------

def test_pytest_ini_only_resolves_python3_pytest(tmp_path):
    _pytest_ini(tmp_path)
    assert discover_test_command(tmp_path) == "python3 -m pytest"


def test_tox_ini_pytest_section_resolves_python3_pytest(tmp_path):
    _tox_pytest(tmp_path)
    assert discover_test_command(tmp_path) == "python3 -m pytest"


def test_setup_cfg_tool_pytest_resolves_python3_pytest(tmp_path):
    _setup_cfg_pytest(tmp_path)
    assert discover_test_command(tmp_path) == "python3 -m pytest"


# --- (5) nothing resolves → None ---------------------------------------------

def test_nothing_resolves_none(tmp_path):
    assert discover_test_command(tmp_path) is None


def test_config_null_alone_resolves_none(tmp_path):
    # A `null` command with NO probes/markers still yields None (not an empty command).
    _write_config(tmp_path, {"schema_version": 1, "test": {"command": None}})
    assert discover_test_command(tmp_path) is None


# --- (6) CLI: nothing resolves → rc 1, empty stdout, the /tp-test-setup token ---

def test_cli_nothing_exits_1_and_points_to_tp_test_setup(tmp_path, capsys):
    rc = main(["--lane", "iteration", "--granularity", "phase", "--repo-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""  # NEVER an empty stdout line a tee-pipe swallows as green
    assert "/tp-test-setup" in captured.err  # the token pin, not the sentence
    assert "CLAUDE.md" not in captured.err  # the old CLAUDE.md claim is gone
