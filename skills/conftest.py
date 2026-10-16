"""skills/conftest.py — contain every test's temp files (ships with the plugin).

Each test runs with `tempfile.tempdir` and `TMPDIR` pointed at its own short scratch
dir, removed after the test, so a bare `tempfile.mkdtemp()`, a subprocess or a shell
`mktemp` in any test cannot leave files in the real temp dir (five tests once leaked
~21k git repos into /tmp). It lives under skills/ rather than the repo root so it
ships: dev runs, a run over the shipped tree and plugin installs all get it.
The dir stays short (`<tmp>/tpt-XXXXXXXX/tXXXXXXXX`) for the 107-char AF_UNIX limit.

It also sandboxes the local router's state (`_no_live_slot_release`) for the same reason: a
guard in the dev-only `_shared/conftest.py` never reaches the shipped tree. And it pins the
identity core's repo-config discovery to an empty dir (`_no_ambient_repo_config`), so no test
posts as the bot this repo's own config names.
"""
from __future__ import annotations

import functools
import importlib
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

_STALE_ROOT_S = 24 * 3600


@pytest.fixture(scope="session")
def _tempfile_root(tmp_path_factory):
    tmp_path_factory.getbasetemp()  # pin pytest's own basetemp before TMPDIR is redirected
    real = Path(tempfile.gettempdir())
    for old in real.glob("tpt-*"):  # roots left by killed runs
        try:
            if time.time() - old.stat().st_mtime > _STALE_ROOT_S:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    root = tempfile.mkdtemp(prefix="tpt-", dir=real)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _contain_tempfiles(_tempfile_root, monkeypatch):
    scratch = tempfile.mkdtemp(prefix="t", dir=_tempfile_root)
    monkeypatch.setattr(tempfile, "tempdir", scratch)
    monkeypatch.setenv("TMPDIR", scratch)
    yield
    shutil.rmtree(scratch, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_live_slot_release(_contain_tempfiles, monkeypatch):
    """No test may read or write the live local router's state.

    design: slot-release-on-attempt-end (plan constraint: tests never touch the real router).
    `attempt_watchdog.py`'s `poll` (on `done`) and `stopped` call `local_lease.release_agent`,
    which loads the real `slot_owner.py` whenever `tp-local` is on PATH. Three things close that:

    - `TP_SLOT_RELEASE=0`: a release answers `disabled` before any router module loads.
    - `TP_LOCAL_SLOT_STATE` points at a per-test scratch file. The router reads it ahead of
      `XDG_STATE_HOME` and `~/.local/state`, so an `acquire` probe, or a release test that opts
      back in, writes a throwaway file and never `slot-owner.json`.
    - `TP_LOCAL_STOPPED` points the stopped-agents backstop at the same scratch dir.

    It lives here and not in `_shared/conftest.py`, which never ships (`dev_only_shared`), so
    dev runs, the ship copy (consumer-fixture-smoke F8) and plugin installs all get it. A test
    that needs the real release path opts back in with `monkeypatch.delenv("TP_SLOT_RELEASE")`
    and sets its own state path (see `test_slot_release_contract.py`).
    """
    sandbox = Path(tempfile.mkdtemp(prefix="slot", dir=tempfile.tempdir))
    monkeypatch.setenv("TP_SLOT_RELEASE", "0")
    monkeypatch.setenv("TP_LOCAL_SLOT_STATE", str(sandbox / "slot-owner.json"))
    monkeypatch.setenv("TP_LOCAL_STOPPED", str(sandbox / "stopped-agents.jsonl"))


def _identity_core():
    """The `automation_identity` module under its plain name, or None when the tree lacks it."""
    if "automation_identity" not in sys.modules:
        shared = str(Path(__file__).resolve().parent / "_shared")
        sys.path.insert(0, shared)
        try:
            importlib.import_module("automation_identity")
        except ImportError:
            return None
        finally:
            if sys.path and sys.path[0] == shared:
                del sys.path[0]
    return sys.modules["automation_identity"]


@pytest.fixture(autouse=True)
def _no_ambient_repo_config(_contain_tempfiles, monkeypatch):
    """No test discovers the repo's own `.three-pillars/config.json` through a write helper.

    design: review-proof-ambient-gh-identity. Every automation write helper defaults to
    `config=DISCOVER`: `automation_identity.run_gh_write` loads the config from the git toplevel
    (`_default_repo_root`). Run inside this repo that finds `github.pr_author_account` and would
    fetch a real token (`gh auth token --user <bot>`) and post as the bot. This pins
    `automation_identity._default_repo_root` to an empty per-test dir, so discovery yields `{}`
    (the ambient path) and every write-site test stays hermetic. A discovery test opts back in
    by patching `_default_repo_root` to a tmp repo that names the bot; the pin keeps the original
    as `__wrapped__`.

    It lives here and not in `_shared/conftest.py`, which never ships, for the same reason as
    `_no_live_slot_release`. The module is imported by name (so it is the object write helpers
    see), with `_shared` on the path only for that import; a tree without it has nothing to pin.
    """
    core = _identity_core()
    if core is None:
        return
    empty = Path(tempfile.mkdtemp(prefix="repo", dir=tempfile.tempdir))

    @functools.wraps(core._default_repo_root)
    def pinned() -> Path:
        return empty

    monkeypatch.setattr(core, "_default_repo_root", pinned)
