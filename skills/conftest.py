"""skills/conftest.py — contain every test's temp files (ships with the plugin).

Each test runs with `tempfile.tempdir` and `TMPDIR` pointed at its own short scratch
dir, removed after the test, so a bare `tempfile.mkdtemp()`, a subprocess or a shell
`mktemp` in any test cannot leave files in the real temp dir (five tests once leaked
~21k git repos into /tmp). It lives under skills/ rather than the repo root so it
ships: dev runs, a run over the shipped tree and plugin installs all get it.
The dir stays short (`<tmp>/tpt-XXXXXXXX/tXXXXXXXX`) for the 107-char AF_UNIX limit.
When the session's temp dir is the run's in-tree dir (`<wt>/.tp-scratch/run`) or too long for that
limit, pytest's own basetemp (`tmp_path`) moves too: to a fresh `tpt-<tag>-b<8 hex>/p` in the system
temp root (`_SOCKET_PARENT`), removed at session end, so no test's temp dir sits inside a git
checkout (`pytest_configure`).

It also sandboxes the local router's state (`_no_live_slot_release`) for the same reason: a
guard in the dev-only `_shared/conftest.py` never reaches the shipped tree. And it pins the
identity core's repo-config discovery to an empty dir (`_no_ambient_repo_config`), so no test
posts as the bot this repo's own config names.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_STALE_ROOT_S = 24 * 3600


_SOCKET_PARENT = "/tmp"  # nosec B108  # where a long or in-tree TMPDIR run keeps its short roots
_SHORT_TMP_MAX = 40
_RUN_SUFFIX = os.sep + os.path.join(".tp-scratch", "run")


def _needs_short(path: str) -> bool:
    """True when tests must not run under `path`: the run's in-tree dir, or too long for AF_UNIX."""
    norm = os.path.normpath(path)
    return len(norm) > _SHORT_TMP_MAX or norm.endswith(_RUN_SUFFIX)


def _sweep_stale(parent: str) -> None:
    """Remove `tpt-*` roots older than a day under `parent` (left by killed runs, whatever their tag)."""
    for old in Path(parent).glob("tpt-*"):
        try:
            if time.time() - old.stat().st_mtime > _STALE_ROOT_S:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


def _run_tag() -> str:
    """6 hex of sha1(realpath worktree): the same recipe as `run_scratch.tag`, inline so this ships alone.

    The worktree is two levels above a run-dir-shaped session TMPDIR (`<wt>/.tp-scratch/run`), so a
    nested attempt worker's leak carries the run's tag; else the cwd's top level.
    """
    tmp = os.path.normpath(os.environ.get("TMPDIR") or "")
    if os.path.isabs(tmp) and tmp.endswith(_RUN_SUFFIX):
        wt = os.path.dirname(os.path.dirname(tmp))
    else:
        try:
            out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
            wt = out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            wt = ""
        wt = wt or os.getcwd()
    return hashlib.sha1(os.path.realpath(wt).encode(), usedforsecurity=False).hexdigest()[:6]  # noqa: S324


def _make_root() -> str:
    real = tempfile.gettempdir()
    if not _needs_short(real):
        parent, prefix = real, "tpt-"
    else:
        parent, prefix = _SOCKET_PARENT, "tpt-" + _run_tag() + "-"
    _sweep_stale(parent)
    return tempfile.mkdtemp(prefix=prefix, dir=parent)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Move pytest's basetemp out of a long or in-tree temp dir (controller only; fail-open).

    Runs before pytest's tmpdir plugin reads `--basetemp`. An explicit `--basetemp` is kept, and an
    xdist worker already has one (`<controller basetemp>/popen-gwN`), so workers inherit the move.
    The holder is a fresh 0700 dir; pytest makes `p` inside it, so the name is never pre-claimed.
    """
    if getattr(config.option, "basetemp", None) or hasattr(config, "workerinput"):
        return
    if not _needs_short(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()):
        return
    try:
        _sweep_stale(_SOCKET_PARENT)
        holder = os.path.join(_SOCKET_PARENT, "tpt-" + _run_tag() + "-b" + secrets.token_hex(4))
        os.mkdir(holder, 0o700)
    except OSError:
        return  # pytest keeps its default basetemp
    config._tpt_basetemp_holder = holder
    config.option.basetemp = os.path.join(holder, "p")


def pytest_unconfigure(config):
    holder = getattr(config, "_tpt_basetemp_holder", None)
    if holder:
        shutil.rmtree(holder, ignore_errors=True)


@pytest.fixture(scope="session")
def _tempfile_root(tmp_path_factory):
    tmp_path_factory.getbasetemp()  # pin pytest's own basetemp before TMPDIR is redirected
    root = _make_root()
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


@pytest.fixture(autouse=True)
def _no_machine_gate_lock(_contain_tempfiles, monkeypatch, request):
    """A test's gate never contends with a real gate, or with another test.

    design: ci-local-speed-part2 (task 1.9, Behavior 5). `ci_gate_run.main` takes a
    machine-wide advisory lock (`ci_gate_lock`), so a test that runs the gate would sit
    behind — or block — the real `ci-local` gate. `CI_GATE_LOCK` goes to a per-test file in
    this test's own scratch dir; the holder marker is cleared so the test's gate exercises
    the lock. A suite run BY a gate still tests it: the gate exports `CI_GATE_LOCK_HELD` to
    its command. It lives here, not in `_shared/conftest.py`, so the ship copy gets it too.
    `test_ci_gate_lock.py` is exempt: it tests path resolution through an explicit env dict.
    """
    monkeypatch.delenv("CI_GATE_LOCK_HELD", raising=False)
    node_path = getattr(request.node, "path", None) or getattr(request.node, "fspath", None)
    if node_path is not None and Path(str(node_path)).name == "test_ci_gate_lock.py":
        monkeypatch.delenv("CI_GATE_LOCK", raising=False)
        return
    monkeypatch.setenv("CI_GATE_LOCK", str(Path(tempfile.tempdir) / "tp-ci-gate.lock"))


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
