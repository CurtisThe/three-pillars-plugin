"""PR #206 round 1 (test-quality): numbering rewrites placeholder citations across the WHOLE tree.

issue-id-placeholders.md promises "the numbering pass rewrites every occurrence of the
placeholder across the tree", but the CLI read only `three-pillars-docs/*.md`, so a citation in a
skill doc or CLAUDE.md kept the stale `M-new-x` after the heading was numbered (and `/tp-merge`'s
placeholder gate, which reads only the issue files, let it land). The carry certifier
(`numbering_carry`) must re-derive that wider plan too, or the numbering commit stops being a
certified link. Round 4: the base and merge-base reads cover the issue files HEAD lacks, so an
ID the base holds only in a `known_issues_resolved.md` created after the branch was cut is never
reissued. Real tmp repos only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import placeholder_gate  # noqa: E402
import task_scope  # noqa: E402
from base_sync_cert import _certify_link_unchecked  # noqa: E402
from task_scope import _git_env  # noqa: E402

CLI = str(Path(__file__).resolve().parent / "number_issues.py")
IDENT = {"GIT_AUTHOR_NAME": "f", "GIT_AUTHOR_EMAIL": "f@t",
         "GIT_COMMITTER_NAME": "f", "GIT_COMMITTER_EMAIL": "f@t"}
KI = "three-pillars-docs/known_issues.md"
KR = "three-pillars-docs/known_issues_resolved.md"
SKILL = "skills/tp-x/SKILL.md"
ROOT_DOC = "CLAUDE.md"


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch):
    for key in task_scope._GIT_LOCAL_ENV:       # the cert's default git seam reads os.environ
        monkeypatch.delenv(key, raising=False)


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], env=_git_env(**IDENT),
                          capture_output=True, text=True, check=True).stdout


def _put(repo, rel, s):
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(s, encoding="utf-8")


def _number(repo, cwd=None):
    return subprocess.run([sys.executable, CLI, "--repo", str(repo), "--base", "master",
                           "--commit"], env=_git_env(**IDENT), capture_output=True, text=True,
                          cwd=cwd)


def _scenario(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _put(repo, KI, "### M47: existing\n")
    _put(repo, SKILL, "x\n")
    _put(repo, ROOT_DOC, "root\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c0")
    _git(repo, "update-ref", "refs/remotes/origin/master", "master")
    _git(repo, "checkout", "-qb", "feature")
    _put(repo, KI, "### M47: existing\n\n### M-new-x: new\n")
    _put(repo, SKILL, "x (residual: M-new-x)\n")
    _put(repo, ROOT_DOC, "root, see M-new-x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "branch")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def test_numbering_rewrites_a_placeholder_cited_in_a_skill_doc(tmp_path):
    repo, _h0 = _scenario(tmp_path)
    done = _number(repo)
    assert done.returncode == 0, done.stderr
    assert "### M48: new" in _git(repo, "show", f"HEAD:{KI}")
    assert placeholder_gate.unnumbered_ids_at(repo, "HEAD") == []
    assert _git(repo, "show", f"HEAD:{SKILL}") == "x (residual: M48)\n"
    assert _git(repo, "show", f"HEAD:{ROOT_DOC}") == "root, see M48\n"


def test_scope_is_repo_wide_from_a_subdirectory_cwd(tmp_path):
    repo, _h0 = _scenario(tmp_path)
    done = _number(repo, cwd=str(repo / "skills"))
    assert done.returncode == 0, done.stderr
    assert _git(repo, "show", f"HEAD:{ROOT_DOC}") == "root, see M48\n"


def test_a_numbering_commit_rewriting_outside_the_docs_dir_is_a_certified_link(tmp_path):
    repo, h0 = _scenario(tmp_path)
    assert _number(repo).returncode == 0
    h1 = _git(repo, "rev-parse", "HEAD").strip()
    link = _certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert link.ok, link.reason


def test_a_subdirectory_repo_arg_writes_at_the_top_level(tmp_path):
    repo, h0 = _scenario(tmp_path)
    _put(repo, "skills/README.md", "unrelated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sub readme")
    done = subprocess.run([sys.executable, CLI, "--base", "master", "--commit"],
                          env=_git_env(**IDENT), capture_output=True, text=True,
                          cwd=str(repo / "skills"))
    assert done.returncode == 0, done.stderr
    assert _git(repo, "show", f"HEAD:{ROOT_DOC}") == "root, see M48\n"
    assert (repo / "skills/README.md").read_text(encoding="utf-8") == "unrelated\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_a_placeholder_cited_in_a_non_ascii_named_doc_is_rewritten(tmp_path):
    repo, _h = _scenario(tmp_path)
    name = "docs/r\u00e9sum\u00e9.md"
    _put(repo, name, "see M-new-x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "non-ascii doc")
    h0 = _git(repo, "rev-parse", "HEAD").strip()
    assert _number(repo).returncode == 0
    assert _git(repo, "show", f"HEAD:{name}") == "see M48\n"
    h1 = _git(repo, "rev-parse", "HEAD").strip()
    link = _certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert link.ok, link.reason


def test_an_id_held_only_in_a_base_side_issue_file_is_not_reissued(tmp_path):
    """The branch was cut before `known_issues_resolved.md` existed; the base then filed M51 and
    resolved it into that NEW file, so the base's `known_issues.md` still tops out at M50."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _put(repo, KI, "## Medium\n\n### M50: old\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c0")
    _git(repo, "checkout", "-qb", "feature")
    _put(repo, KI, "## Medium\n\n### M50: old\n\n### M-new-x: mine\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "branch")
    h0 = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "master")
    _put(repo, KI, "## Medium\n\n### M50: old\n\n### M51: theirs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base files M51")
    _put(repo, KI, "## Medium\n\n### M50: old\n")
    _put(repo, KR, "### M51 (RESOLVED 2026-10-02): theirs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base resolves M51 into a new resolved file")
    _git(repo, "update-ref", "refs/remotes/origin/master", "master")
    _git(repo, "checkout", "-q", "feature")
    done = _number(repo)
    assert done.returncode == 0, done.stderr
    numbered = _git(repo, "show", f"HEAD:{KI}")
    assert "### M52: mine" in numbered, numbered
    assert "### M51" not in numbered, "M51 reissued: the base holds it in its resolved file"
    h1 = _git(repo, "rev-parse", "HEAD").strip()
    link = _certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert link.ok, link.reason
