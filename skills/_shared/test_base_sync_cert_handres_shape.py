"""Relaxed-path coverage for `_relaxed_resolve`'s defensive content-conflict guards (Tier-7
review finding 2). These security-relevant fail-closed branches confine the trust relaxation to
regular-file, all-stages-present, UTF-8-decodable content conflicts; their strict `_cond5_resolve`
twins are tested in `test_base_sync_cert_link2.py`, but the RELAXED `certify_link_carry` path had
no pin. Each drives `certify_link_carry` on a CARRY-SET path (so M1 + cond1-4 pass and the guard
under test is genuinely reached) and asserts the exact fail-closed reason — non-vacuous by the
reason string (an earlier refuse would report a different one).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from living_doc_carry import certify_link_carry  # noqa: E402
from base_sync_repo import (  # noqa: E402
    build_scenario,
    force_merge_commit,
    write_bytes_and_commit,
)

KI = "three-pillars-docs/known_issues.md"
ARCH = "three-pillars-docs/architecture.md"


# ---- SHAPE gate: a missing conflict stage (modify/delete) → non-content conflict ----


def test_handres_modify_delete_missing_stage_refuses(tmp_path):
    """A modify/delete conflict on a carry-set path (design DELETES, base MODIFIES) has a missing
    stage, so the all-3-stages SHAPE gate refuses. Twin of strict
    `test_base_sync_cert_link2.py::test_modify_delete_conflict_missing_stage_fails_condition5`."""
    s = build_scenario(tmp_path)   # KI is a carry-set path → M1 passes
    s.git("rm", "-q", KI, check=True)
    s.git("commit", "--quiet", "-m", "design: delete living doc", check=True)
    h0 = s.head()
    p = s.origin_dir / KI
    p.write_text(p.read_text(encoding="utf-8") + "### Z1: base modifies\n", encoding="utf-8")
    s.origin_git("add", "--", KI, check=True)
    s.origin_git("commit", "--quiet", "-m", "base: modify", check=True)
    h1 = force_merge_commit(s, {KI: "### Z1: base modifies\n"})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "non-content conflict"


# ---- MODE gate: a non-100644 stage mode (executable, 100755) → non-content conflict ----


def test_handres_non_regular_file_mode_refuses(tmp_path):
    """A content conflict on a carry-set path where a conflict STAGE carries a non-100644 mode
    (base side executable, 100755) → the PER-STAGE mode check refuses, confining the relaxation
    to regular-file content conflicts (the load-bearing `any(m != "100644" for m in stage_modes)`
    gate). The committed h1 blob is forced back to 100644 (via `git add --chmod=-x`), so
    `parsed[0] == "100644"` passes the first clause and the refusal MUST come from the per-stage
    clause — isolating exactly the clause this test claims to pin (r2 de-vacuous fix)."""
    s = build_scenario(tmp_path)
    # Establish ARCH as a regular file on the common base; fast-forward design onto it.
    (s.origin_dir / ARCH).parent.mkdir(parents=True, exist_ok=True)
    (s.origin_dir / ARCH).write_text("# Arch\n### Z0: seed\n### Z1: base seed\n", encoding="utf-8")
    s.origin_git("add", "--", ARCH)
    s.origin_git("commit", "--quiet", "-m", "base: seed arch")
    s.git("fetch", "--quiet", "origin", s.base_ref)
    s.git("merge", "--quiet", "--ff-only", f"origin/{s.base_ref}")
    # design: modify content (regular file, 100644).
    (s.repo_dir / ARCH).write_text("# Arch\n### Z0: seed\n### Z1: design change\n", encoding="utf-8")
    s.git("add", "--", ARCH)
    s.git("commit", "--quiet", "-m", "design: change arch")
    h0 = s.head()
    # base: modify content AND set the executable bit → the base conflict STAGE becomes 100755.
    (s.origin_dir / ARCH).write_text("# Arch\n### Z0: seed\n### Z1: base change\n", encoding="utf-8")
    s.origin_git("add", "--chmod=+x", "--", ARCH)
    s.origin_git("commit", "--quiet", "-m", "base: change arch + exec bit")
    assert s.origin_git("ls-files", "-s", "--", ARCH).stdout.startswith("100755"), (
        "fixture precondition: base side must record ARCH as executable (100755)"
    )
    # Merge + resolve, but FORCE the committed h1 blob back to 100644 (git add --chmod=-x) so the
    # h1-blob-mode first clause (parsed[0]) passes and ONLY the per-stage clause can refuse.
    s.git("fetch", "--quiet", "origin", s.base_ref)
    s.git("merge", "--no-commit", "--no-ff", f"origin/{s.base_ref}", check=False)
    (s.repo_dir / ARCH).write_text("# Arch\n### Z0: seed\n### Z1: resolved\n", encoding="utf-8")
    s.git("add", "--chmod=-x", "--", ARCH)
    s.git("commit", "--quiet", "-m", "test: forced merge resolution (committed blob 100644)")
    h1 = s.head()
    assert s.git("ls-tree", h1, "--", ARCH).stdout.startswith("100644"), (
        "fixture precondition: committed h1 blob must be 100644 so the first clause cannot fire"
    )

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "non-content conflict"


# ---- DECODE gate: a non-UTF-8 blob on a carry-set path → undecodable ----


def test_handres_undecodable_blob_refuses(tmp_path):
    """A non-UTF-8 blob on the design side of a carry-set path → strict cat-blob decode raises
    UnicodeDecodeError, caught as a fail-closed 'undecodable' refusal. Twin of strict
    `test_base_sync_cert_link2.py::test_undecodable_blob_fails_condition5`."""
    s = build_scenario(tmp_path)
    write_bytes_and_commit(s.repo_dir, KI, b"\xff\xfe not valid utf8 \x80\x81\n",
                           "design: invalid bytes")
    h0 = s.head()
    p = s.origin_dir / KI
    p.write_text(p.read_text(encoding="utf-8") + "### Z1: base modifies\n", encoding="utf-8")
    s.origin_git("add", "--", KI, check=True)
    s.origin_git("commit", "--quiet", "-m", "base: modify", check=True)
    h1 = force_merge_commit(s, {KI: "placeholder\n"})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "undecodable (non-UTF-8) blob content"
