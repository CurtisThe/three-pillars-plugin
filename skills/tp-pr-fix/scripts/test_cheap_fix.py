"""Tests for cheap_fix.py (+ its CLI) — the `pr_fix_reproducer` slot's eligibility, scope and adopt.

design: cheap-tier-offload (Task 6.3; slots doc §Phase 6). A tmp repo stands in for
the PR head checkout (the fix worktree); the reproducer is a `python -c` command that
passes only when `a.py` reads `fixed`; most tests pass a stub `test_argv` one-liner.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_fix  # noqa: E402
import cheap_fix_cli  # noqa: E402
import scratch_root  # noqa: E402

PY = sys.executable
GREEN = [PY, "-c", "raise SystemExit(0)"]
_IS_FIXED = ("import pathlib; text = pathlib.Path('a.py').read_text(encoding='utf-8'); "
             "raise SystemExit(0 if text == 'fixed' else 1)")


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _finding(**over) -> dict:
    base = {"verdict": "structural", "file": "a.py", "blocking": True,
            "reproducer": {"kind": "command", "argv": [PY, "-c", _IS_FIXED],
                           "expect": {"exit": 0}}}
    return {**base, **over}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "a.py").write_text("broken", encoding="utf-8")
    (root / "b.py").write_text("b", encoding="utf-8")
    (root / "test_old.py").write_text("def test_old():\n    pass\n", encoding="utf-8")
    (root / ".gitignore").write_text("/.tp-scratch/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _head(repo) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _gone(repo, path: Path) -> bool:
    return not path.exists() and str(path) not in _git(repo, "worktree", "list", "--porcelain")


# --- eligible ------------------------------------------------------------------------


def test_eligible_only_for_a_reproduced_structural_finding():
    rep = cheap_fix.REPRODUCED
    assert cheap_fix.eligible(_finding(), rep) is True
    assert cheap_fix.eligible(_finding(verdict="minor"), rep) is False
    assert cheap_fix.eligible(_finding(reproducer=None), rep) is False
    assert cheap_fix.eligible(_finding(reproducer={"kind": "test", "source": " "}), rep) is False
    assert cheap_fix.eligible(_finding(), "not-reproduced") is False
    assert cheap_fix.eligible(_finding(), "inconclusive") is False
    assert cheap_fix.eligible(_finding(file=""), rep) is False
    assert cheap_fix.eligible(_finding(source="no-angles"), rep) is False


# --- scratch -------------------------------------------------------------------------


def test_scratch_is_a_detached_worktree_at_head_in_the_ignored_scratch_dir(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    try:
        assert _git(path, "rev-parse", "HEAD") == _head(repo)
        detached = subprocess.run(["git", "-C", str(path), "symbolic-ref", "-q", "HEAD"],
                                  capture_output=True)
        assert detached.returncode != 0
        # in-repo, so a project-scoped drafter can write there; gitignored, so the fix
        # worktree stays clean
        owner = path.resolve().parent
        assert owner.parent == (repo / ".tp-scratch").resolve()
        assert owner.name.startswith("cheap-fix-")
        assert str(path) in _git(repo, "worktree", "list", "--porcelain")
        assert _git(repo, "status", "--porcelain") == ""
    finally:
        cheap_fix.discard(path)
    assert _gone(repo, path) and not path.parent.exists()


def test_scratch_refuses_when_the_scratch_dir_is_not_ignored(repo, monkeypatch):
    # Task 3.7: `scratch` first calls `scratch_root.ensure_excluded` (fail-open), so a repo
    # with no ignore line still gets its scratch; the refusal needs that call to fail too.
    (repo / ".gitignore").unlink()
    _git(repo, "commit", "-q", "-am", "drop the ignore")
    monkeypatch.setattr(scratch_root, "ensure_excluded", lambda root: False)
    with pytest.raises(RuntimeError, match="not gitignored"):
        cheap_fix.scratch(repo, _head(repo))
    assert not (repo / ".tp-scratch").exists()


# --- adopt ---------------------------------------------------------------------------


def test_adopt_escalates_an_out_of_scope_file_and_removes_the_scratch(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    (path / "a.py").write_text("fixed", encoding="utf-8")
    (path / "b.py").write_text("changed", encoding="utf-8")
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["ok"] is False and v["action"] == "escalate"
    assert "b.py" in v["reason"]
    assert _gone(repo, path)
    assert _git(repo, "status", "--porcelain") == ""  # the fix worktree is untouched


@pytest.mark.parametrize("name, text", [("test_old.py", "def test_old():\n    assert 1\n"),
                                        ("conftest.py", "import pytest\n")])
def test_adopt_escalates_an_edit_to_an_existing_test_or_a_conftest(repo, name, text):
    path = cheap_fix.scratch(repo, _head(repo))
    (path / "a.py").write_text("fixed", encoding="utf-8")
    (path / name).write_text(text, encoding="utf-8")
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["action"] == "escalate" and name in v["reason"], v
    assert _gone(repo, path) and _git(repo, "status", "--porcelain") == ""


def test_adopt_escalates_when_the_reproducer_still_fails(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    (path / "a.py").write_text("still broken", encoding="utf-8")
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["ok"] is False and v["action"] == "escalate"
    assert v["oracle"] == "reproducer_fixed"
    assert _gone(repo, path)
    assert _git(repo, "status", "--porcelain") == ""


def test_adopt_escalates_when_the_tests_fail(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    (path / "a.py").write_text("fixed", encoding="utf-8")
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=[PY, "-c", "raise SystemExit(1)"])
    assert v["action"] == "escalate" and "test_argv exited 1" in v["reason"]
    assert _gone(repo, path) and _git(repo, "status", "--porcelain") == ""


def test_adopt_escalates_an_empty_diff(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["action"] == "escalate" and "no change" in v["reason"]
    assert _gone(repo, path)


def test_a_green_adopt_applies_exactly_one_diff(repo):
    head = _head(repo)
    path = cheap_fix.scratch(repo, head)
    (path / "a.py").write_text("fixed", encoding="utf-8")
    (path / "tests").mkdir()
    (path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["ok"] is True and v["action"] == "accept"
    assert v["files"] == ["a.py", "tests/test_a.py"]
    assert _gone(repo, path)
    # the diff is in the working tree only: no commit, nothing staged
    assert _head(repo) == head
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    status = sorted(_git(repo, "status", "--porcelain", "-uall").splitlines())
    assert status == ["?? tests/test_a.py", "M a.py"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "fixed"


# --- tests_argv ----------------------------------------------------------------------


def test_tests_argv_is_pytest_over_the_fixs_own_tests(tmp_path):
    base = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    (tmp_path / "pkg").mkdir()
    finding = _finding(file="pkg/mod.py")
    assert cheap_fix.tests_argv(finding, ["pkg/mod.py"], tmp_path) == base + ["pkg"]
    (tmp_path / "pkg" / "test_mod.py").write_text("", encoding="utf-8")
    assert cheap_fix.tests_argv(finding, ["pkg/mod.py"], tmp_path) == base + ["pkg/test_mod.py"]
    got = cheap_fix.tests_argv(finding, ["pkg/mod.py", "tests/test_new.py"], tmp_path)
    assert got == base + ["tests/test_new.py", "pkg/test_mod.py"]
    assert cheap_fix.tests_argv(_finding(), ["a.py"], tmp_path) == base + ["."]


def test_no_config_is_read_for_the_test_command():
    import inspect
    assert "load_repo_config" not in inspect.getsource(cheap_fix_cli)
    assert "gate_command" not in inspect.getsource(cheap_fix).replace(
        "never `ci.gate_command`", "")


# --- CLI (cheap_fix_cli.py) -----------------------------------------------------------------------------


def _cli(capsys, *argv) -> dict:
    assert cheap_fix_cli.main(list(argv)) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_adopt_never_runs_the_gate_command(repo, tmp_path, capsys):
    # a gate like ci-local.sh refuses a dirty tree, and the scratch is always dirty
    refuse_dirty = tmp_path / "refuse_dirty.py"
    refuse_dirty.write_text("import subprocess, sys\n"
                            "out = subprocess.run(['git', 'status', '--porcelain'],\n"
                            "                     capture_output=True).stdout\n"
                            "sys.exit(1 if out else 0)\n", encoding="utf-8")
    (repo / ".three-pillars").mkdir()
    (repo / ".three-pillars" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "ci": {"gate_command": f"{PY} {refuse_dirty}"}}),
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "config")
    finding = tmp_path / "finding.json"
    finding.write_text(json.dumps(_finding()), encoding="utf-8")
    out = _cli(capsys, "scratch", "--repo", str(repo), "--head", _head(repo),
               "--finding", str(finding))
    assert out["eligible"] is True
    path = Path(out["scratch"])
    (path / "a.py").write_text("fixed", encoding="utf-8")
    (path / "test_new.py").write_text("def test_new():\n    pass\n", encoding="utf-8")
    got = _cli(capsys, "adopt", "--scratch", str(path), "--fix-worktree", str(repo),
               "--finding", str(finding))
    assert got["action"] == "accept" and _gone(repo, path), got


def test_cli_scratch_refuses_a_finding_that_does_not_reproduce(repo, tmp_path, capsys):
    (repo / "a.py").write_text("fixed", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "already fixed")
    finding = tmp_path / "finding.json"
    finding.write_text(json.dumps(_finding()), encoding="utf-8")
    out = _cli(capsys, "scratch", "--repo", str(repo), "--head", _head(repo),
               "--finding", str(finding))
    assert out["eligible"] is False and out["scratch"] is None
    assert "not-reproduced" in out["reason"]
    assert _git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_cli_adopt_with_a_bad_finding_file_escalates(repo, tmp_path, capsys):
    path = cheap_fix.scratch(repo, _head(repo))
    got = _cli(capsys, "adopt", "--scratch", str(path), "--fix-worktree", str(repo),
               "--finding", str(tmp_path / "missing.json"))
    assert got["action"] == "escalate" and _gone(repo, path)
