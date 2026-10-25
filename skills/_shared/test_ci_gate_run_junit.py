"""test_ci_gate_run_junit.py — ci_gate_run exports a per-head junit directory.

design: ci-local-speed (task 1.8, B7)

With `CI_LOCAL_MANIFEST_DIR` unset, `ci_gate_run.main` hands the gate command
`<common git dir>/tp-ci-junit/<HEAD sha>` in that variable, so the stage junit
survives `git worktree remove`. An explicit value wins. A command that writes
no junit leaves no directory. Only the newest 20 head dirs are kept.

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

WRITE = (
    'printf "<testsuite/>" > "$CI_LOCAL_MANIFEST_DIR/pytest-main.xml" && '
    'printf "<testsuite/>" > "$CI_LOCAL_MANIFEST_DIR/f8.xml"'
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("CI_LOCAL_MANIFEST_DIR", raising=False)


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
    _git(root, "config", "user.email", "t18@test.local")
    _git(root, "config", "user.name", "T18 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _default_dir(repo: Path, head: str) -> Path:
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / "tp-ci-junit" / head


def test_default_dir_receives_the_stage_junit(tmp_path):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    assert ci_gate_run.main(["--repo", str(repo), "--command", WRITE]) == 0
    d = _default_dir(repo, head)
    assert (d / "pytest-main.xml").exists()
    assert (d / "f8.xml").exists()
    assert ci_local_stamp.read_stamp(repo) is not None

    # From a linked worktree the junit must land under the COMMON git dir, not
    # the worktree's private git dir (`--git-dir` would tell them apart only here).
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
    _git(wt, "config", "user.email", "t18@test.local")
    _git(wt, "config", "user.name", "T18 Fixture")
    (wt / "y.txt").write_text("wt\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "wt commit")
    wt_head = _git(wt, "rev-parse", "HEAD")
    assert wt_head != head
    assert ci_gate_run.main(["--repo", str(wt), "--command", WRITE]) == 0
    d_wt = _default_dir(wt, wt_head)
    assert (d_wt / "pytest-main.xml").exists()
    assert (d_wt / "f8.xml").exists()
    gitdir = (repo / ".git").resolve()
    assert gitdir in d_wt.resolve().parents
    assert (gitdir / "worktrees") not in d_wt.resolve().parents


def test_explicit_manifest_dir_wins(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    mine = tmp_path / "mine"
    mine.mkdir()
    monkeypatch.setenv("CI_LOCAL_MANIFEST_DIR", str(mine))
    assert ci_gate_run.main(["--repo", str(repo), "--command", WRITE]) == 0
    assert (mine / "pytest-main.xml").exists()
    assert not _default_dir(repo, head).exists()


def test_no_junit_written_leaves_no_dir(tmp_path, capsys):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    assert ci_gate_run.main(["--repo", str(repo), "--command", "true"]) == 0
    d = _default_dir(repo, head)
    assert not d.exists()
    assert not d.parent.exists()
    assert capsys.readouterr().err == ""


def test_junit_dir_is_under_the_common_git_dir(tmp_path):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    assert ci_gate_run.junit_dir(repo, head) == _default_dir(repo, head)


def test_linked_worktree_uses_common_git_dir(tmp_path):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    got = ci_gate_run.junit_dir(wt, head)
    assert got == ci_gate_run.junit_dir(repo, head)
    gitdir = (repo / ".git").resolve()
    assert gitdir in got.resolve().parents
    assert (gitdir / "worktrees") not in got.resolve().parents


def test_old_head_dirs_are_pruned(tmp_path):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    parent = _default_dir(repo, head).parent
    parent.mkdir(parents=True)
    seeded = []
    for i in range(21):
        d = parent / f"old{i:02d}"
        d.mkdir()
        (d / "f.xml").write_text("<testsuite/>", encoding="utf-8")
        os.utime(d, (1_000_000 + i * 100, 1_000_000 + i * 100))
        seeded.append(d)
    assert ci_gate_run.main(["--repo", str(repo), "--command", WRITE]) == 0
    remaining = [p for p in parent.iterdir() if p.is_dir()]
    assert len(remaining) == 20, f"the newest 20 head dirs must stay, found {len(remaining)}"
    assert not seeded[0].exists(), "the oldest head dir must be pruned"
    assert not seeded[1].exists(), "the second-oldest head dir must be pruned"
    assert (_default_dir(repo, head) / "pytest-main.xml").exists()


def test_rerun_at_the_same_head_drops_stale_junit(tmp_path):
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    d = _default_dir(repo, head)
    d.mkdir(parents=True)
    (d / "stale.xml").write_text("<old/>", encoding="utf-8")
    (d / "pytest-main.xml").write_text("<old/>", encoding="utf-8")
    cmd = 'printf "<new/>" > "$CI_LOCAL_MANIFEST_DIR/pytest-main.xml"'
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert not (d / "stale.xml").exists()
    assert (d / "pytest-main.xml").read_text(encoding="utf-8") == "<new/>"


@pytest.mark.parametrize(
    "out",
    ["--path-format=absolute\n.git\n", "rel/.git\n"],
)
def test_junit_dir_refuses_anything_but_one_absolute_path(tmp_path, monkeypatch, out):
    """An old git echoing the flag, or printing a relative dir, is a refusal — not a path.

    Joining the two lines (or a relative dir) would send the junit somewhere
    meaningless; the caller catches the refusal and runs the gate with no junit.
    """
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(ci_gate_run.subprocess, "run", fake_run)
    with pytest.raises(ValueError):
        ci_gate_run.junit_dir(tmp_path, "abc")


@pytest.mark.parametrize("failure", ["rev-parse", "mkdir", "echoed-flag"])
def test_junit_setup_failure_skips_the_side_channel(tmp_path, monkeypatch, failure):
    """Junit is best effort: a failing git or mkdir must not stop the gate command."""
    repo = _make_repo(tmp_path)
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")

    def broken(_repo, _head):
        if failure == "rev-parse":
            raise subprocess.CalledProcessError(129, ["git", "rev-parse"])
        if failure == "echoed-flag":
            raise ValueError("two lines")  # `--path-format` echoed by an old git
        return blocker / "sub"  # mkdir under a regular file raises OSError

    monkeypatch.setattr(ci_gate_run, "junit_dir", broken)
    ran = tmp_path / "ran.txt"
    cmd = f'test -z "$CI_LOCAL_MANIFEST_DIR" && echo ok > "{ran}"'
    assert ci_gate_run.main(["--repo", str(repo), "--command", cmd]) == 0
    assert ran.exists()
    assert ci_local_stamp.read_stamp(repo) is not None
