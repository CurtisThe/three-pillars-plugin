"""test_pending_conflicts.py — Task 1.6: validate and summary see the other pending fragments (B7).

design: living-doc-fragments, Task 1.6. Real temp git repos from test_docs_compile.py's helpers;
assertions are on problem membership and the presence of a reason line, not message wording.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import changes_fragment  # noqa: E402
import pending_changes  # noqa: E402
from test_docs_compile import frag, make_repo  # noqa: E402

SWAP = "\n## Roadmap\n\n### Current Focus\n- - focus one\n+ - {new}\n"


def _repo(tmp_path):
    return make_repo(tmp_path, {"a1": frag("a1", "2020-01-02", SWAP.format(new="first")),
                                "b2": frag("b2", "2020-01-03", SWAP.format(new="second"))})


def _problems(root, slug, with_root=True):
    path = root / "three-pillars-docs/changes" / f"{slug}.md"
    fragment = changes_fragment.parse(path.read_text(encoding="utf-8"), stem=slug)
    return changes_fragment.validate(fragment, repo_root=root if with_root else None)


def test_validate_with_root_folds_pending_first(tmp_path):
    root = _repo(tmp_path)
    assert _problems(root, "a1") == []
    problems = _problems(root, "b2")
    assert any(p.section == "Roadmap" and "focus one" in p.reason for p in problems)
    assert _problems(root, "b2", with_root=False) == []


def test_summary_shows_conflict_reason(tmp_path):
    root = _repo(tmp_path)
    lines = pending_changes.summary(root).splitlines()
    assert not any(ln.strip().startswith("conflict:") for ln in lines[: lines.index(next(l for l in lines if l.startswith("b2")))])
    after_b2 = lines[lines.index(next(l for l in lines if l.startswith("b2"))) + 1:]
    assert any(ln.strip().startswith("conflict:") and "focus one" in ln for ln in after_b2)
