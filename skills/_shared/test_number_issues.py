"""test_number_issues.py — Task 1.1: number_issues.py placeholder numbering core + CLI.

design: basesync-autoresolve-coverage, Task 1.1.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from task_scope import _git_env as clean_git_env  # noqa: E402 — shipped scrub; git_env is dev-only

import number_issues as ni  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
KR = "three-pillars-docs/known_issues_resolved.md"
RM = "three-pillars-docs/product_roadmap.md"

MODULE = Path(__file__).resolve().parent / "number_issues.py"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}


# --- pure planner -----------------------------------------------------------

def test_placeholder_numbered_and_citation_rewritten():
    head = {
        KI: "### M47: existing\n\n### M-new-reset-not-runaway: x\n",
        KR: "### M48 (RESOLVED 2026-09-30): y\n",
        RM: "See M-new-reset-not-runaway for details.\n",
    }
    plan = ni.plan_numbering(head)
    assert plan == {
        KI: "### M47: existing\n\n### M49: x\n",
        RM: "See M49 for details.\n",
    }


def test_two_placeholders_numbered_in_file_order():
    head = {
        KI: "### M-new-aaa: a\n",
        KR: "### M-new-bbb: b\n",
    }
    plan = ni.plan_numbering(head)
    assert plan == {KI: "### M1: a\n", KR: "### M2: b\n"}


def test_cited_only_placeholder_left_untouched():
    head = {
        KI: "### M1: x\n",
        RM: "See M-new-orphan later.\n",
    }
    assert ni.plan_numbering(head) == {}


def test_base_headings_count_toward_next_free():
    head = {KI: "### M-new-a: z\n"}
    base = {KI: "### M49: existing in base\n"}
    plan = ni.plan_numbering(head, base=base)
    assert plan == {KI: "### M50: z\n"}


def test_collision_renumbers_only_heads_changed_files():
    unchanged = "three-pillars-docs/architecture.md"
    merge_base = {KI: "### M47: old\n", unchanged: "an older M49 mention.\n"}
    head = {
        KI: "### M47: old\n\n### M49: head added\n",
        RM: "cites M49 somewhere.\n",
        unchanged: "an older M49 mention.\n",
    }
    base = {KI: "### M47: old\n\n### M49: base added\n"}
    plan = ni.plan_numbering(head, base=base, merge_base=merge_base)
    assert plan == {
        KI: "### M47: old\n\n### M50: head added\n",
        RM: "cites M50 somewhere.\n",
    }
    assert unchanged not in plan  # text equals merge_base: out of head's renumbering scope
    assert base[KI] == "### M47: old\n\n### M49: base added\n"


def test_planner_is_idempotent():
    head = {
        KI: "### M47: existing\n\n### M-new-reset-not-runaway: x\n",
        KR: "### M48 (RESOLVED 2026-09-30): y\n",
        RM: "See M-new-reset-not-runaway for details.\n",
    }
    plan = ni.plan_numbering(head)
    head2 = dict(head)
    head2.update(plan)
    assert ni.plan_numbering(head2) == {}


def test_no_known_issues_file_is_noop():
    head = {KR: "### M1: a\n"}
    assert ni.plan_numbering(head) == {}


def test_allocation_order_collision_before_placeholder():
    merge_base = {KI: "### M30: existing\n"}
    head = {KI: "### M30: existing\n\n### M49: head collided\n\n### M-new-a: ph\n"}
    base = {KI: "### M30: existing\n\n### M49: base collided\n"}
    plan = ni.plan_numbering(head, base=base, merge_base=merge_base)
    assert plan == {
        KI: "### M30: existing\n\n### M50: head collided\n\n### M51: ph\n",
    }


def test_inherited_placeholder_numbered_by_base_is_skipped():
    # The base owns a placeholder already headed at the merge-base: it numbers it (L184) and
    # the merge brings that number in. Numbering it here too would mint a colliding L185.
    inherited = "### L183: a\n\n### L-new-x: inherited\n"
    plan = ni.plan_numbering({KI: inherited}, base={KI: "### L183: a\n\n### L184: inherited\n"},
                             merge_base={KI: inherited})
    assert plan == {}


def test_only_branch_introduced_placeholder_is_numbered():
    inherited = "### L183: a\n\n### L-new-x: inherited\n"
    head = {KI: inherited + "\n### L-new-y: mine\n", RM: "See L-new-x and L-new-y.\n"}
    plan = ni.plan_numbering(head, base={KI: "### L183: a\n\n### L184: inherited\n"},
                             merge_base={KI: inherited})
    assert plan == {
        KI: inherited + "\n### L185: mine\n",
        RM: "See L-new-x and L185.\n",
    }


def test_inherited_placeholder_still_unnumbered_at_base_is_numbered():
    # Stacked tp/A -> tp/B, or a placeholder that slipped onto master: the base still holds it
    # unchanged, so numbering it here merges cleanly and keeps the /tp-merge gate satisfiable.
    inherited = "### L183: a\n\n### L-new-x: inherited\n"
    plan = ni.plan_numbering({KI: inherited}, base={KI: inherited}, merge_base={KI: inherited})
    assert plan == {KI: "### L183: a\n\n### L184: inherited\n"}


def test_inherited_placeholder_moved_between_issue_files_stays_inherited():
    mb = {KI: "### L183: a\n\n### L-new-x: inherited\n"}
    head = {KI: "### L183: a\n", KR: "### L-new-x (RESOLVED): inherited\n"}
    base = {KI: "### L183: a\n", KR: "### L184 (RESOLVED): inherited\n"}
    assert ni.plan_numbering(head, base=base, merge_base=mb) == {}


# --- CLI ---------------------------------------------------------------------

def _git(*args: str, cwd: Path) -> str:
    env = clean_git_env(**_IDENTITY)
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=True).stdout


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_cli(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    env = clean_git_env(**_IDENTITY)
    return subprocess.run(
        [sys.executable, str(MODULE), "--repo", str(repo), *extra],
        env=env, capture_output=True, text=True)


def _repo_with_feature_branch(tmp_path: Path, name: str, base_text: str, head_text: str) -> Path:
    """``master`` holds ``base_text``; a ``feature`` branch (checked out) adds ``head_text``."""
    repo = tmp_path / name
    repo.mkdir()
    _git("init", "-q", "-b", "master", cwd=repo)
    _write(repo, KI, base_text)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _write(repo, KI, head_text)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "add placeholder", cwd=repo)
    return repo


def test_cli_commit_then_second_run_is_noop(tmp_path):
    repo = _repo_with_feature_branch(
        tmp_path, "repo1", "### M1: a\n", "### M1: a\n\n### M-new-y: b\n")
    base_sha = _git("rev-parse", "master", cwd=repo).strip()

    result = _run_cli(repo, "--base", "master", "--commit")
    assert result.returncode == 0, result.stderr
    assert (repo / KI).read_text(encoding="utf-8") == "### M1: a\n\n### M2: b\n"
    log = _git("log", "-1", "--format=%s%n%b", cwd=repo)
    lines = log.splitlines()
    assert lines[0] == "chore(ids): number issue IDs"
    assert f"Numbered-against: {base_sha}" in log
    commit_count = len(_git("log", "--format=%H", cwd=repo).splitlines())

    result2 = _run_cli(repo, "--base", "master", "--commit")
    assert result2.returncode == 0, result2.stderr
    commit_count2 = len(_git("log", "--format=%H", cwd=repo).splitlines())
    assert commit_count2 == commit_count


def test_cli_dirty_same_file_blocks_and_changes_nothing(tmp_path):
    repo = _repo_with_feature_branch(
        tmp_path, "repo2", "### M1: a\n", "### M1: a\n\n### M-new-y: b\n")
    dirty_text = "### M1: a\n\n### M-new-y: b\n\nunstaged note\n"
    _write(repo, KI, dirty_text)

    result = _run_cli(repo, "--base", "master", "--commit")
    assert result.returncode == 3
    assert "dirty" in result.stderr.lower()
    assert (repo / KI).read_text(encoding="utf-8") == dirty_text
    assert len(_git("log", "--format=%H", cwd=repo).splitlines()) == 2


def test_cli_dirty_elsewhere_does_not_block(tmp_path):
    repo = _repo_with_feature_branch(
        tmp_path, "repo3", "### M1: a\n", "### M1: a\n\n### M-new-y: b\n")
    _write(repo, "README.md", "unstaged readme change\n")

    result = _run_cli(repo, "--base", "master", "--commit")
    assert result.returncode == 0, result.stderr
    assert (repo / KI).read_text(encoding="utf-8") == "### M1: a\n\n### M2: b\n"
    status = _git("status", "--porcelain", cwd=repo)
    assert "README.md" in status


def test_cli_plan_reads_committed_blob_not_worktree(tmp_path):
    repo = _repo_with_feature_branch(
        tmp_path, "repo4", "### M1: a\n", "### M1: a\n\n### M-new-z: q\n")
    _write(repo, KI, "### M1: a\n\n### M-new-z: q\n\n### M-new-extra: zz\n")

    result = _run_cli(repo, "--base", "master")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["assign"] == {"M-new-z": "M2"}
    assert plan["files"] == [KI]


def test_cli_unresolvable_base_exits_2(tmp_path):
    repo = tmp_path / "repo5"
    repo.mkdir()
    _git("init", "-q", "-b", "master", cwd=repo)
    _write(repo, KI, "### M1: a\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)

    result = _run_cli(repo, "--base", "does-not-exist")
    assert result.returncode == 2


def test_cli_prefers_origin_base_over_stale_local(tmp_path):
    """Local ``master`` lacks a teammate's M49; ``origin/master`` has it: placeholder gets M50."""
    repo = _repo_with_feature_branch(
        tmp_path, "repo6", "### M1: a\n", "### M1: a\n\n### M-new-y: b\n")
    _git("checkout", "-q", "master", cwd=repo)
    _write(repo, KI, "### M1: a\n\n### M49: teammate\n")
    _git("commit", "-q", "-am", "teammate lands M49", cwd=repo)
    _git("update-ref", "refs/remotes/origin/master", "HEAD", cwd=repo)
    origin_sha = _git("rev-parse", "HEAD", cwd=repo).strip()
    _git("reset", "-q", "--hard", "HEAD~1", cwd=repo)  # local master is now stale
    _git("checkout", "-q", "feature", cwd=repo)

    result = _run_cli(repo, "--base", "master")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["assign"] == {"M-new-y": "M50"}

    result = _run_cli(repo, "--base", "master", "--commit")
    assert result.returncode == 0, result.stderr
    assert f"Numbered-against: {origin_sha}" in _git("log", "-1", "--format=%b", cwd=repo)


def test_cli_failed_commit_exits_4_and_rolls_back(tmp_path):
    """A blocking pre-commit hook: one stderr line, exit 4, tree and index restored."""
    head_text = "### M1: a\n\n### M-new-y: b\n"
    repo = _repo_with_feature_branch(tmp_path, "repo7", "### M1: a\n", head_text)
    hooks = tmp_path / "hooks7"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho blocked by hook >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    _git("config", "core.hooksPath", str(hooks), cwd=repo)

    result = _run_cli(repo, "--base", "master", "--commit")
    assert result.returncode == 4
    assert "Traceback" not in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1
    assert result.stderr.startswith("number_issues: error: commit failed")
    assert (repo / KI).read_text(encoding="utf-8") == head_text
    assert _git("status", "--porcelain", cwd=repo).strip() == ""
    assert len(_git("log", "--format=%H", cwd=repo).splitlines()) == 2
