"""test_docs_compile_verify.py — Task 1.5: the zero-drop verify runs last and a refusal restores.

design: living-doc-fragments, Task 1.5 (§Interfaces steps 4-5). Real temp git repos; assertions are
exit codes, git state and exact text (Oracle: example), never message wording (test-fragility.md §2).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
import docs_fold  # noqa: E402
import history_rollover  # noqa: E402
from test_docs_compile import CH, KI, ROADMAP, frag, git, make_repo  # noqa: E402

RESOLVED = "three-pillars-docs/known_issues_resolved.md"
KI2 = ("# Known Issues\n\n## Critical / High\n\n## Medium\n\n### M34: resolve me\nbody34\n\n"
       "### M35: keep me\nbody35\n\n### M51: old\nbody\n\n## Low\n")
FOCUS = "\n## Roadmap\n\n### Current Focus\n+ - alpha focus\n"


def _run(root, base, capsys):
    rc = docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root), "--pr", "alpha=7"])
    return rc, capsys.readouterr().out


def _repo(tmp_path, body=FOCUS):
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", body)}, docs={KI: KI2})
    return root, git(root, "rev-parse", "HEAD")


def _assert_untouched(root, base):
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "rev-parse", "HEAD") == base
    assert (root / CH / "alpha.md").exists()


def test_a_dropped_entry_refuses_and_restores_the_tree(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)
    real = docs_fold.fold

    def lossy(docs, fragment, **kw):
        out = real(docs, fragment, **kw)
        docs = dict(out.docs)
        docs[KI] = docs[KI].replace("### M35: keep me\nbody35\n\n", "")
        return docs_fold.FoldResult(docs, out.directed)

    monkeypatch.setattr(docs_fold, "fold", lossy)
    rc, out = _run(root, base, capsys)
    assert rc == 1 and "keep me" in out
    _assert_untouched(root, base)


def test_directed_removals_are_not_drops(tmp_path, capsys):
    body = ("\n## Roadmap\n\n### Current Focus\n- - focus one\n+ - replaced focus\n"
            "\n### Roadmap History\n- - **2019-05-05** — older entry\n+ - **2019-05-05** — reworded entry\n")
    root, base = _repo(tmp_path, body)
    rc, _ = _run(root, base, capsys)
    assert rc == 0 and git(root, "rev-list", "--count", f"{base}..HEAD") == "1"
    text = (root / ROADMAP).read_text(encoding="utf-8")
    assert "- replaced focus\n" in text and "— reworded entry" in text and "older entry" not in text


def test_renumbered_placeholder_is_not_a_drop(tmp_path, capsys):
    root, base = _repo(tmp_path, "\n## Known issues — add\n\n### M-new-x: fresh title\nfresh body\n")
    rc, _ = _run(root, base, capsys)
    assert rc == 0 and git(root, "rev-list", "--count", f"{base}..HEAD") == "1"
    ki = (root / KI).read_text(encoding="utf-8")
    assert "### M52: fresh title\nfresh body\n" in ki and "M-new-x" not in ki


def test_resolve_move_is_not_a_drop(tmp_path, capsys):
    root, base = _repo(tmp_path, "\n## Known issues — resolve\n\n- M34: fixed\n")
    rc, _ = _run(root, base, capsys)
    assert rc == 0 and git(root, "rev-list", "--count", f"{base}..HEAD") == "1"
    assert "### M34" not in (root / KI).read_text(encoding="utf-8")
    assert "### M34 (RESOLVED 2020-01-02): resolve me\n" in (root / RESOLVED).read_text(encoding="utf-8")


def test_a_drop_by_close_or_rollover_is_caught(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)

    def lossy_roll(repo_root, rel):
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("- **2019-05-05** — older entry\n", ""), encoding="utf-8")

    monkeypatch.setattr(history_rollover, "roll", lossy_roll)
    rc, out = _run(root, base, capsys)
    assert rc == 1 and "older entry" in out
    _assert_untouched(root, base)
