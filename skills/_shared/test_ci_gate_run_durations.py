"""test_ci_gate_run_durations.py — ci_gate_run exports the PREVIOUS head's durations dir.

design: ci-local-speed-part2 (task 1.6)

`ci_gate_run.main` hands the gate command `CI_LOCAL_DURATIONS_DIR` = the newest
other head dir under `<common git dir>/tp-ci-junit/` holding `pytest-main.xml` —
never this head's own dir, which is the one being rewritten. With no such dir, or
a failing `junit_dir`, the variable is absent and the gate runs and stamps as
today. An explicit value wins.

Stdlib + pytest only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import ci_gate_run  # noqa: E402
import ci_local_stamp  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("CI_LOCAL_MANIFEST_DIR", raising=False)
    monkeypatch.delenv("CI_LOCAL_DURATIONS_DIR", raising=False)


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
    _git(root, "config", "user.email", "t16@test.local")
    _git(root, "config", "user.name", "T16 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _default_dir(repo: Path, head: str) -> Path:
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / "tp-ci-junit" / head


def _show(tmp_path: Path) -> "tuple[str, Path]":
    out = tmp_path / "out.txt"
    cmd = f'printf %s "${{CI_LOCAL_DURATIONS_DIR-unset}}" > "{out}"'
    return cmd, out


def _seed(parent: Path, name: str, files: "list[str]", mtime: float) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("<testsuite/>", encoding="utf-8")
        os.utime(d / f, (mtime, mtime))
    return d


def test_newest_other_head_dir_with_the_main_report(tmp_path):
    repo = _make_repo(tmp_path)
    parent = _default_dir(repo, _git(repo, "rev-parse", "HEAD")).parent
    _seed(parent, "old1", ["pytest-main.xml"], 1_000_000)
    _seed(parent, "old2", ["pytest-main.xml"], 2_000_000)
    cmd, out = _show(tmp_path)
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert out.read_text(encoding="utf-8") == str(parent / "old2")


def test_the_current_heads_own_dir_is_never_used(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    mine = _default_dir(repo, head)
    _seed(mine.parent, head, ["pytest-main.xml"], 1_000_000)
    # An explicit manifest dir keeps main() from emptying the seeded default dir first.
    monkeypatch.setenv("CI_LOCAL_MANIFEST_DIR", str(tmp_path / "manifest"))
    cmd, out = _show(tmp_path)
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert out.read_text(encoding="utf-8") == "unset", "the gate was pointed at its own head dir"


def test_durations_dir_skips_the_own_head_dir_directly(tmp_path):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    _seed(_default_dir(repo, head).parent, head, ["pytest-main.xml"], 1_000_000)
    assert ci_gate_run._durations_dir(repo, head) is None


@pytest.mark.parametrize("setup", ["no-parent", "other-report-only"])
def test_no_usable_previous_report_leaves_it_unset(tmp_path, setup):
    repo = _make_repo(tmp_path)
    parent = _default_dir(repo, _git(repo, "rev-parse", "HEAD")).parent
    if setup == "other-report-only":
        _seed(parent, "old1", ["f8.xml"], 1_000_000)
    cmd, out = _show(tmp_path)
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert out.read_text(encoding="utf-8") == "unset"


def test_failing_junit_dir_still_runs_and_stamps(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)

    def broken(_repo, _head):
        raise ValueError("no common git dir")

    monkeypatch.setattr(ci_gate_run, "junit_dir", broken)
    cmd, out = _show(tmp_path)
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert out.read_text(encoding="utf-8") == "unset"
    assert ci_local_stamp.read_stamp(repo) is not None


def test_explicit_value_wins(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    parent = _default_dir(repo, _git(repo, "rev-parse", "HEAD")).parent
    _seed(parent, "old1", ["pytest-main.xml"], 1_000_000)
    _seed(parent, "old2", ["pytest-main.xml"], 2_000_000)
    monkeypatch.setenv("CI_LOCAL_DURATIONS_DIR", "/given")
    cmd, out = _show(tmp_path)
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert out.read_text(encoding="utf-8") == "/given"
