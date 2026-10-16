"""observed_red runs the scaffold from an in-tree copy (PR #209 review r1).

The scratch dir sits under the proof root, which in a linked worktree is
`<main>/.git/worktrees/<wt>/...`: a scaffold run from there takes pytest's
rootdir, ini and conftest chain from the MAIN checkout (another commit). The
oracle must judge the head tree, exactly as `reproduce._outcome_test` does.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_oracle  # noqa: E402
import cheap_oracle_run as cor  # noqa: E402

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
        "-c", "commit.gpgsign=false"]


def _git(cwd, *args) -> str:
    return subprocess.run([*_GIT, "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def test_observed_red_judges_the_head_tree_not_the_proof_roots_ancestor(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    (main / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (main / "pkgmod.py").write_text('VALUE = "main"\n', encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "pkgmod.py").write_text('VALUE = "head"\n', encoding="utf-8")
    _git(wt, "init", "-q")
    _git(wt, "add", ".")
    _git(wt, "commit", "-qm", "head")
    scratch = main / ".git" / "worktrees" / "x" / "review-proof" / "check"
    src = ("import pkgmod\n\ndef test_red():\n"
           "    assert pkgmod.VALUE != 'head'  # red on head by an assertion\n")
    v = cheap_oracle.check("repro_scaffold", {"source": src, "test_name": "test_red"},
                           {"cwd": str(wt), "head": _git(wt, "rev-parse", "HEAD"),
                            "scratch_dir": str(scratch)})
    assert v["ok"], v
    assert (scratch / "repro_scaffold.py").is_file()  # the audit copy stays in scratch
    assert not (wt / ".three-pillars").exists()  # the in-tree copy is removed


def test_observed_red_imports_the_head_tree_in_a_linked_worktree(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (main / "mod.py").write_text("X = 1\n", encoding="utf-8")
    _git(main, "add", ".")
    _git(main, "commit", "-qm", "base")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "tp/x", str(wt))
    (wt / "mod.py").write_text("X = 2\n", encoding="utf-8")  # the PR head changes X
    _git(wt, "commit", "-qam", "head")
    gitdir = Path(_git(wt, "rev-parse", "--absolute-git-dir"))
    scratch = gitdir / "three-pillars" / "review-proof" / "rounds" / "7" / "work" / "check"
    art = {"source": "import mod\ndef test_x():\n    assert mod.X == 1\n", "test_name": "test_x"}
    ok, why = cor.observed_red(art, {"cwd": str(wt), "head": _git(wt, "rev-parse", "HEAD"),
                                     "scratch_dir": str(scratch)})
    assert ok, f"the scaffold is red on head (X == 2) but the oracle said: {why}"
