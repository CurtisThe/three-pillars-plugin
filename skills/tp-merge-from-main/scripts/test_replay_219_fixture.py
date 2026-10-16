"""The #219 consumer-shape replay: the shipped driver, a real git merge, a slug-keyed roadmap.

Spec: basesync-three-way-verifier plan Task 6.1. The base branch moves a table row on (`Planned` ->
`Done`) and appends a row; the design branch appends a row of its own after the same base row. Git
conflicts, and the driver must resolve it in base-branch-first row order, with nothing left behind.
Rule: skills/_shared/test-fragility.md (the merged file and the report; the counterfactual
monkeypatches the resolver table the driver reads, so the test is not vacuous).
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import resolvers  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only

PRM = "three-pillars-docs/product_roadmap.md"
HEAD = "# Roadmap\n\n| Slug | Note | Status |\n| --- | --- | --- |\n"
R = "| `ci-settle-statuscontext` | settle the status context | Planned |"
R2 = R.replace("Planned", "Done")
X = "| `ours-new` | the design branch's row | Planned |"
Y = "| `theirs-new` | the base branch's row | Planned |"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=clean_git_env(**IDENT))


def commit_roadmap(repo, rows, msg):
    path = repo / PRM
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEAD + "\n".join(rows) + "\n", encoding="utf-8")
    git(repo, "add", PRM)
    git(repo, "commit", "-q", "-m", msg)


def make_219_repo(tmp_path):
    """master: R -> (R2, Y). design: R -> (R, X). The merge of master into design conflicts."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    commit_roadmap(repo, [R], "base")
    git(repo, "checkout", "-q", "-b", "design")
    commit_roadmap(repo, [R, X], "design adds a row")
    git(repo, "checkout", "-q", "master")
    commit_roadmap(repo, [R2, Y], "master marks R done and adds a row")
    git(repo, "checkout", "-q", "design")
    return repo


def rows_of(text):
    return [ln for ln in text.splitlines() if ln.startswith("| `")]


def test_the_driver_auto_resolves_the_219_roadmap_sync_base_branch_first(tmp_path):
    repo = make_219_repo(tmp_path)
    report = merge_back(str(repo), "master")
    assert PRM in report.auto_resolved, report.to_json()
    assert PRM not in report.deferred and not report.needs_human, report.to_json()
    text = (repo / PRM).read_text(encoding="utf-8")
    assert rows_of(text) == [R2, Y, X]
    assert text.startswith(HEAD)
    assert not any(m in text for m in ("<<<<<<<", "|||||||", "=======", ">>>>>>>"))
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert PRM not in unmerged


def test_without_the_shaped_class_the_same_sync_defers(tmp_path, monkeypatch):
    monkeypatch.delitem(resolvers.MECH_RESOLVERS, "shaped-line-merge")
    repo = make_219_repo(tmp_path)
    report = merge_back(str(repo), "master")
    assert PRM not in report.auto_resolved, report.to_json()
    assert PRM in report.deferred and report.needs_human, report.to_json()
