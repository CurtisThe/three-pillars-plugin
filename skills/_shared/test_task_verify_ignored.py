"""test_task_verify_ignored.py — check judges the committed tree, never an ignored file.

design: local-implement-and-review (PR #165 r12 ruling, amendment A32)

Step 4's porcelain never lists gitignored files, and step 6 runs the Targets in the
attempt worktree. So an ignored implementation file (``lib/`` in GitHub's stock Python
``.gitignore``: ``git add`` refuses it, the commit carries only the test) made the
Targets green on disk while ``land`` fast-forwarded a red test. ``check`` now deletes
the attempt's ignored files before any Target runs (both the commit path and the
``pre_exists`` path) and logs each one it removed, bytecode caches aside. A33 adds the
two r13 residuals: a tracked edit hidden by ``skip-worktree`` / ``assume-unchanged`` is
uncommitted work, and the scrub runs only in a placed attempt dir. Real tmp repos.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import task_attempts
import task_verify
from attempt_fixture import DD, commit, git, make_seat, task_row, write

RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider"
IGNORE = "lib/\n__pycache__/\n.pytest_cache/\n"
TEST = ("import pathlib, sys\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'lib'))\n"
        "from helpers import two\n\n\n"
        "def test_two():\n    assert two() == 2\n")
TARGET = "`tests/test_helpers.py::test_two`"


def _seat(tmp_path: Path, files: dict | None = None) -> Path:
    _seat_dir, wt = make_seat(tmp_path)
    commit(wt, {".gitignore": IGNORE, **(files or {})}, "ignore lib/ and caches")
    return wt


def test_ignored_implementation_never_passes_and_never_lands(tmp_path):
    wt = _seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    write(adir, "lib/helpers.py", "def two():\n    return 2\n")
    write(adir, "tests/test_helpers.py", TEST)
    git(adir, "add", "--", "tests/test_helpers.py")  # `git add lib/helpers.py` is refused
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    res = task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                            rung="local", timeout=120)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")
    assert "ignored-removed: lib/" in res["logged"]
    assert not (adir / "lib").exists()
    head = git(wt, "rev-parse", "HEAD")
    assert task_verify.land(att)["reason"] == "not-passed: FAIL"
    assert git(wt, "rev-parse", "HEAD") == head


def test_pre_exists_never_passes_on_an_ignored_file(tmp_path):
    """Opus, zero commits: the base test is green only through an ignored file."""
    wt = _seat(tmp_path, {"tests/test_helpers.py": TEST})
    att = task_attempts.open_attempt(wt, "1.1", DD)
    write(Path(att["attempt_dir"]), "lib/helpers.py", "def two():\n    return 2\n")
    res = task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                            rung="opus", timeout=120)
    assert (res["verdict"], res["reason"], res["pre_exists"]) == ("FAIL", "no commit", False)


def test_committed_work_still_passes_and_caches_are_not_logged(tmp_path):
    """A worker that ran pytest leaves ignored caches: removed, never named, still PASS."""
    wt = _seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    write(adir, "lib/helpers.py", "def two():\n    return 2\n")
    write(adir, "tests/test_helpers.py", TEST)
    git(adir, "add", "-f", "--", "lib/helpers.py", "tests/test_helpers.py")
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    env = {k: v for k, v in os.environ.items()  # the worker's run writes its caches
           if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=adir, env=env,
                   capture_output=True, text=True, check=True)
    assert (adir / "tests" / "__pycache__").is_dir()  # the ignored cache is there
    res = task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                            rung="local", timeout=120)
    assert (res["verdict"], res["exit"]) == ("PASS", 0), res["reason"]
    assert not any(n.startswith("ignored-removed") for n in res["logged"])
    assert task_verify.land(att)["exit"] == 0


# A33: the two residuals of r13 — an index-hidden edit, and a scrub outside its attempt.
BASE_LIB = {"lib/helpers.py": "def two():\n    return 1\n"}


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_an_index_hidden_edit_never_passes(tmp_path, flag):
    """A tracked File edited on disk but hidden from `git status` never counts."""
    wt = _seat(tmp_path)
    write(wt, "lib/helpers.py", BASE_LIB["lib/helpers.py"])
    git(wt, "add", "-f", "--", "lib/helpers.py")
    git(wt, "commit", "-q", "-m", "red base")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    write(adir, "lib/helpers.py", "def two():\n    return 2\n")
    write(adir, "tests/test_helpers.py", TEST)
    git(adir, "add", "--", "tests/test_helpers.py")
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    git(adir, "update-index", flag, "--", "lib/helpers.py")
    res = task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                            rung="local", timeout=120)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")  # A35: HEAD is judged
    assert (adir / "lib" / "helpers.py").read_text(encoding="utf-8").endswith("return 1\n")


def test_pre_exists_never_passes_on_an_index_hidden_edit(tmp_path):
    wt = _seat(tmp_path, {"tests/test_helpers.py": TEST})
    write(wt, "lib/helpers.py", BASE_LIB["lib/helpers.py"])
    git(wt, "add", "-f", "--", "lib/helpers.py")
    git(wt, "commit", "-q", "-m", "red base")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    write(adir, "lib/helpers.py", "def two():\n    return 2\n")
    git(adir, "update-index", "--skip-worktree", "--", "lib/helpers.py")
    res = task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                            rung="opus", timeout=120)
    assert (res["verdict"], res["reason"], res["pre_exists"]) == ("FAIL", "no commit", False)


def test_the_scrub_refuses_a_dir_that_is_not_the_attempt(tmp_path):
    """A record whose attempt_dir is moved elsewhere (another worktree, the dispatcher)
    never gets `git clean -ffdX`: exit 2 and the ignored files there survive."""
    wt = _seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    keep = write(wt, "lib/keep.py", "precious\n")  # ignored in the dispatcher
    for elsewhere in (wt, Path(att["attempt_dir"]) / "tests"):
        with pytest.raises(task_verify._EnvError, match="ignored-scrub-refused"):
            task_verify._scrub_ignored({**att, "attempt_dir": str(elsewhere)})
    assert keep.read_text(encoding="utf-8") == "precious\n"


def test_an_ignored_name_that_is_not_utf8_is_scrubbed_not_a_crash(tmp_path):
    wt = _seat(tmp_path, {".gitignore": IGNORE + "*.log\n"})  # listed one by one
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    write(adir, "tests/test_helpers.py", TEST)
    write(adir, "lib/helpers.py", "def two():\n    return 2\n")
    git(adir, "add", "--", "tests/test_helpers.py")
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    open(bytes(adir) + b"/\xff.log", "wb").close()  # an ignored name, not valid UTF-8
    res = task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                            rung="local", timeout=120)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")
    assert not (adir / "lib").exists()


# A34/A35: r14's and r15's regressions — sparse checkout, a symlinked .claude, a hidden
# deletion or mode change — closed by writing HEAD over the attempt before any Target.
def _commit_work(att) -> Path:
    adir = Path(att["attempt_dir"])
    write(adir, "lib/helpers.py", "def two():\n    return 2\n")
    write(adir, "tests/test_helpers.py", TEST)
    git(adir, "add", "-f", "--", "lib/helpers.py", "tests/test_helpers.py")
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    return adir


def _check(att, rung="local"):
    return task_verify.check(att, task_row(("lib/helpers.py",), TARGET), RUNNER,
                             rung=rung, timeout=120)


def test_sparse_checkout_out_of_cone_paths_are_not_hidden_work(tmp_path):
    """Sparse checkout tags every out-of-cone path `S` with no file on disk."""
    wt = _seat(tmp_path, {"docs/far.md": "out of cone\n"})
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = _commit_work(att)
    git(adir, "sparse-checkout", "set", "--no-cone", "/*", "!/docs/")
    assert "S docs/far.md" in git(adir, "ls-files", "-v")  # the premise holds
    res = _check(att)
    assert (res["verdict"], res["exit"]) == ("PASS", 0), res["reason"]


def test_a_flagged_entry_whose_file_matches_the_index_is_not_hidden_work(tmp_path):
    wt = _seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = _commit_work(att)
    git(adir, "update-index", "--assume-unchanged", "--", "lib/helpers.py")  # unedited
    assert _check(att)["verdict"] == "PASS"


def test_a_symlinked_claude_dir_still_places_the_attempt(tmp_path):
    wt = _seat(tmp_path, {".gitignore": IGNORE + ".claude\n"})  # the link itself
    real = tmp_path / "real-claude"
    real.mkdir()
    (wt / ".claude").symlink_to(real, target_is_directory=True)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    _commit_work(att)
    res = _check(att)
    assert (res["verdict"], res["exit"]) == ("PASS", 0), res["reason"]


def test_the_scrub_refuses_a_placed_dir_that_is_not_its_own_toplevel(tmp_path):
    """A plain dir named like an attempt passes `removable`, but its git toplevel is the
    dispatcher: `git clean` there would reach the dispatcher's ignored files."""
    wt = _seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    fake = Path(att["attempt_dir"]).parent / "tp-attempt-fake"
    fake.mkdir()
    keep = write(wt, "lib/keep.py", "precious\n")
    with pytest.raises(task_verify._EnvError, match="ignored-scrub-refused"):
        task_verify._scrub_ignored({**att, "attempt_dir": str(fake)})
    assert keep.read_text(encoding="utf-8") == "precious\n"


