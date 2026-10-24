"""test_docs_compile_publish_landing.py — Task 1.14: landed-or-open, numbering and compile exits.

design: living-doc-fragments, Task 1.14 (§Interfaces: the content test, number_issues before the base
merge, the ``--pr`` pairs, exit 1 and 4). Helpers come from test_docs_compile_publish.py.
Oracle: example. Real temp repos; assertions read refs, trees, recorded argv and file text.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

from test_docs_compile import ARCH, CH, KI, ROADMAP, TWO, frag, git, make_repo  # noqa: E402
from test_docs_compile_close import ARCHIVE, BODY, DESIGN, ROADMAP2  # noqa: E402
from test_docs_compile_publish import (BRANCH, GAMMA, Forge, Git, add_to_main, publish, tip,  # noqa: E402
                                        with_origin)
import docs_compile  # noqa: E402
from test_docs_compile_stable import DUP_KI  # noqa: E402
from test_docs_compile_conflicts import _swap  # noqa: E402


def _creates(forge):
    return [c for c in forge.calls if c[0] == "pr-create"]


def _landed(tmp_path, squash):
    """A first publish, then the branch lands on main (merge commit or one squash commit), plus gamma."""
    root, bare, _ = with_origin(tmp_path, TWO)
    forge = Forge()
    publish(root, forge)
    if squash:
        git(root, "fetch", "-q", "origin")
        git(root, "checkout", "-q", "main")
        git(root, "merge", "-q", "--squash", f"origin/{BRANCH}")
        git(root, "commit", "-q", "-m", "squash of the compile PR")
    else:
        git(root, "fetch", "-q", "origin")
        git(root, "checkout", "-q", "main")
        git(root, "merge", "-q", "--no-ff", "-m", "merge the compile PR", f"origin/{BRANCH}")
    git(root, "push", "-q", "origin", "main")
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    return root, bare, forge


def test_merge_commit_landing_opens_new_pr(tmp_path):
    root, bare, forge = _landed(tmp_path, squash=False)
    first = tip(bare)
    publish(root, forge)
    assert len(_creates(forge)) == 2 and tip(bare) != first
    assert subprocess.run(["git", "-C", str(bare), "merge-base", "--is-ancestor", first, BRANCH]).returncode == 0


def test_squash_landing_merges_cleanly_and_opens_new_pr(tmp_path):
    root, bare, forge = _landed(tmp_path, squash=True)
    first = tip(bare)
    assert subprocess.run(["git", "-C", str(bare), "merge-base", "--is-ancestor", first, "main"]).returncode != 0
    runner = Git()
    lines = publish(root, forge, runner=runner)
    assert len(_creates(forge)) == 2 and tip(bare) != first
    assert subprocess.run(["git", "-C", str(bare), "merge-base", "--is-ancestor", first, BRANCH]).returncode == 0
    assert not any("merge conflicts" in ln for ln in lines)
    assert git(bare, "ls-tree", "-r", "--name-only", BRANCH, "--", CH) == ""
    assert not [a for a in runner.argvs if "--force" in a]


def test_fragments_still_on_base_mean_pr_open(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    forge = Forge()
    publish(root, forge)
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    publish(root, forge)
    publish(root, forge)
    assert len(_creates(forge)) == 1


def test_branch_ids_renumbered_before_base_merge(tmp_path):
    add = "\n## Known issues — add\n\n### M-new-a: from the branch\nbranch body\n"
    root, bare, _ = with_origin(tmp_path, {"alpha": frag("alpha", "2020-01-02", add)})
    publish(root, Forge())
    assert "### M52: from the branch" in git(bare, "show", f"{BRANCH}:{KI}")
    base_ki = (root / KI).read_text(encoding="utf-8").rstrip("\n") + "\n\n### M52: minted on base\nbase body\n"
    add_to_main(root, {KI: base_ki, f"{CH}/gamma.md": GAMMA})
    lines = publish(root, Forge())
    assert not any("merge conflicts" in ln for ln in lines)
    merged = git(bare, "show", f"{BRANCH}:{KI}")
    assert "### M52: minted on base" in merged and "### M53: from the branch" in merged
    assert git(bare, "rev-list", "--count", "--merges", f"main..{BRANCH}") == "1"


def test_pr_pairs_reach_compile(tmp_path):
    root, bare, _ = with_origin(tmp_path, {"alpha": frag("alpha", "2020-01-02", BODY)},
                                docs={ROADMAP: ROADMAP2, DESIGN: "# alpha\n"})
    publish(root, Forge(), prs=("alpha=7",))
    row = [ln for ln in git(bare, "show", f"{BRANCH}:{ARCHIVE}").splitlines() if ln.startswith("| alpha ")]
    assert row and "Done — PR #7" in row[0]


def test_compile_exit_4_pushes_and_names_kept(tmp_path):
    frags = {"a1": _swap("a1", "2020-01-02", "first"), "b2": _swap("b2", "2020-01-03", "second"), "gamma": GAMMA}
    root, bare, _ = with_origin(tmp_path, frags)
    forge = Forge()
    lines = publish(root, forge)
    assert tip(bare) and len(_creates(forge)) == 1
    assert any("b2" in ln for ln in lines)
    assert git(bare, "ls-tree", "-r", "--name-only", BRANCH, "--", CH) == f"{CH}/b2.md"


def test_compile_exit_1_pushes_nothing(tmp_path, monkeypatch):
    body = "\n## Roadmap\n\n### Current Focus\n+ - alpha focus\n"
    root, bare, _ = with_origin(tmp_path, {"alpha": frag("alpha", "2020-01-02", body)}, docs={KI: DUP_KI})
    # a base-held duplicate no longer refuses (test_docs_compile_basedups.py); force a NEW one here
    monkeypatch.setattr(docs_compile, "_duplicate_ids", lambda root, base_ref=None: ["M52"])
    forge = Forge()
    lines = publish(root, forge)
    assert tip(bare) == "" and forge.calls == []
    assert any("M52" in ln for ln in lines)
