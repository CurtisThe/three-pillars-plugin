"""Pure-unit tests for `base_sync_cert.py`: config interpreters, `git_version_ok` (task 2.2),
and the `merge-tree -z` parser's fail-closed SHAPE invariant (task 2.3's corruption matrix).

No fixture repos here (see `test_base_sync_cert_link.py` for the real-git integration tests);
`run_git` is injected throughout, as the plan specifies for version-parse / git-error /
parser-corruption cases.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from base_sync_cert import (  # noqa: E402
    GIT_MIN_VERSION,
    _cond5_resolve,
    _parse_merge_tree_z,
    carry_enabled,
    carry_max_chain,
    git_version_ok,
)


def _fake_version(text):
    return lambda args: (0, text, "")


# ---- git_version_ok --------------------------------------------------------


def test_git_version_ok_below_floor_is_false():
    assert git_version_ok(run_git=_fake_version("git version 2.37.1\n")) is False


def test_git_version_ok_at_floor_is_true():
    assert git_version_ok(run_git=_fake_version("git version 2.38.0\n")) is True


def test_git_version_ok_above_floor_is_true():
    assert git_version_ok(run_git=_fake_version("git version 2.43.0\n")) is True


def test_git_version_ok_garbage_is_false():
    assert git_version_ok(run_git=_fake_version("not a version string\n")) is False


def test_git_version_ok_nonzero_rc_is_false():
    assert git_version_ok(run_git=lambda args: (1, "git version 2.43.0\n", "")) is False


def test_git_version_ok_raising_seam_is_false():
    def _boom(args):
        raise RuntimeError("boom")
    assert git_version_ok(run_git=_boom) is False


def test_git_version_ok_real_git_on_this_machine():
    # Sanity check against the actual installed binary (no injection).
    assert git_version_ok() is True
    assert GIT_MIN_VERSION == (2, 38)


# ---- carry_enabled (literal-True-only, the INVERSE of strict-default review.* readers) ----


def test_carry_enabled_literal_true():
    assert carry_enabled({"review": {"approval_survives_safe_base_sync": True}}) is True


def test_carry_enabled_absent_key_false():
    assert carry_enabled({"review": {}}) is False


def test_carry_enabled_absent_config_false():
    assert carry_enabled(None) is False
    assert carry_enabled({}) is False


def test_carry_enabled_truthy_nonbool_false():
    assert carry_enabled({"review": {"approval_survives_safe_base_sync": 1}}) is False
    assert carry_enabled({"review": {"approval_survives_safe_base_sync": "true"}}) is False


def test_carry_enabled_corrupt_review_false():
    assert carry_enabled({"review": "not-a-dict"}) is False
    assert carry_enabled({"review": None}) is False


def test_carry_enabled_explicit_false():
    assert carry_enabled({"review": {"approval_survives_safe_base_sync": False}}) is False


# ---- carry_max_chain (int, bool excluded, 1..20 else default 5) ----


def test_carry_max_chain_in_range():
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": 2}}) == 2
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": 20}}) == 20
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": 1}}) == 1


def test_carry_max_chain_out_of_range_defaults():
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": 0}}) == 5
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": 21}}) == 5
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": -1}}) == 5


def test_carry_max_chain_bool_excluded_defaults():
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": True}}) == 5
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": False}}) == 5


def test_carry_max_chain_non_int_defaults():
    assert carry_max_chain({"review": {"base_sync_carry_max_chain": "3"}}) == 5


def test_carry_max_chain_absent_defaults():
    assert carry_max_chain(None) == 5
    assert carry_max_chain({}) == 5


# ---- task 2.3: merge-tree -z parser corruption matrix ----------------------
# Every malformed shape must return None (the caller's fail-closed "merge-tree output shape
# unrecognized"); the parser never guesses. Happy-parse is covered by real-git fixtures in
# tasks 2.4/2.5.


def test_parse_happy_clean_no_conflicts():
    tree = "d" * 40
    assert _parse_merge_tree_z(f"{tree}\x00") == (tree, {})


def test_parse_happy_one_conflict_stanza():
    tree, oid = "d" * 40, "e" * 40
    parsed = _parse_merge_tree_z(f"{tree}\x00100644 {oid} 1\tpath\x00")
    assert parsed == (tree, {"path": {1: ("100644", oid)}})


def test_shape_truncated_stanza_no_tab():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 {'e' * 40}\x00") is None


def test_shape_stage_out_of_range():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 {'e' * 40} 4\tpath\x00") is None


def test_shape_non_integer_stage():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 {'e' * 40} x\tpath\x00") is None


def test_shape_missing_field():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 {'e' * 40}\tpath\x00") is None


def test_shape_malformed_mode():
    assert _parse_merge_tree_z(f"{'d' * 40}\x0010064 {'e' * 40} 1\tpath\x00") is None


def test_shape_malformed_oid():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 not-an-oid 1\tpath\x00") is None


def test_shape_undecodable_path():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 {'e' * 40} 1\t\udcff\x00") is None


def test_shape_trailing_garbage_no_final_nul():
    assert _parse_merge_tree_z(f"{'d' * 40}\x00100644 {'e' * 40} 1\tpath\x00GARBAGE") is None


def test_shape_missing_tree_oid():
    assert _parse_merge_tree_z("") is None


def test_shape_malformed_tree_oid():
    assert _parse_merge_tree_z("not-a-tree-oid\x00") is None


# ---- condition 5's mode-mismatch branch: real git mangles type-change conflict paths, so
# this is exercised directly (injected `git`), documented rationale in the docstring below ----


def test_cond5_mode_mismatch_is_non_content_conflict():
    """A same-path conflict where some stage's mode isn't 100644 must refuse as
    "non-content conflict". Real git renames a symlink-vs-regular type-change conflict onto a
    synthesized `~<oid>`-suffixed path (verified live), so this exact shape (all 3 stages
    present at the SAME literal path, one stage non-100644) cannot be constructed through a
    real merge without the allowlist's exact-path check intercepting it first at condition 3.
    Exercised directly against `_cond5_resolve` instead -- the missing-stage half of this same
    guard IS covered end-to-end on real git objects (a modify/delete conflict) in
    `test_base_sync_cert_link2.py`."""
    path = "three-pillars-docs/known_issues.md"
    conflicts = {path: {1: ("100644", "a" * 40), 2: ("120000", "b" * 40), 3: ("100644", "c" * 40)}}

    def fake_git(args):
        if args[0] == "ls-tree":
            return (0, f"100644 blob {'d' * 40}\t{path}\n", "")
        return (0, "", "")

    assert _cond5_resolve(fake_git, conflicts, "c" * 40) == "non-content conflict"
