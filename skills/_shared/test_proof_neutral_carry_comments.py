"""Task 1.2: the comment-only Python class of proof_neutral_carry.

`python_comment_only(before, after)` is a pure table: an existing `.py` file is neutral only
when its token stream (comments and non-logical newlines removed) is unchanged, both sides parse,
physical lines 1-2 are identical and no changed comment is a directive. The git-backed half builds
real commits in a throwaway repo and reads `is_proof_neutral_commit`. The oracle is example-based
(test-fragility.md section 3): each case is one concrete input with the spec's expected answer, and
the directive list is the spec's own closed table, not a heuristic over prose.
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
# Two neutral lines so a table case can edit a comment below the frozen lines 1-2.
PRE = "import os\nimport sys\n"
SHEBANG = "#!/usr/bin/env python3\n"

ACCEPTED = {
    "trailing comment edited": (PRE + "x = 1  # old\n", PRE + "x = 1  # new\n"),
    "full-line comment added": (PRE + "def f():\n    return 1\n",
                                PRE + "def f():\n    # explain\n    return 1\n"),
    "plain comment removed": (PRE + "x = 1  # old\ny = 2\n", PRE + "x = 1\ny = 2\n"),
    "prose comment reworded": (PRE + "# old\nx = 1\n", PRE + "# new prose comment\nx = 1\n"),
    "untouched directive beside an edited comment": (
        PRE + "a = 1  # noqa\nb = 2  # old\n", PRE + "a = 1  # noqa\nb = 2  # new\n"),
}

REJECTED = {
    "docstring edited": (PRE + 'def f():\n    """old doc"""\n    return 1\n',
                         PRE + 'def f():\n    """new doc"""\n    return 1\n'),
    "string literal edited": (PRE + 's = "old"\n', PRE + 's = "new"\n'),
    "code edited": (PRE + "x = 1\n", PRE + "x = 2\n"),
    "shebang changed": (SHEBANG + "x = 1\ny = 2\n", "#!/usr/bin/python3\nx = 1\ny = 2\n"),
    "plain comment inserted above the shebang": (SHEBANG + "x = 1\n", "# hi\n" + SHEBANG + "x = 1\n"),
    "plain comment edited on line 1": ("x = 1  # old\ny = 2\nz = 3\n", "x = 1  # new\ny = 2\nz = 3\n"),
    "plain comment edited on line 2": ("a = 0\nx = 1  # old\nz = 3\n", "a = 0\nx = 1  # new\nz = 3\n"),
    "noqa removed": (PRE + "x = 1  # noqa: E501\n", PRE + "x = 1\n"),
    "directive moved to another line": (PRE + "a = 1  # noqa\nb = 2\n", PRE + "a = 1\nb = 2  # noqa\n"),
    "unclosed paren on the after side": (PRE + "x = 1\n", PRE + "x = (1  # c\n"),
    "syntax error on the before side": (PRE + "x = = 1\n", PRE + "x = = 1  # c\n"),
}

# The spec's closed table of directive comments; adding any one is never neutral.
DIRECTIVES = [
    "# noqa: E501", "# nosec", "# type: ignore", "# pragma: no cover", "# pylint: disable=x",
    "# fmt: off", "# mypy: strict", "# -*- coding: latin-1 -*-", "# tp-allow-fragile: r",
    "# tp-allow-fail-open: r", "# isort: skip", "# pyright: ignore",
    # bare word forms the shape regex misses (no ':' or '='): only the subject's word list
    # catches these, so each is the one case resting on its word. "# nosec" above and these two
    # stay single (no "# nosec B101", no "# pragma no cover") so dropping a word fails one case.
    "# noqa", "# pragma",
    # coding cookies written with ':' or '=' (the shape regex also catches these two)
    "# coding=utf-8", "# coding: utf-8",
]


@pytest.mark.parametrize("name", ACCEPTED)
def test_comment_only_edit_is_neutral(name):
    ok, why = pnc.python_comment_only(*ACCEPTED[name])
    assert ok, why
    assert why == ""


@pytest.mark.parametrize("name", REJECTED)
def test_non_comment_or_unsafe_edit_is_not_neutral(name):
    ok, why = pnc.python_comment_only(*REJECTED[name])
    assert ok is False
    assert why


@pytest.mark.parametrize("directive", DIRECTIVES)
def test_adding_a_directive_is_not_neutral(directive):
    before = PRE + "x = 1\ny = 2\n"
    for after in (PRE + f"x = 1  {directive}\ny = 2\n",     # trailing
                  PRE + f"x = 1\n{directive}\ny = 2\n"):    # full-line
        ok, why = pnc.python_comment_only(before, after)
        assert ok is False, after
        assert why


def test_unusable_input_never_raises():
    for before, after in ((None, "x = 1\n"), ("x = 1\n", None), (b"x = 1\n", "x = 1\n"),
                          (PRE + "x = 1\x00\n", PRE + "x = 1\x00  # c\n")):
        ok, why = pnc.python_comment_only(before, after)
        assert ok is False
        assert why


# --- git-backed: is_proof_neutral_commit over real commits ------------------------------------

DOC = "three-pillars-docs/guide.md"
PY_BASE = PRE + "def f():\n    return 1  # old\n"
BASE_FILES = {
    "pkg/a.py": PY_BASE,
    "pkg/run.py": PRE + "def g():\n    return 2  # old\n",
    DOC: "guide\n",
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


def chmod(repo, rel, flag):
    git(repo, "update-index", f"--chmod={flag}", rel)


def commit(repo, msg="c"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "core.fileMode", "false")  # the index mode is set by update-index
    write(tmp_path, BASE_FILES)
    git(tmp_path, "add", "-A")
    chmod(tmp_path, "pkg/run.py", "+x")
    commit(tmp_path, "base")
    return tmp_path


def classify(repo, mutate, git_seam=None):
    """Run `mutate(repo)` on the base commit, then classify the new commit."""
    parent = git(repo, "rev-parse", "HEAD")
    mutate(repo)
    head = commit(repo)
    return pnc.is_proof_neutral_commit((git_seam or run_git)(repo), parent, head)


def edit_comment(r):
    write(r, {"pkg/a.py": PY_BASE.replace("# old", "# new")})


def test_comment_only_edit_of_an_existing_py_is_neutral(repo):
    ok, why, lines = classify(repo, edit_comment)
    assert ok, why
    assert lines == 2  # one deleted, one added


def test_comment_only_edit_of_an_executable_py_is_neutral(repo):
    ok, why, _ = classify(repo, lambda r: write(r, {"pkg/run.py": BASE_FILES["pkg/run.py"].replace(
        "# old", "# new")}))
    assert ok, why


def test_adding_a_new_py_is_not_neutral(repo):
    ok, why, lines = classify(repo, lambda r: write(r, {"pkg/b.py": PRE + "# only a comment\n"}))
    assert ok is False
    assert why
    assert lines == 0


@pytest.mark.parametrize("rel,flag", [("pkg/a.py", "+x"), ("pkg/run.py", "-x")])
def test_chmod_on_a_py_is_not_neutral(repo, rel, flag):
    ok, why, _ = classify(repo, lambda r: chmod(r, rel, flag))
    assert ok is False
    assert why


def test_deleting_a_py_is_not_neutral(repo):
    ok, why, _ = classify(repo, lambda r: (r / "pkg/a.py").unlink())
    assert ok is False
    assert why


@pytest.mark.parametrize("body", [
    "def f():\n    return 2  # old\n",           # code edit
    "def f():\n    return 1  # noqa\n",          # directive added
    "def f(:\n    return 1  # new\n",            # syntax error
])
def test_unsafe_py_edit_in_a_commit_is_not_neutral(repo, body):
    ok, why, _ = classify(repo, lambda r: write(r, {"pkg/a.py": PRE + body}))
    assert ok is False
    assert why


def test_doc_edit_plus_comment_only_py_edit_is_neutral(repo):
    def both(r):
        write(r, {DOC: "guide\nmore\n"})
        edit_comment(r)
    ok, why, lines = classify(repo, both)
    assert ok, why
    assert lines == 3  # doc: one added; py: one deleted + one added


def test_doc_edit_plus_unsafe_py_edit_is_not_neutral(repo):
    def both(r):
        write(r, {DOC: "guide\nmore\n", "pkg/a.py": PRE + "def f():\n    return 9  # old\n"})
    ok, why, _ = classify(repo, both)
    assert ok is False
    assert why


def _seam_failing_on_cat_file(fail):
    def make(repo):
        real = run_git(repo)

        def seam(args):
            if args and args[0] == "cat-file":
                return fail()
            return real(args)
        return seam
    return make


def test_unreadable_blob_is_not_neutral(repo):
    ok, why, lines = classify(repo, edit_comment, _seam_failing_on_cat_file(lambda: (1, "", "boom")))
    assert ok is False
    assert why
    assert lines == 0


def test_raising_blob_read_is_not_neutral_and_never_raises(repo):
    def boom():
        raise OSError("no git")
    ok, why, lines = classify(repo, edit_comment, _seam_failing_on_cat_file(boom))
    assert ok is False
    assert why
    assert lines == 0
