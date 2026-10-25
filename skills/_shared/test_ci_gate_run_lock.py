"""test_ci_gate_run_lock.py — the gate runs under the machine lock; tests never take it.

design: ci-local-speed-part2 (task 1.9, Behaviors 3, 5)

`ci_gate_run.main` takes `ci_gate_lock` before sampling HEAD / dirty state, holds it
across the gate command and the stamp, and releases it on every path (rc 0, a non-zero
rc, a `StampError` refusal, an exception). A timeout still runs the command with today's
rc and stamp; a gate nested in one that already holds the lock runs at once. Inside a
test the lock path is the `skills/conftest.py` sandbox's per-test file, so no test ever
contends with a real gate.

Stdlib + pytest only.
"""
from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import ci_gate_lock  # noqa: E402
import ci_gate_run  # noqa: E402
import ci_local_stamp  # noqa: E402

# The gate command exits 0 only when the lock file refuses a second flock AND the
# holder marker is set: the command ran while the machine lock was held. When
# PROBE_SENTINEL names a file the probe also records that it ran (and the holder marker
# it saw), so a test can tell "the command ran" from "main merely returned its rc".
PROBE_SCRIPT = (
    "import fcntl, os, sys\n"
    "sentinel = os.environ.get('PROBE_SENTINEL')\n"
    "if sentinel:\n"
    "    with open(sentinel, 'w') as fh:\n"
    "        fh.write('ran held=' + os.environ.get('CI_GATE_LOCK_HELD', ''))\n"
    "fd = os.open(os.environ['CI_GATE_LOCK'], os.O_RDWR | os.O_CREAT)\n"
    "try:\n"
    "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "except BlockingIOError:\n"
    "    sys.exit(0 if os.environ.get('CI_GATE_LOCK_HELD') else 5)\n"
    "sys.exit(1)\n"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("CI_LOCAL_MANIFEST_DIR", raising=False)
    monkeypatch.delenv("CI_LOCAL_DURATIONS_DIR", raising=False)
    monkeypatch.delenv(ci_gate_lock.HELD_ENV, raising=False)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "x.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t19@test.local")
    _git(root, "config", "user.name", "T19 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _lock(monkeypatch, tmp_path: Path) -> Path:
    """An explicit per-test lock path (the conftest sandbox fixture is this task's Green)."""
    path = tmp_path / "gate.lock"
    monkeypatch.setenv(ci_gate_lock.LOCK_ENV, str(path))
    return path


def _probe(tmp_path: Path) -> str:
    script = tmp_path / "probe.py"
    script.write_text(PROBE_SCRIPT, encoding="utf-8")
    return f'python3 "{script}"'


def _holder(path: Path):
    """A competing gate: flock a second open of the lock file."""
    fh = open(path, "w", encoding="utf-8")  # noqa: SIM115 - released by the test
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fh.write("pid=999 repo=/other/head=beef")
    fh.flush()
    return fh


def _flock_refused(path: Path) -> bool:
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def test_command_runs_while_the_lock_is_held(tmp_path, monkeypatch):
    _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)
    assert ci_gate_run.main(["--repo", str(repo), "--command", _probe(tmp_path)]) == 0
    assert ci_local_stamp.read_stamp(repo) is not None


@pytest.mark.parametrize("command", ["true", "exit 3"])
def test_released_after_the_command_rc(tmp_path, monkeypatch, command, capsys):
    path = _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)
    rc = ci_gate_run.main(["--repo", str(repo), "--command", command])
    assert rc == (0 if command == "true" else 3)
    assert not _flock_refused(path)
    assert "waiting for" not in capsys.readouterr().err


def test_released_after_a_stamp_error_refusal(tmp_path, monkeypatch):
    path = _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)
    (repo / "loose.txt").write_text("untracked\n", encoding="utf-8")
    assert ci_gate_run.main(["--repo", str(repo), "--command", "true"]) == 1
    assert not _flock_refused(path)


def test_released_when_the_gate_raises(tmp_path, monkeypatch):
    path = _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)

    def boom(_made):
        raise RuntimeError("junit finish blew up")

    monkeypatch.setattr(ci_gate_run, "_finish_junit", boom)
    with pytest.raises(RuntimeError):
        ci_gate_run.main(["--repo", str(repo), "--command", "true"])
    assert not _flock_refused(path)


def test_head_is_sampled_after_the_lock(tmp_path, monkeypatch):
    """A commit that lands while this gate waits must be the HEAD the stamp names."""
    path = _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)
    holder = _holder(path)
    calls = []

    def _sleep(_seconds):
        calls.append(1)
        (repo / "late.txt").write_text("landed during the wait\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "landed during the wait")
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()

    monkeypatch.setattr(ci_gate_lock, "_sleep", _sleep)
    assert ci_gate_run.main(["--repo", str(repo), "--command", "true"]) == 0
    assert calls, "the gate must wait for the lock"
    stamp = ci_local_stamp.read_stamp(repo)
    assert stamp is not None
    assert stamp["head_sha"] == _git(repo, "rev-parse", "HEAD"), (
        "HEAD sampled before the wait would refuse the stamp as moved"
    )


def test_timeout_still_runs_the_command_and_stamps(tmp_path, monkeypatch, capsys):
    path = _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)
    holder = _holder(path)
    monkeypatch.setenv(ci_gate_lock.WAIT_ENV, "0")
    monkeypatch.setattr(ci_gate_lock, "_sleep", lambda _s: None)
    sentinel = tmp_path / "probe-ran.txt"
    monkeypatch.setenv("PROBE_SENTINEL", str(sentinel))
    rc = ci_gate_run.main(["--repo", str(repo), "--command", _probe(tmp_path)])
    assert rc == 0, f"ci_gate_run.main: a lock timeout must still return the command's rc 0, got {rc}"
    assert sentinel.exists(), "ci_gate_run.main: the gate command must actually run after the lock wait times out"
    assert sentinel.read_text(encoding="utf-8") == f"ran held={os.getpid()}", (
        "ci_gate_run.main: the command must run with the holder marker set to this gate's pid"
    )
    err = capsys.readouterr().err
    assert "busy, waiting for" in err, "busy, waiting for: the timed-out gate must print the wait notice on stderr"
    assert "running anyway" in err, "running anyway: the timed-out gate must say it runs anyway"
    assert ci_local_stamp.read_stamp(repo) is not None, (
        "ci_local_stamp.read_stamp: a timed-out gate must still write its stamp"
    )
    fcntl.flock(holder, fcntl.LOCK_UN)
    holder.close()


def test_nested_gate_runs_at_once(tmp_path, monkeypatch, capsys):
    path = _lock(monkeypatch, tmp_path)
    repo = _make_repo(tmp_path)
    holder = _holder(path)
    monkeypatch.setenv(ci_gate_lock.HELD_ENV, str(os.getpid()))
    assert ci_gate_run.main(["--repo", str(repo), "--command", "true"]) == 0
    assert "waiting for" not in capsys.readouterr().err
    fcntl.flock(holder, fcntl.LOCK_UN)
    holder.close()


def test_a_test_never_takes_the_machine_lock():
    """`skills/conftest.py` gives every test its own lock path (Behavior 5)."""
    lock = Path(os.environ[ci_gate_lock.LOCK_ENV])
    assert lock == Path(tempfile.tempdir) / "tp-ci-gate.lock"
    assert ci_gate_lock.HELD_ENV not in os.environ
