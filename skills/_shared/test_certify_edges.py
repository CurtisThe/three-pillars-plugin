"""Edge pins for certify: setup ops never reach `.git`, and `--out` is written atomically.

design: audit-pass-does-not-bind (impl-audit F14; detailed-design.md §Interfaces, N13).
`certify._target` refuses any setup-op path that resolves into the pole tree's
`.git` (symlinks resolved) or out of the tree; `certify_cli.write_atomic` only
ever changes `--out` by one `os.replace` of a fully written temp file in the same
directory, so a failure leaves the old `--out` intact and no temp behind. Pure
filesystem tests: no git, no dev-only helper.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import certify
import certify_cli


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("op", [
    {"op": "write", "path": ".git/hooks/pre-commit", "content": "#!/bin/sh\n"},
    {"op": "replace", "path": "sub/../.git/config", "old": "[core]", "new": "[x]"},
    {"op": "delete", "path": ".git/config"},
    {"op": "delete", "path": ".git"},
    {"op": "write", "path": "../outside.txt", "content": "x"},
    {"op": "write", "path": ".", "content": "x"},
])
def test_setup_ops_never_reach_git_or_leave_the_tree(tree, op):
    before = sorted(p.relative_to(tree.parent) for p in tree.parent.rglob("*"))
    config = (tree / ".git" / "config").read_bytes()
    assert certify.apply_setup(tree, [op]) == f"path:{op['path']}"
    assert sorted(p.relative_to(tree.parent) for p in tree.parent.rglob("*")) == before
    assert (tree / ".git" / "config").read_bytes() == config


def test_a_symlink_into_git_is_refused(tree):
    (tree / "link").symlink_to(tree / ".git", target_is_directory=True)
    op = {"op": "write", "path": "link/hooks/post-checkout", "content": "#!/bin/sh\n"}
    assert certify.apply_setup(tree, [op]) == "path:link/hooks/post-checkout"
    assert not (tree / ".git" / "hooks" / "post-checkout").exists()


@pytest.mark.parametrize("rel", [".gitignore", "sub/.git-notes", "docs/.git.md"])
def test_git_lookalike_names_are_ordinary_paths(tree, rel):
    assert certify.apply_setup(tree, [{"op": "write", "path": rel, "content": "x\n"}]) is None
    assert (tree / rel).read_text(encoding="utf-8") == "x\n"


# --- write_atomic ---------------------------------------------------------------------
def _dir_names(path: Path) -> list[str]:
    return sorted(p.name for p in path.iterdir())


def test_write_atomic_replaces_once_with_a_complete_temp_in_the_same_dir(tmp_path, monkeypatch):
    out = tmp_path / "result.json"
    out.write_text("old\n", encoding="utf-8")
    real, seen = os.replace, []

    def spy(src, dst):
        seen.append((Path(src).parent, Path(src).read_text(encoding="utf-8"),
                     Path(dst).read_text(encoding="utf-8")))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    certify_cli.write_atomic(out, "new body\n")
    assert seen == [(tmp_path, "new body\n", "old\n")]
    assert out.read_text(encoding="utf-8") == "new body\n"
    assert _dir_names(tmp_path) == ["result.json"]


@pytest.mark.parametrize("fail", ["fsync", "replace"])
def test_write_atomic_failure_keeps_the_old_out_and_no_temp(tmp_path, monkeypatch, fail):
    out = tmp_path / "result.json"
    out.write_text("old\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, fail, boom)
    with pytest.raises(certify_cli.BadInput):  # T2: an OSError is bad input (exit 2)
        certify_cli.write_atomic(out, "new body\n")
    assert out.read_text(encoding="utf-8") == "old\n"
    assert _dir_names(tmp_path) == ["result.json"]


# --- r6: an unhashable claim / record id is bad input (exit 2), never a traceback ------- #
@pytest.mark.parametrize("bad", [["c1"], {"c": 1}])
def test_an_unhashable_claim_id_is_bad_input(bad):
    doc = {"disposition": "verdict",
           "claims": [{"id": bad, "guard": "g.sh", "property": "p", "parameters": []}]}
    with pytest.raises(ValueError):
        certify._entries(doc, {}, set(), name="verdict.claims.json", max_claims=25,
                         run=lambda claim, rec: {"id": claim["id"], "status": "binds"})


@pytest.mark.parametrize("bad", [["r1"], {"r": 1}])
def test_an_unhashable_record_id_is_bad_input(bad):
    with pytest.raises(ValueError):
        certify._records_by_id([{"id": "r0"}, {"id": bad}])
