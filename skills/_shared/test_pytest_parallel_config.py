"""test_pytest_parallel_config.py — Task 1.1 guard for the xdist adoption.

design: iteration-speed

Pins the four halves of the parallel-test contract:
  (a) pytest.ini's addopts enables `-n auto` (parallel by default).
  (b) pytest.ini registers BOTH the `unit` and `serial` markers.
  (c) requirements-dev.txt declares `pytest-xdist` as a dev dependency.
  (d) the documented `-n0` serial/debug escape hatch actually works — a tiny
      collection under `-n0` runs serially and exits clean even with `-n auto`
      injected by addopts. (NOT `-p no:xdist`, which removes the -n parser while
      addopts still passes -n auto → `error: unrecognized arguments: -n`, exit 4.)
"""
from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_INI = REPO_ROOT / "pytest.ini"
REQ_DEV = REPO_ROOT / "requirements-dev.txt"


def _pytest_cfg() -> configparser.ConfigParser:
    # interpolation=None so a literal '%' in addopts can never raise.
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(PYTEST_INI, encoding="utf-8")
    return cfg


def test_addopts_enables_n_auto():
    cfg = _pytest_cfg()
    assert cfg.has_option("pytest", "addopts"), "pytest.ini must declare an addopts line"
    addopts = cfg.get("pytest", "addopts")
    assert "-n auto" in addopts, f"addopts must enable xdist via '-n auto', got: {addopts!r}"


def test_markers_register_unit_and_serial():
    cfg = _pytest_cfg()
    assert cfg.has_option("pytest", "markers"), "pytest.ini must declare a markers section"
    markers = cfg.get("pytest", "markers")
    assert "unit:" in markers, f"markers must register 'unit', got: {markers!r}"
    assert "serial:" in markers, f"markers must register 'serial', got: {markers!r}"


def test_pytest_xdist_is_declared_dev_dependency():
    assert REQ_DEV.exists(), "requirements-dev.txt must exist"
    lines = REQ_DEV.read_text(encoding="utf-8").splitlines()
    assert any(
        line.strip().lower().startswith("pytest-xdist") for line in lines
    ), f"requirements-dev.txt must declare pytest-xdist, got: {lines!r}"


def test_n0_serial_escape_hatch_runs_without_error(tmp_path):
    """The documented serial/debug escape hatch is `-n0` (numeric zero: the xdist
    plugin stays loaded, 0 workers = serial). Pin it: a tiny collection under `-n0`
    runs serially and exits clean even with `-n auto` in addopts."""
    probe = tmp_path / "test_escape_hatch_probe.py"
    probe.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-n0", "-q", "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "`-n0` escape hatch must run serially without error; "
        f"rc={result.returncode}\nstdout={result.stdout[-1500:]}\nstderr={result.stderr[-500:]}"
    )
