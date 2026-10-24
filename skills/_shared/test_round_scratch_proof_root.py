"""round_scratch.py prepare --proof-root: the rename, the --root alias, the in-tree refusal.

design: run-tooling-footguns (Task 1.2, trap 2)

`prepare --root` named the proof root, not the repo root, and passing `.` wrote an untracked
`rounds/` into the worktree. The flag is now `--proof-root`; `--root` still works and prints one
deprecation line on stderr; a proof root inside the git working tree exits 2 with one JSON line
and writes nothing. The default root (under the git dir) and the root the repo config names
(`review.proof_dir`, resolved by `proof_root.py`) are not refused.

Stdlib and pytest only: it ships with `skills/`, so it imports no dev-only module.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tp-pr-iterate" / "scripts" / "round_scratch.py"
PR = "https://github.com/o/r/pull/42"


def _env():
    """The subprocess env, built per call: it carries the per-test contained `TMPDIR` the
    conftest fixture sets (a module-level snapshot would keep the session's, and `prepare`'s
    exec dirs would then land in the real system temp)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "TP_REVIEW_PROOF_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    return env


def _git(repo, *args):
    p = subprocess.run(["git", *args], cwd=str(repo), env=_env(), capture_output=True,
                       text=True, check=True)
    return p.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A real two-commit git repo; its work tree is `tmp_path/repo`."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    for name in ("a.txt", "b.txt"):
        (r / name).write_text(name + "\n", encoding="utf-8")
        _git(r, "add", name)
        _git(r, "commit", "-q", "-m", name)
    return r


def _prepare(repo, flag, root, tmp_path):
    args = [sys.executable, str(SCRIPT), "prepare", flag, str(root), "--pr-url", PR,
            "--base", _git(repo, "rev-parse", "HEAD~1"), "--head", _git(repo, "rev-parse", "HEAD"),
            "--state", str(tmp_path / "state.json"), "--log", str(tmp_path / "log.md"),
            "--rulings", "r.md"]
    return subprocess.run(args, cwd=str(repo), env=_env(), capture_output=True, text=True,
                          timeout=120)


def _deprecations(p):
    return [ln for ln in p.stderr.splitlines() if "deprecated" in ln]


def test_proof_root_flag_works_like_root_did(repo, tmp_path):
    proof = tmp_path / "proof"
    p = _prepare(repo, "--proof-root", proof, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    r = Path(p.stdout.strip())
    assert r == proof / "rounds" / "42" / "r1"
    manifest = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    assert manifest["paths"]["proof_root"] == str(proof)
    assert _deprecations(p) == []
    # The angles' exec dirs land in this test's contained temp dir, never the real system temp:
    # a run-dir-shaped session TMPDIR would send them to /tmp (run_scratch.outside_tmpdir), where
    # scratch_leftovers reports them at the next gate.
    contained = os.path.realpath(tempfile.gettempdir())
    for e in manifest["angles"]:
        assert os.path.realpath(e["exec_dir"]).startswith(contained + os.sep), e["exec_dir"]


def test_root_alias_still_works_and_warns_once(repo, tmp_path):
    proof = tmp_path / "proof"
    p = _prepare(repo, "--root", proof, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert Path(p.stdout.strip()) == proof / "rounds" / "42" / "r1"
    warned = _deprecations(p)
    assert len(warned) == 1
    assert "--root" in warned[0] and "--proof-root" in warned[0]


@pytest.mark.parametrize("flag", ["--proof-root", "--root"])
@pytest.mark.parametrize("inside", ["proof", "."])
def test_proof_root_inside_working_tree_is_refused_and_nothing_written(
        repo, tmp_path, flag, inside):
    p = _prepare(repo, flag, repo / inside, tmp_path)
    assert p.returncode == 2, p.stdout + p.stderr
    assert len(p.stdout.strip().splitlines()) == 1
    payload = json.loads(p.stdout)
    assert payload["terminal"] == "needs-human-attention"
    assert payload["reason"] == "prepare-refused"
    assert "working tree" in payload["detail"]
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert not (repo / "proof").exists() and not (repo / "rounds").exists()
    assert not (tmp_path / "state.json").exists() and not (tmp_path / "log.md").exists()


def test_default_root_under_the_git_dir_is_not_refused(repo, tmp_path):
    root = repo / ".git" / "three-pillars" / "review-proof"
    p = _prepare(repo, "--proof-root", root, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert Path(p.stdout.strip()) == root / "rounds" / "42" / "r1"


def test_root_named_by_the_repo_config_is_not_refused(repo, tmp_path):
    (repo / ".three-pillars").mkdir()
    (repo / ".three-pillars" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "review": {"proof_dir": ".three-pillars/review-proof"}}),
        encoding="utf-8")
    root = repo / ".three-pillars" / "review-proof"
    p = _prepare(repo, "--proof-root", root, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert Path(p.stdout.strip()) == root / "rounds" / "42" / "r1"


def test_help_says_proof_root_is_outside_the_working_tree():
    p = subprocess.run([sys.executable, str(SCRIPT), "prepare", "--help"], env=_env(),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    text = " ".join(p.stdout.split())
    assert "--proof-root" in text
    assert "outside the working tree" in text and "not the repo root" in text


def test_neither_flag_and_both_flags_are_usage_errors(repo, tmp_path):
    base = [sys.executable, str(SCRIPT), "prepare", "--pr-url", PR, "--base", "b", "--head", "h",
            "--state", str(tmp_path / "s.json"), "--log", str(tmp_path / "l.md")]
    for extra in ([], ["--proof-root", str(tmp_path / "a"), "--root", str(tmp_path / "b")]):
        p = subprocess.run(base + extra, cwd=str(repo), env=_env(), capture_output=True,
                           text=True, timeout=60)
        assert p.returncode == 2 and p.stdout == ""
        assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()
