"""test_unit_marker.py — Task 1.3 guard for the pure-`unit` inner-loop lane.

design: iteration-speed

The `unit` marker is applied by skills/_shared/conftest.py's
`pytest_collection_modifyitems` hook to every item whose module basename is in the
curated `_UNIT_MODULES` frozenset — pure-logic modules (no subprocess, no real git)
that form the <10s inner loop (`pytest -m unit -n0`).

This guard pins the contract against allowlist drift:
  (a) `_UNIT_MODULES` is a NON-EMPTY curated allowlist, and every entry names a real
      skills/_shared/ test module that actually defines test functions (so `-m unit`
      selects > 0 items).
  (b) every allowlisted module's SOURCE imports/uses no `subprocess` (a structural
      purity source-scan — not merely a wall-clock backstop).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _load_conftest_unit_modules():
    """Load skills/_shared/conftest.py under a unique name (avoiding any collision
    with pytest's own conftest import machinery) and return its _UNIT_MODULES."""
    spec = importlib.util.spec_from_file_location(
        "_iterspeed_conftest_probe", HERE / "conftest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._UNIT_MODULES


_UNIT_MODULES = _load_conftest_unit_modules()


def _uses_subprocess(src: str) -> bool:
    return (
        "import subprocess" in src
        or "from subprocess" in src
        or "subprocess." in src
    )


def test_unit_allowlist_is_non_empty():
    assert _UNIT_MODULES, "_UNIT_MODULES must be a non-empty curated allowlist"


def test_unit_modules_exist_and_define_tests():
    for name in sorted(_UNIT_MODULES):
        mod = HERE / f"{name}.py"
        assert mod.exists(), f"_UNIT_MODULES entry {name!r} has no skills/_shared/{name}.py"
        src = mod.read_text(encoding="utf-8")
        assert "def test" in src, (
            f"{name!r} defines no test functions — it would contribute 0 unit items"
        )


def test_unit_modules_are_subprocess_free():
    offenders = [
        name
        for name in sorted(_UNIT_MODULES)
        if (HERE / f"{name}.py").exists()
        and _uses_subprocess((HERE / f"{name}.py").read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"unit-lane modules must be pure-logic (no subprocess); offenders: {offenders}"
    )


def test_collection_hook_actually_applies_unit_marker():
    """Pin the PRODUCTION MECHANISM, not just the `_UNIT_MODULES` data: run a real
    `-m unit -n0 --co` collection so conftest.py::pytest_collection_modifyitems runs.
    If the hook regresses (stops applying the marker), `-m unit` selects 0 items and
    the inner-loop lane is silently empty — the data-only guards above stay green over
    that broken hook (the production-arm-unpinned-by-tests class). `-n0` keeps the
    subprocess serial (no nested xdist under the repo's `-n auto` addopts)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "skills/_shared/",
         "-m", "unit", "-n0", "--co", "-q"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    tail = proc.stdout[-2000:] + "\n" + proc.stderr[-500:]
    assert "no tests collected" not in proc.stdout, (
        "`pytest -m unit` collected 0 items — the conftest "
        "pytest_collection_modifyitems hook is not applying the `unit` marker.\n" + tail
    )
    # A known allowlist member's nodes must appear among the collected `-m unit` items
    # — proves the hook actually MARKED them, not merely that the allowlist data is valid.
    sample = sorted(_UNIT_MODULES)[0]
    assert f"{sample}.py::" in proc.stdout or f"{sample}::" in proc.stdout, (
        f"expected `unit`-marked items from {sample!r} in the `-m unit` collection; "
        "the hook may not be applying the marker.\n" + tail
    )
