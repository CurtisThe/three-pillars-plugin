"""test_docs_compile_basedups.py — fix.1: the duplicate-ID refusal fires only on NEW duplicates.

design: living-doc-fragments, fidelity-audit fix 1. A duplicate issue ID that already exists on
``base_ref`` must not block the compile (this repo's own docs hold some); a duplicate that appears after
``base_ref`` still refuses, restores the tree and commits nothing. Real temp git repos; assertions are
exit codes, git state and text (Oracle: example), never message wording.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
from test_docs_compile import CH, KI, frag, git, make_repo  # noqa: E402

BODY = "\n## Roadmap\n\n### Current Focus\n+ - alpha focus\n"
ONE_KI = "# Known Issues\n\n## Critical / High\n\n## Medium\n\n### M52: first\nbody\n\n## Low\n"
DUP_KI = ONE_KI.replace("## Low\n", "### M52: second\nbody\n\n## Low\n")


def test_base_duplicate_does_not_block_the_compile(tmp_path):
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", BODY)}, docs={KI: DUP_KI})
    base = git(root, "rev-parse", "HEAD")
    rc = docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root), "--pr", "alpha=7"])
    assert rc == 0
    assert git(root, "rev-parse", "HEAD") != base
    assert not (root / CH / "alpha.md").exists()


def test_duplicate_introduced_after_base_still_refuses(tmp_path, capsys):
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", BODY)}, docs={KI: ONE_KI})
    base = git(root, "rev-parse", "HEAD")
    (root / KI).write_text(DUP_KI, encoding="utf-8")
    git(root, "commit", "-q", "-am", "merge introduces a duplicate")
    head = git(root, "rev-parse", "HEAD")
    rc = docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root), "--pr", "alpha=7"])
    assert rc == 1 and "M52" in capsys.readouterr().out
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "rev-parse", "HEAD") == head
    assert (root / CH / "alpha.md").exists()
