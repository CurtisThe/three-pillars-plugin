"""Round 21, S1 — the certifier does not certify an inventory row moved out of its table.

Both branches append a row to a table that ends the living doc; the design branch also leaves a
blank line after its row. The pre-fix row merge put the base branch's row after that blank line,
outside the table, and strict condition 5 reproduced those bytes (it re-runs the shared byte path,
`auto_safe_resolution.resolve_conflict_bytes`), as did the carry lane's clean-merge comparison.
With the table-run refusal (`skills/tp-merge-from-main/scripts/table_run.py`) the link fails strict
certification and carries only as a HAND-resolution; with the refusal lifted it certifies (control).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402
from base_sync_cert import _certify_link_unchecked  # noqa: E402
from base_sync_repo import (  # noqa: E402
    LIVING_DOC_PATH, _write_and_commit, build_scenario, diverge_living_doc, force_merge_commit,
)
from living_doc_carry import certify_link_carry  # noqa: E402

import classify  # noqa: E402 — on sys.path via auto_safe_resolution's shim

TABLE = "\n| ID | Name | Status |\n| --- | --- | --- |\n| D11 | a | done |\n"
DESIGN_ROW, BASE_ROW = "| D12 | b | wip |\n\n", "| D13 | c | wip |\n"


def _moved_row_link(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    doc = (s.origin_dir / LIVING_DOC_PATH).read_text(encoding="utf-8") + TABLE
    _write_and_commit(s.origin_dir, LIVING_DOC_PATH, doc, "base: add a table")
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("merge", "--quiet", "--ff-only", f"origin/{s.base_ref}", check=True)
    diverge_living_doc(s, base_line=BASE_ROW, design_line=DESIGN_ROW)
    h0 = s.head()
    ours = s.git("show", f"{h0}:{LIVING_DOC_PATH}").stdout
    theirs = s.origin_git("show", f"{s.origin_head()}:{LIVING_DOC_PATH}").stdout
    assert resolve_conflict_bytes(base=doc, ours=ours, theirs=theirs)[0] != RESOLVED
    with monkeypatch.context() as m:
        m.setattr(classify, "table_run_refusal", lambda h: None)
        status, moved = resolve_conflict_bytes(base=doc, ours=ours, theirs=theirs)
    assert status == RESOLVED and moved.endswith(DESIGN_ROW + BASE_ROW), moved
    return s, h0, force_merge_commit(s, {LIVING_DOC_PATH: moved})


def test_a_row_merged_out_of_its_table_does_not_certify_as_mechanical(tmp_path, monkeypatch):
    s, h0, h1 = _moved_row_link(tmp_path, monkeypatch)
    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is False
    assert strict.reason == "resolver could not deterministically reproduce a resolution"
    assert strict.conflicted_paths == (LIVING_DOC_PATH,)
    carry = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert carry.ok is True and carry.conflicted_paths == (LIVING_DOC_PATH,), carry


def test_control_with_the_refusal_lifted_the_same_link_certifies_strictly(tmp_path, monkeypatch):
    s, h0, h1 = _moved_row_link(tmp_path, monkeypatch)
    monkeypatch.setattr(classify, "table_run_refusal", lambda h: None)
    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is True, strict.reason
    assert certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref).conflicted_paths == ()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
