"""Hermetic CLI tests for jdi_eligibility: `check` exits 0 / 1 / 2 and prints the line.

Every arm runs the module as a real subprocess (the entry point is `main`), so the
exit codes are the process's, not a return value. Fixture repos are tmp dirs with
GIT_* removed (the `rig` pattern in test_launch_design_run.py); identity goes
through `-c`. The last arm copies the module alone into a tmp dir and runs it with
`python3 -I`, where the hot_patch_check import fails.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent / "jdi_eligibility.py"

SCOPE_CLEAN = (
    "### In scope\n\n"
    "- `skills/foo/bar.py` (new)\n\n"
    "### Out of scope\n\n"
    "- nothing yet\n"
)


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(cwd), check=True, capture_output=True,
    )


def _rev(repo, ref):
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _commit(repo, paths: dict) -> str:
    for rel, body in paths.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "head", cwd=repo)
    return _rev(repo, "HEAD")


def _design(tmp_path) -> Path:
    d = tmp_path / "design"
    d.mkdir(exist_ok=True)
    (d / "design.md").write_text(
        "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
        "# fixture — design\n\n## Scope\n\n" + SCOPE_CLEAN + "\n"
        "## Behaviors\n\n1. It works.\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", cwd=r)
    _git("commit", "-q", "--allow-empty", "-m", "base", cwd=r)
    return r


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(MODULE), *args],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None,
    )


def _check_args(tmp_path, repo, base, head):
    return ("check", "--design-dir", str(_design(tmp_path)),
            "--base", base, "--head", head, "--repo", str(repo))


# --- exit 0: eligible -------------------------------------------------------


def test_check_prints_eligible_and_exits_0(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"src/a.py": "".join(f"x = {i}\n" for i in range(150))})
    out = _run(*_check_args(tmp_path, repo, base, head))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ELIGIBLE"


# --- exit 1: cap exceeded ---------------------------------------------------


def test_diff_cap_over_150_exits_1_naming_the_cap(tmp_path, repo):
    base = _rev(repo, "HEAD")
    head = _commit(repo, {"src/a.py": "".join(f"x = {i}\n" for i in range(151))})
    out = _run(*_check_args(tmp_path, repo, base, head))
    assert out.returncode == 1, out.stderr
    assert out.stdout.startswith("ESCALATE diff-cap")


# --- exit 2: bad input ------------------------------------------------------


def test_unresolvable_base_exits_2_as_bad_input(tmp_path, repo):
    head = _rev(repo, "HEAD")
    out = _run(*_check_args(tmp_path, repo, "definitely-not-a-ref", head))
    assert out.returncode == 2
    assert out.stdout.startswith("ESCALATE bad-input")


def test_missing_required_flag_exits_2(tmp_path, repo):
    base = _rev(repo, "HEAD")
    args = _check_args(tmp_path, repo, base, base)[:6]  # drop --head and its value
    out = _run(*args)
    assert out.returncode == 2
    assert "--head" in out.stderr


# --- exit 2: the module alone, with no importable hot_patch_check -----------


def test_standalone_copy_without_hot_patch_check_exits_2(tmp_path, repo):
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copyfile(MODULE, lone / "jdi_eligibility.py")
    base = _rev(repo, "HEAD")
    out = subprocess.run(
        [sys.executable, "-I", str(lone / "jdi_eligibility.py"), "check",
         "--design-dir", str(_design(tmp_path)),
         "--base", base, "--head", base, "--repo", str(repo)],
        capture_output=True, text=True,
    )
    assert out.returncode == 2, out.stderr
    assert out.stdout.startswith("ESCALATE bad-input")
