"""test_docs_compile_conflicts.py — Task 1.6: each fragment folds atomically; a conflict is kept and named.

design: living-doc-fragments, Task 1.6 (§Interfaces: exit 4, B7). Real temp git repos built with the
helpers of test_docs_compile.py. Assertions compare tree contents, file presence and result fields,
never message wording (test-fragility.md §2).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
from test_docs_compile import CH, ROADMAP, frag, git, make_repo  # noqa: E402

SWAP = "\n## Roadmap\n\n### Current Focus\n- - focus one\n+ - {new}\n"
THIRD = frag("gamma", "2020-01-04", "\n## Architecture\n\n### Dist\n+ - gamma bullet\n")


def _swap(slug, date, new):
    return frag(slug, date, SWAP.format(new=new))


def _run(tmp_path, fragments, commit=True):
    root = make_repo(tmp_path, fragments)
    base = git(root, "rev-parse", "HEAD")
    return root, base, docs_compile.compile_all(root, base_ref=base, prs={}, commit=commit)


def test_two_fragments_replacing_one_line_keep_the_second(tmp_path):
    root, _, result = _run(tmp_path, {"a1": _swap("a1", "2020-01-02", "first"), "b2": _swap("b2", "2020-01-03", "second")})
    text = (root / ROADMAP).read_text(encoding="utf-8")
    assert "- first\n" in text and "- second\n" not in text and "- focus one\n" not in text
    assert result.folded == ["a1"] and [s for s, _ in result.conflicts] == ["b2"]
    assert not (root / CH / "a1.md").exists() and (root / CH / "b2.md").exists()


def test_invalid_fragment_is_kept_and_named(tmp_path):
    bad = frag("bad", "2020-01-02", "\n## Nonsense\n\nstuff\n")
    root, _, result = _run(tmp_path, {"bad": bad, "gamma": THIRD})
    assert result.folded == ["gamma"] and [s for s, _ in result.conflicts] == ["bad"]
    assert result.conflicts[0][1]
    assert (root / CH / "bad.md").read_text(encoding="utf-8") == bad


def test_exit_4_commits_the_rest_and_lists_conflicts_in_body(tmp_path, capsys):
    root = make_repo(tmp_path, {"a1": _swap("a1", "2020-01-02", "first"), "b2": _swap("b2", "2020-01-03", "second"),
                                "gamma": THIRD})
    base = git(root, "rev-parse", "HEAD")
    rc = docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root)])
    assert rc == 4
    assert git(root, "rev-list", "--count", f"{base}..HEAD") == "1"
    assert "b2" in git(root, "log", "-1", "--format=%b")
    assert [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("docs-compile: b2:")]
    assert not (root / CH / "gamma.md").exists() and (root / CH / "b2.md").exists()


def test_all_conflicting_is_exit_4_with_no_commit(tmp_path):
    root = make_repo(tmp_path, {"x1": _swap("x1", "2020-01-02", "x").replace("focus one", "nope"),
                                "y2": _swap("y2", "2020-01-03", "y").replace("focus one", "nada")})
    base = git(root, "rev-parse", "HEAD")
    assert docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root)]) == 4
    assert git(root, "rev-parse", "HEAD") == base and git(root, "status", "--porcelain") == ""


def test_next_compile_still_runs(tmp_path):
    root, base, first = _run(tmp_path, {"a1": _swap("a1", "2020-01-02", "first"), "b2": _swap("b2", "2020-01-03", "second")})
    assert [s for s, _ in first.conflicts] == ["b2"]
    (root / CH / "gamma.md").write_text(THIRD, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "land gamma")
    head = git(root, "rev-parse", "HEAD")
    again = docs_compile.compile_all(root, base_ref=head, prs={}, commit=True)
    assert again.folded == ["gamma"] and [s for s, _ in again.conflicts] == ["b2"]
    assert git(root, "rev-parse", "HEAD") != head