def test_a_committed_name_that_is_not_utf8_is_judged_not_a_crash(tmp_path):
    wt = _seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    open(bytes(adir) + b"/\xff.txt", "wb").close()
    git(adir, "add", "-A")
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    res = _check(att)
    assert (res["verdict"], res["reason"]) == ("FAIL", "unlisted file: \udcff.txt")


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_a_hidden_deletion_never_passes(tmp_path, flag):
    """The base's conftest fails every test; a worker deletes it and hides the delete."""
    wt = _seat(tmp_path, {"tests/conftest.py": "def pytest_runtest_call(item):\n"
                                                "    raise AssertionError('policy')\n"})
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = _commit_work(att)
    git(adir, "update-index", flag, "--", "tests/conftest.py")
    (adir / "tests" / "conftest.py").unlink()
    assert git(adir, "status", "--porcelain") == ""  # hidden from status
    assert (_check(att)["verdict"], _check(att)["reason"]) == ("FAIL", "red test")


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_a_hidden_mode_change_never_passes(tmp_path, flag):
    wt = _seat(tmp_path, {"bin/run.sh": "#!/bin/sh\n"})
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    write(adir, "tests/test_mode.py", "import os\n\n\ndef test_x():\n"
          "    assert os.access('bin/run.sh', os.X_OK)\n")
    git(adir, "add", "--", "tests/test_mode.py")
    git(adir, "commit", "-q", "-m", "Implement: demo 1.1")
    (adir / "bin" / "run.sh").chmod(0o755)
    git(adir, "update-index", flag, "--", "bin/run.sh")
    res = task_verify.check(att, task_row(("bin/run.sh",), "`tests/test_mode.py::test_x`"),
                            RUNNER, rung="local", timeout=120)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")


def test_ignore_stat_with_a_crlf_blob_still_passes(tmp_path):
    """core.ignoreStat tags every entry; a CRLF blob under autocrlf is not an edit."""
    wt = _seat(tmp_path)
    (wt / "win.txt").write_bytes(b"crlf\r\n")
    git(wt, "add", "--", "win.txt")
    git(wt, "commit", "-q", "-m", "crlf blob")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = _commit_work(att)
    git(adir, "config", "core.autocrlf", "true")
    git(adir, "config", "core.ignoreStat", "true")
    res = _check(att)
    assert (res["verdict"], res["exit"]) == ("PASS", 0), res["reason"]
    assert (adir / "win.txt").read_bytes() == b"crlf\r\n"
