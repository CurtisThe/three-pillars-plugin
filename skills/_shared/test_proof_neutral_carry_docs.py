"""Task 1.1: the docs-class commit classifier of proof_neutral_carry.

A single-parent commit is proof-neutral only when every changed path is a living-doc `.md` with
status M/A and a regular file mode; every other shape fails closed. The oracle is example-based:
each case builds a real commit in a throwaway git repo and reads the (ok, reason, lines) triple.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import proof_neutral_carry as pnc  # noqa: E402

IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
DOCS = "three-pillars-docs"
BASE_FILES = {
    f"{DOCS}/known_issues.md": "one\ntwo\nthree\n",
    f"{DOCS}/guide.md": "guide\n",
    f"{DOCS}/specs/a.md": "spec\n",
    f"{DOCS}/project-context.md": "ctx\n",
    "README.md": "readme\n",
    "LICENSE": "mit\n",
    "CLAUDE.md": "claude\n",
    "skills/tp-x/SKILL.md": "skill\n",
    "x.sh": "echo hi\n",
    "x.js": "let a = 1;\n",
    "x.ts": "let a: number = 1;\n",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def run_git(repo):
    def _run(args):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return (r.returncode, r.stdout, r.stderr)
    return _run


def write(repo, files):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def make_executable(repo, rel):
    git(repo, "update-index", "--chmod=+x", rel)


def commit(repo, msg="c", *extra):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", *extra, "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "core.fileMode", "false")  # the index mode is set by update-index
    write(tmp_path, BASE_FILES)
    commit(tmp_path, "base")
    return tmp_path


def classify(repo, mutate):
    """Run `mutate(repo)` on top of the base commit, then classify the new commit."""
    parent = git(repo, "rev-parse", "HEAD")
    mutate(repo)
    head = commit(repo)
    return pnc.is_proof_neutral_commit(run_git(repo), parent, head)


def test_constants_are_the_design_caps():
    assert (pnc.MAX_LINKS, pnc.MAX_LINES) == (4, 200)


def test_modified_living_doc_is_neutral_with_line_count(repo):
    ok, why, lines = classify(
        repo, lambda r: write(r, {f"{DOCS}/known_issues.md": "one\nTWO\nthree\nfour\n"}))
    assert ok, why
    assert lines == 3  # one deleted, two added


def test_added_design_note_is_neutral_with_line_count(repo):
    ok, why, lines = classify(
        repo, lambda r: write(r, {f"{DOCS}/tp-designs/x/notes.md": "a\nb\nc\nd\n"}))
    assert ok, why
    assert lines == 4


def test_modified_root_readme_is_neutral(repo):
    ok, why, lines = classify(repo, lambda r: write(r, {"README.md": "readme\nmore\n"}))
    assert ok, why
    assert lines == 1


def test_two_docs_in_one_commit_sum_their_lines(repo):
    ok, why, lines = classify(repo, lambda r: write(r, {
        f"{DOCS}/known_issues.md": "one\ntwo\nthree\nfour\n", "README.md": "readme\nmore\n"}))
    assert ok, why
    assert lines == 2


@pytest.mark.parametrize("path", [
    f"{DOCS}/specs/a.md", f"{DOCS}/project-context.md", "LICENSE", "CLAUDE.md",
    "skills/tp-x/SKILL.md"])
def test_excluded_paths_are_not_neutral(repo, path):
    ok, why, _ = classify(repo, lambda r: write(r, {path: "changed\n"}))
    assert not ok
    assert why


def test_added_file_under_specs_is_not_neutral(repo):
    ok, why, _ = classify(repo, lambda r: write(r, {f"{DOCS}/specs/new.md": "x\n"}))
    assert not ok
    assert why


def test_deleting_a_doc_is_not_neutral(repo):
    ok, why, _ = classify(repo, lambda r: (r / DOCS / "guide.md").unlink())
    assert not ok
    assert why


def test_renaming_a_doc_is_not_neutral(repo):
    ok, why, _ = classify(
        repo, lambda r: git(r, "mv", f"{DOCS}/guide.md", f"{DOCS}/guide-renamed.md"))
    assert not ok
    assert why


def test_chmod_on_a_doc_is_not_neutral(repo):
    ok, why, _ = classify(repo, lambda r: make_executable(r, f"{DOCS}/guide.md"))
    assert not ok
    assert why


def test_executable_doc_edit_is_not_neutral(repo):
    make_executable(repo, f"{DOCS}/guide.md")
    commit(repo, "make executable")
    ok, why, _ = classify(repo, lambda r: write(r, {f"{DOCS}/guide.md": "guide\nmore\n"}))
    assert not ok
    assert why


def test_symlink_doc_is_not_neutral(repo):
    ok, why, _ = classify(
        repo, lambda r: os.symlink("known_issues.md", r / DOCS / "link.md"))
    assert not ok
    assert why


@pytest.mark.parametrize("name", ["x.sh", "x.js", "x.ts"])
def test_comment_only_edit_in_other_languages_is_not_neutral(repo, name):
    marker = "#" if name == "x.sh" else "//"
    old = (repo / name).read_text(encoding="utf-8")
    ok, why, _ = classify(repo, lambda r: write(r, {name: f"{marker} a comment\n{old}"}))
    assert not ok
    assert why


def test_doc_plus_shell_script_in_one_commit_is_not_neutral(repo):
    ok, why, _ = classify(repo, lambda r: write(r, {
        "README.md": "readme\nmore\n", "x.sh": "echo hi\necho there\n"}))
    assert not ok
    assert why


def test_empty_commit_is_not_neutral(repo):
    parent = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "empty", "--allow-empty")
    ok, why, _ = pnc.is_proof_neutral_commit(run_git(repo), parent, head)
    assert not ok
    assert why


def test_diff_tree_failure_is_not_neutral_and_does_not_raise():
    def fake(args):
        return (1, "", "boom")
    ok, why, lines = pnc.is_proof_neutral_commit(fake, "p", "c")
    assert (ok, lines) == (False, 0)
    assert why


def test_raising_git_is_not_neutral_and_does_not_raise():
    def fake(args):
        raise RuntimeError("git exploded")
    ok, why, lines = pnc.is_proof_neutral_commit(fake, "p", "c")
    assert (ok, lines) == (False, 0)
    assert why.startswith("error:")


def test_unreadable_numstat_is_not_neutral(repo):
    real = run_git(repo)
    parent = git(repo, "rev-parse", "HEAD")
    write(repo, {"README.md": "readme\nmore\n"})
    head = commit(repo)

    def fake(args):
        if "--numstat" in args:
            return (1, "", "numstat failed")
        return real(args)

    ok, why, lines = pnc.is_proof_neutral_commit(fake, parent, head)
    assert (ok, lines) == (False, 0)
    assert why


def test_binary_numstat_row_is_not_neutral(repo):
    real = run_git(repo)
    parent = git(repo, "rev-parse", "HEAD")
    write(repo, {"README.md": "readme\nmore\n"})
    head = commit(repo)

    def fake(args):
        if "--numstat" in args:
            return (0, "-\t-\tREADME.md\n", "")
        return real(args)

    ok, why, _ = pnc.is_proof_neutral_commit(fake, parent, head)
    assert not ok
    assert why
