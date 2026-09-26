"""Round 22, T1 — the certifier does not certify an entry swallowed into the other side's HTML block.

Both branches append a dated log entry to the end of the living doc; the design branch's entry is
followed by a `<details>…</details>` block. A CommonMark HTML block runs until a blank line, so the
pre-fix keep-both merge put the base branch's bullet directly after `</details>`, where it renders
as literal text inside the block. Strict condition 5 reproduced those bytes (it re-runs the shared
byte path, `auto_safe_resolution.resolve_conflict_bytes`), and so did the carry lane's clean-merge
comparison. With the line-shape allowlist (`skills/tp-merge-from-main/scripts/line_shapes.py`) the
link fails strict certification and carries only as a HAND-resolution; with the allowlist lifted it
certifies (control).
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
    LIVING_DOC_PATH, build_scenario, diverge_living_doc, force_merge_commit,
)
from living_doc_carry import certify_link_carry  # noqa: E402

import classify  # noqa: E402 — on sys.path via auto_safe_resolution's shim

BASE_ENTRY = "- **2026-02-11** — base entry\n"
DESIGN_ENTRY = "- **2026-02-10** — design entry\n\n<details>\n<summary>n</summary>\n\nlong\n</details>\n"


def _swallowed_entry_link(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    doc = (s.origin_dir / LIVING_DOC_PATH).read_text(encoding="utf-8")
    diverge_living_doc(s, base_line=BASE_ENTRY, design_line=DESIGN_ENTRY)
    h0 = s.head()
    ours = s.git("show", f"{h0}:{LIVING_DOC_PATH}").stdout
    theirs = s.origin_git("show", f"{s.origin_head()}:{LIVING_DOC_PATH}").stdout
    assert resolve_conflict_bytes(base=doc, ours=ours, theirs=theirs)[0] != RESOLVED
    with monkeypatch.context() as m:
        m.setattr(classify, "keep_both_refusal", lambda side, entry: None)
        status, swallowed = resolve_conflict_bytes(base=doc, ours=ours, theirs=theirs)
    assert status == RESOLVED and swallowed.endswith("</details>\n" + BASE_ENTRY), swallowed
    return s, h0, force_merge_commit(s, {LIVING_DOC_PATH: swallowed})


def test_an_entry_swallowed_into_an_html_block_does_not_certify_as_mechanical(tmp_path, monkeypatch):
    s, h0, h1 = _swallowed_entry_link(tmp_path, monkeypatch)
    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is False
    assert strict.reason == "resolver could not deterministically reproduce a resolution"
    assert strict.conflicted_paths == (LIVING_DOC_PATH,)
    carry = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert carry.ok is True and carry.conflicted_paths == (LIVING_DOC_PATH,), carry


def test_control_with_the_allowlist_lifted_the_same_link_certifies_strictly(tmp_path, monkeypatch):
    s, h0, h1 = _swallowed_entry_link(tmp_path, monkeypatch)
    monkeypatch.setattr(classify, "keep_both_refusal", lambda side, entry: None)
    strict = _certify_link_unchecked(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert strict.ok is True, strict.reason
    assert certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref).conflicted_paths == ()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
