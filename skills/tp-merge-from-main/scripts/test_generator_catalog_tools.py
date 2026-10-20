"""The tool assumption probe: the catalog's argv run against the real tools.

The unit tests in `test_generator_catalog.py` never shell out, so two things the design takes for
granted stay unproven until this file runs them for real: that a catalog `write` followed by its
`check` exits 0 on a no-dependency fixture, and that the npm `check` actually refuses a lockfile
that has gone out of sync with its manifest (the case the base sync must not silently regenerate
over). The assertions are the tools' own behaviour - exit codes and their stderr - not a doc's
claim about it, so a tool change breaks here rather than in a live run.

Each test skips when its tool is absent: the probe is a claim about the machine that has npm/uv,
not a requirement that every machine carry both.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from generator_catalog import CATALOG  # noqa: E402

# Generous: these are real package managers on a cold cache, but every run is still bounded.
TIMEOUT = 120


def entry_for(basename):
    """The catalog entry for `basename`, so the probe drives the shipped argv verbatim."""
    for entry in CATALOG:
        if entry.basename == basename:
            return entry
    raise AssertionError(f"catalog has no entry for {basename}")


def run(argv, cwd, extra_env=None):
    """One catalog argv in `cwd`: list argv, no shell, captured output, hard timeout.

    `extra_env` redirects a tool's own state (below, uv's cache) into the fixture, so the probe
    asserts the tool's behaviour and not the machine's permissions on `~/.cache`."""
    env = os.environ.copy()
    env.update(extra_env or {})
    return subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True,
                          timeout=TIMEOUT, env=env)


def require(tool):
    """Skip the test when the tool is not on PATH."""
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} is not installed")


@pytest.fixture
def npm_project(tmp_path):
    """A package.json with no dependencies - everything the npm pair needs, nothing else."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "probe", "version": "1.0.0"}),
                                           encoding="utf-8")
    return tmp_path


def test_npm_write_then_check_exits_zero_with_no_dependencies(npm_project):
    """The npm pair is offline-safe on a no-dependency fixture: `write` builds the lockfile, then
    `check` accepts it - both exit 0, and the lockfile is what `write` produced."""
    require("npm")
    entry = entry_for("package-lock.json")

    write = run(entry.write, npm_project)
    assert write.returncode == 0, f"write failed:\n{write.stdout}\n{write.stderr}"
    assert (npm_project / "package-lock.json").is_file()

    check = run(entry.check, npm_project)
    assert check.returncode == 0, f"check failed:\n{check.stdout}\n{check.stderr}"


def test_npm_check_refuses_a_lock_out_of_sync_with_the_manifest(npm_project):
    """Add a dependency without re-locking and the check must refuse: non-zero exit, and npm's own
    `EUSAGE` in stderr. The dependency is a local `file:` path so nothing fetches a registry."""
    require("npm")
    entry = entry_for("package-lock.json")
    assert run(entry.write, npm_project).returncode == 0

    (npm_project / "dep").mkdir()
    (npm_project / "dep" / "package.json").write_text(
        json.dumps({"name": "dep", "version": "1.0.0"}), encoding="utf-8")
    (npm_project / "package.json").write_text(
        json.dumps({"name": "probe", "version": "1.0.0",
                    "dependencies": {"dep": "file:./dep"}}), encoding="utf-8")

    check = run(entry.check, npm_project)
    assert check.returncode != 0, f"check accepted a stale lock:\n{check.stdout}\n{check.stderr}"
    assert "EUSAGE" in check.stderr, f"no EUSAGE in stderr:\n{check.stdout}\n{check.stderr}"


def test_uv_write_then_check_exits_zero_with_no_dependencies(tmp_path):
    """The uv pair behaves the same on a pyproject.toml with no dependencies: `write` makes
    `uv.lock`, `check` accepts it, both exit 0."""
    require("uv")
    entry = entry_for("uv.lock")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n',
        encoding="utf-8")

    cache = tmp_path / "uv-cache"
    write = run(entry.write, tmp_path, extra_env={"UV_CACHE_DIR": str(cache)})
    assert write.returncode == 0, f"write failed:\n{write.stdout}\n{write.stderr}"
    assert (tmp_path / "uv.lock").is_file()

    check = run(entry.check, tmp_path, extra_env={"UV_CACHE_DIR": str(cache)})
    assert check.returncode == 0, f"check failed:\n{check.stdout}\n{check.stderr}"
