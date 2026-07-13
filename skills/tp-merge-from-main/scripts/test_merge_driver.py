"""Integration tests for the merge driver against real git repositories."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from merge_driver import merge_back  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
PRE = "*Last updated: {date}*\n\n# Known issues\n"


def git(repo, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=env)


def make_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    (repo / "three-pillars-docs").mkdir()
    return repo


def write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def setup_collision(tmp_path, bump_preamble: bool, ours_extra="", theirs_extra=""):
    """master + a design branch each add a colliding `### L4:` entry; optionally both bump preamble."""
    repo = make_repo(tmp_path)
    base = PRE.format(date="2026-05-01") + "\n### L1: base issue\nbody\n" + ours_extra + theirs_extra
    write(repo, KI, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    od = "2026-05-10" if bump_preamble else "2026-05-01"
    write(repo, KI, PRE.format(date=od) + "\n### L1: base issue\nbody\n"
          + ours_extra + "### L4: ours unique entry\nours body\n" + theirs_extra)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    td = "2026-05-12" if bump_preamble else "2026-05-01"
    write(repo, KI, PRE.format(date=td) + "\n### L1: base issue\nbody\n"
          + ours_extra + "### L4: theirs entry one\nt1\n### L5: theirs entry two\nt2\n" + theirs_extra)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def test_full_auto_resolve_when_only_mechanical(tmp_path):
    # No preamble bump -> the only conflict is the id-renumber hunk -> fully auto-resolved + staged.
    repo = setup_collision(tmp_path, bump_preamble=False)
    report = merge_back(str(repo), "master")
    assert not report.merged_clean
    assert KI in report.auto_resolved, report.to_json()
    assert KI not in report.deferred
    content = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" not in content                       # no markers left
    for needle in ["ours unique entry", "theirs entry one", "theirs entry two"]:
        assert needle in content                          # zero-drop
    # staged (index has no remaining unmerged entry for the file)
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert KI not in unmerged


def test_partial_resolution_when_preamble_also_conflicts(tmp_path):
    # Both bump preamble (semantic) AND collide on L4 (mechanical) -> partially-resolved.
    repo = setup_collision(tmp_path, bump_preamble=True)
    report = merge_back(str(repo), "master")
    assert KI in report.partially_resolved, report.to_json()
    assert report.needs_human
    content = (repo / KI).read_text(encoding="utf-8")
    # mechanical hunk pre-resolved (entries present, monotonic), semantic hunk left as markers
    for needle in ["ours unique entry", "theirs entry one", "theirs entry two"]:
        assert needle in content
    assert "Last updated" in content and "<<<<<<<" in content
    # NOT staged — markers remain
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert KI in unmerged


def test_non_living_doc_conflict_is_deferred(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "code.py", "x = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, "code.py", "x = 2\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, "code.py", "x = 3\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert "code.py" in report.deferred
    assert report.needs_human


def test_empty_but_present_file_is_not_misreported_as_add_delete(tmp_path):
    # Regression (Copilot #7): an empty-but-present living doc on both sides that conflicts must
    # NOT be deferred as an add/delete "missing side" — _stage_blob distinguishes "" from absent.
    from merge_driver import resolve_living_doc, _stage_blob
    repo = make_repo(tmp_path)
    write(repo, KI, "")                        # present but empty
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, "### L1: ours only\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, "### L1: theirs only\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)
    # base stage is the empty file: present, content "" — must be "" not None.
    assert _stage_blob(str(repo), 1, KI) == ""
    outcome = resolve_living_doc(str(repo), KI)
    assert "add/delete" not in outcome.reason   # not misreported as a missing-side conflict


def test_add_add_conflict_is_deferred_no_common_base(tmp_path):
    # Regression (Copilot round-2 #3): both branches CREATE the same living doc (no merge base for
    # it) -> must defer (no common base to anchor a structured merge), not auto-resolve.
    repo = make_repo(tmp_path)
    write(repo, "seed.md", "x\n")
    commit(repo, "base")                       # KI does not exist yet on the common base
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, PRE.format(date="2026-05-10") + "\n### L1: ours\n")
    commit(repo, "ours adds KI")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, PRE.format(date="2026-05-12") + "\n### L1: theirs\n")
    commit(repo, "theirs adds KI")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert KI in report.deferred, report.to_json()
    assert any("add/add" in o["reason"] for o in report.outcomes if o["path"] == KI)
    # nothing staged; markers remain for the human
    assert "<<<<<<<" in (repo / KI).read_text(encoding="utf-8")


def test_clean_merge_reports_no_conflict(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, KI, PRE.format(date="2026-05-01") + "\n### L1: a\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, "other.md", "design-only change\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, "unrelated.md", "master-only change\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    report = merge_back(str(repo), "master")
    assert report.merged_clean
    assert not report.needs_human
