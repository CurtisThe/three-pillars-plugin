"""test_number_issues_inherited.py — the planner/gate contract for inherited placeholders.

design: number-issues-inherited-placeholder (PR #234 review round 1). A placeholder the
base has since numbered is left alone by the planner, so the `/tp-merge` placeholder gate
still sees it on head: the CLI must name it, and a base-sync must be what clears it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from task_scope import _git_env as clean_git_env  # noqa: E402

import number_issues as ni  # noqa: E402
import placeholder_gate as pg  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
KR = "three-pillars-docs/known_issues_resolved.md"
MODULE = Path(__file__).resolve().parent / "number_issues.py"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}
INHERITED = "### L183: a\n\n### L-new-x: inherited\n"
# The incident shape: the base numbered it and moved it to the resolved file.
BASE = {KI: "### L183: a\n", KR: "### L184 (RESOLVED): inherited\n"}


def test_every_key_the_planner_skips_is_reported_inherited():
    head = {KI: INHERITED + "\n### L-new-y: mine\n"}
    mb = {KI: INHERITED}
    plan = ni.plan_numbering(head, base=BASE, merge_base=mb)
    left = set(pg.unnumbered_ids({p: plan.get(p, t) for p, t in head.items()}))
    assert left == {"L-new-x"} == ni.inherited_numbered(head, BASE, mb)


def test_base_sync_clears_what_the_planner_left():
    # The merge takes the base's side of a placeholder head never touched.
    head = {KI: INHERITED}
    assert ni.plan_numbering(head, base=BASE, merge_base={KI: INHERITED}) == {}
    assert pg.unnumbered_ids(BASE) == []


def test_inherited_not_reported_when_base_still_heads_it():
    head = {KI: INHERITED}
    assert ni.inherited_numbered(head, head, head) == set()


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), env=clean_git_env(**_IDENTITY),
                          capture_output=True, text=True, check=True).stdout


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "master", cwd=repo)
    _write(repo, KI, INHERITED)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "file placeholder", cwd=repo)
    _git("branch", "feature", cwd=repo)
    for rel, text in BASE.items():
        _write(repo, rel, text)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "number and resolve L184", cwd=repo)
    _git("checkout", "-q", "feature", cwd=repo)
    return repo


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(MODULE), "--repo", str(repo), "--base", "master",
                           *extra], env=clean_git_env(**_IDENTITY), capture_output=True, text=True)


def test_cli_plan_names_inherited_keys(tmp_path):
    out = _run(_repo(tmp_path))
    assert out.returncode == 0
    assert json.loads(out.stdout) == {"assign": {}, "files": [], "inherited": ["L-new-x"]}


def test_cli_commit_points_at_base_sync(tmp_path):
    repo = _repo(tmp_path)
    head = _git("rev-parse", "HEAD", cwd=repo)
    out = _run(repo, "--commit")
    assert out.returncode == 0
    assert "L-new-x" in out.stderr and "/tp-merge-from-main" in out.stderr
    assert _git("rev-parse", "HEAD", cwd=repo) == head
