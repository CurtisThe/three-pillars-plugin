"""Real-git integration tests for `certify_link` RME conditions 3-5 (task 2.5: allowlist,
containment, resolver re-run). Split from `test_base_sync_cert_link.py` per the plan's named
escape hatch to stay under the 300-line soft cap.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from base_sync_cert import certify_link  # noqa: E402
from base_sync_repo import (  # noqa: E402
    LIVING_DOC_PATH,
    OTHER_PATH,
    build_scenario,
    diverge_base_only,
    diverge_last_line,
    diverge_living_doc,
    force_merge_commit,
    make_certified_sync_merge,
    tamper_smuggle_edit,
    write_bytes_and_commit,
)


def _tree_of(scenario, commit_sha: str) -> str:
    r = subprocess.run(["git", "-C", str(scenario.repo_dir), "rev-parse", f"{commit_sha}^{{tree}}"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


# ============================================================
# Condition 3: allowlist
# ============================================================


def test_non_auto_safe_conflict_path_fails_condition3(tmp_path):
    s = build_scenario(tmp_path)
    diverge_last_line(s, OTHER_PATH, base_line="base other change\n", design_line="design other change\n")
    h0 = s.head()
    h1 = force_merge_commit(s, {OTHER_PATH: "design other change\n"})
    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "non-AUTO-SAFE conflict path"


# ============================================================
# Condition 4: byte-equality outside K (containment)
# ============================================================


def test_smuggled_edit_on_clean_merge_fails_condition4(tmp_path):
    """K=empty (clean recompute) requires h1's tree to equal the recomputed T EXACTLY -- any
    smuggled edit at all violates containment (changed ⊄ K=∅)."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tampered = tamper_smuggle_edit(s, h1, LIVING_DOC_PATH, "SMUGGLED\n")
    lc = certify_link(str(s.repo_dir), h0, tampered, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "change outside the conflicted region (condition 4)"


def test_smuggled_edit_outside_k_fails_condition4(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tampered = tamper_smuggle_edit(s, h1, OTHER_PATH, "SMUGGLED OTHER\n")
    lc = certify_link(str(s.repo_dir), h0, tampered, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "change outside the conflicted region (condition 4)"


# ============================================================
# Condition 5: resolver re-run inside K
# ============================================================


def test_modify_delete_conflict_missing_stage_fails_condition5(tmp_path):
    s = build_scenario(tmp_path)
    s.git("rm", "-q", LIVING_DOC_PATH, check=True)
    s.git("commit", "--quiet", "-m", "design: delete living doc", check=True)
    h0 = s.head()
    p = s.origin_dir / LIVING_DOC_PATH
    p.write_text(p.read_text(encoding="utf-8") + "### Z1: base modifies\n", encoding="utf-8")
    s.origin_git("add", "--", LIVING_DOC_PATH, check=True)
    s.origin_git("commit", "--quiet", "-m", "base: modify", check=True)
    h1 = force_merge_commit(s, {LIVING_DOC_PATH: "### Z1: base modifies\n"})
    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "non-content conflict"


def test_undecodable_blob_fails_condition5(tmp_path):
    s = build_scenario(tmp_path)
    write_bytes_and_commit(s.repo_dir, LIVING_DOC_PATH, b"\xff\xfe not valid utf8 \x80\x81\n",
                           "design: invalid bytes")
    h0 = s.head()
    p = s.origin_dir / LIVING_DOC_PATH
    p.write_text(p.read_text(encoding="utf-8") + "### Z1: base modifies\n", encoding="utf-8")
    s.origin_git("add", "--", LIVING_DOC_PATH, check=True)
    s.origin_git("commit", "--quiet", "-m", "base: modify", check=True)
    h1 = force_merge_commit(s, {LIVING_DOC_PATH: "placeholder\n"})
    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "undecodable (non-UTF-8) blob content"


def test_generic_prose_conflict_not_reproduced_fails_condition5(tmp_path):
    """A conflict the classifier calls SEMANTIC (no ID heading / table row / preamble
    signal) -> the shared resolver DEFERs -> condition 5 refuses before ever reaching the
    byte-equality check."""
    s = build_scenario(tmp_path)
    diverge_last_line(s, LIVING_DOC_PATH,
                      base_line="just some prose base change.\n",
                      design_line="just some prose design change.\n")
    h0 = s.head()
    h1 = force_merge_commit(s, {LIVING_DOC_PATH: "placeholder\n"})
    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "resolver could not deterministically reproduce a resolution"


def test_hand_tampered_resolution_fails_condition5_hash_mismatch(tmp_path):
    """The resolver reproduces byte-identical output on the happy path (see
    `test_base_sync_cert_link.py::test_happy_conflicted_certified_sync_merge`); appending ONE
    more hand-typed line inside K (the resolved path itself, still contained -- condition 4
    stays satisfied) must fail the final hash-object byte-equality check, not containment."""
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tampered = tamper_smuggle_edit(s, h1, LIVING_DOC_PATH, "HAND-TAMPERED EXTRA LINE\n")
    lc = certify_link(str(s.repo_dir), h0, tampered, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "resolved bytes do not match h1's committed blob"
