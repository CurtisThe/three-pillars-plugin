"""test_compile_publish_landed_numbering.py — a squash-landed compile PR that numbered an issue.

design: living-doc-fragments, Task 1.14 (landed-or-open). Review round 1 finding: after a squash
landing, the next publish must not renumber the branch's own copy of an issue the base now carries
(a false collision), so the next fragment still compiles. Helpers come from test_docs_compile_publish.py.
Oracle: example. Real temp repos; assertions read refs and file text.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

from test_docs_compile import CH, KI, frag, git  # noqa: E402
from test_docs_compile_publish import BRANCH, GAMMA, Forge, add_to_main, publish, with_origin  # noqa: E402


def _ok(cwd, *args) -> bool:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True).returncode == 0


def _squash_land(root):
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--squash", f"origin/{BRANCH}")
    git(root, "commit", "-q", "-m", "squash of the compile PR")
    git(root, "push", "-q", "origin", "main")


def test_squash_landed_compile_that_numbered_an_issue_still_compiles_the_next_fragment(tmp_path):
    add = "\n## Known issues — add\n\n### M-new-a: from alpha\nalpha body\n"
    root, bare, _ = with_origin(tmp_path, {"alpha": frag("alpha", "2020-01-02", add)})
    forge = Forge()
    publish(root, forge)
    assert "### M52: from alpha" in git(bare, "show", f"{BRANCH}:{KI}")
    _squash_land(root)
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    lines = publish(root, forge)
    assert not any("merge conflicts" in ln for ln in lines), lines
    ki = git(bare, "show", f"{BRANCH}:{KI}")
    assert ki.count("from alpha") == 1 and "### M52: from alpha" in ki, ki
    assert "gamma bullet" in git(bare, "show", f"{BRANCH}:three-pillars-docs/architecture.md")


def test_squash_landed_branch_restart_is_a_fast_forward_push(tmp_path):
    add = "\n## Known issues — add\n\n### M-new-a: from alpha\nalpha body\n"
    root, bare, _ = with_origin(tmp_path, {"alpha": frag("alpha", "2020-01-02", add)})
    forge = Forge()
    publish(root, forge)
    old_tip = git(bare, "rev-parse", BRANCH).strip()
    _squash_land(root)
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    publish(root, forge)
    new_tip = git(bare, "rev-parse", BRANCH).strip()
    assert new_tip != old_tip
    assert _ok(bare, "merge-base", "--is-ancestor", old_tip, new_tip)
    assert _ok(bare, "merge-base", "--is-ancestor", "main", new_tip)
    assert git(bare, "diff", "--name-only", "main", BRANCH, "--", KI).strip() == ""
