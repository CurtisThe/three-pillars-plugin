"""test_artifact_patch_delta.py — patch-overreach measurement (design: run-throughput).

Task 5.4: ``artifact_patch_delta.delta(path, base, cwd=None)`` reports
``{changed, total, ratio}`` for a working-tree file against commit ``base``:
``changed = max(added, deleted)`` from ``git diff --numstat``, ``total`` = the
base line count (the current line count when the file is missing at base, so a
brand-new file has ratio 1.0), ``ratio = round(changed / total, 4)``. The CLI
prints the dict as one JSON line and exits 0; usage/git errors exit 2 with a
stderr line. Git-touching cases build a real tmp repo with a scrubbed env (M23)
and never read the ambient repository.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from task_scope import _git_env as clean_git_env  # shipped scrub; git_env is dev-only

import artifact_patch_delta as apd

MODULE = Path(__file__).resolve().parent / "artifact_patch_delta.py"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}


def _git(*args: str, cwd: Path) -> str:
    env = clean_git_env(**_IDENTITY)
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=True).stdout


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_10(tmp_path: Path) -> tuple[Path, str]:
    """Tmp repo: one base commit holding ``doc.md`` with 10 lines."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, "doc.md", "".join(f"line {i}\n" for i in range(1, 11)))
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo).strip()


def test_in_place_edit_two_of_ten_is_exact(tmp_path):
    repo, base = _repo_10(tmp_path)
    lines = (repo / "doc.md").read_text(encoding="utf-8").splitlines(keepends=True)
    lines[3] = "line 4 edited\n"
    lines[6] = "line 7 edited\n"
    (repo / "doc.md").write_text("".join(lines), encoding="utf-8")
    assert apd.delta("doc.md", base, cwd=repo) == {
        "changed": 2, "total": 10, "ratio": 0.2}


def test_full_rewrite_flags_overreach(tmp_path):
    repo, base = _repo_10(tmp_path)
    (repo / "doc.md").write_text(
        "".join(f"brand new {i}\n" for i in range(10)), encoding="utf-8")
    d = apd.delta("doc.md", base, cwd=repo)
    assert d["changed"] == 10 and d["total"] == 10
    assert d["ratio"] > 0.5


def test_new_file_total_is_new_line_count(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, "seed.txt", "seed\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    base = _git("rev-parse", "HEAD", cwd=repo).strip()
    _write(repo, "fresh.md", "one\ntwo\nthree\nfour\nfive\n")
    _git("add", "fresh.md", cwd=repo)
    assert apd.delta("fresh.md", base, cwd=repo) == {
        "changed": 5, "total": 5, "ratio": 1.0}


def test_unchanged_file_is_zero_delta(tmp_path):
    repo, base = _repo_10(tmp_path)
    assert apd.delta("doc.md", base, cwd=repo) == {
        "changed": 0, "total": 10, "ratio": 0.0}


def test_cli_unchanged_file_exit_zero(tmp_path):
    repo, base = _repo_10(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(MODULE), "--path", "doc.md", "--base", base],
        cwd=str(repo), env=clean_git_env(**_IDENTITY),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"changed": 0, "total": 10, "ratio": 0.0}


def test_cli_prints_one_json_line_exit_zero(tmp_path):
    repo, base = _repo_10(tmp_path)
    lines = (repo / "doc.md").read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = "line 1 edited\n"
    (repo / "doc.md").write_text("".join(lines), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(MODULE), "--path", "doc.md", "--base", base],
        cwd=str(repo), env=clean_git_env(**_IDENTITY),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {"changed": 1, "total": 10, "ratio": 0.1}


def test_cli_bad_base_exits_2_with_stderr(tmp_path):
    repo, _ = _repo_10(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(MODULE), "--path", "doc.md", "--base", "deadbeef"],
        cwd=str(repo), env=clean_git_env(**_IDENTITY),
        capture_output=True, text=True)
    assert proc.returncode == 2
    assert proc.stderr.strip()
