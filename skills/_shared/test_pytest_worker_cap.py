"""test_pytest_worker_cap.py — the framework never asks pytest-xdist for unbounded workers.

just-do-it, operator 2026-10-07: `-n auto` started 32 workers on a 32-thread host (Strata's
cores included) and tripped the CPU package at 94.6 °C. Every `-n auto` the repo passes
carries `--maxprocesses=8`; an environment `PYTEST_ADDOPTS="-n 4"` still overrides the ini.
"""
from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAP = 8


def _cap(text: str) -> int | None:
    m = re.search(r"--maxprocesses[= ](\d+)", text)
    return int(m.group(1)) if m else None


def test_pytest_ini_caps_auto_workers():
    if not (ROOT / "pytest.ini").is_file():  # the shipped copy has no pytest.ini (consumer repos)
        pytest.skip("no pytest.ini in this tree")
    ini = configparser.ConfigParser()
    ini.read(ROOT / "pytest.ini")
    addopts = ini.get("pytest", "addopts")
    assert "-n auto" in addopts, addopts
    assert _cap(addopts) is not None and _cap(addopts) <= CAP, addopts


def test_every_scripted_n_auto_is_capped():
    hits = []
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if code.lstrip().startswith("echo"):  # a progress message, not an argv
                continue
            if re.search(r"-n auto\b", code) and not (_cap(code) and _cap(code) <= CAP):
                hits.append(f"{path.name}:{n}: {line.strip()}")
    assert not hits, "uncapped -n auto:\n" + "\n".join(hits)
