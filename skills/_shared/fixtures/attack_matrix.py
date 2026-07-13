"""attack_matrix.py -- shared Phase 4-5 attack-scenario builder for the approval/proof
carry consumer property tests (tasks 6.4 / 7.2: "every attack fixture -> INDETERMINATE,
never FAIL/PASS").

Each case reproduces (compactly) one Phase-4/5 adversarial fixture from
`test_base_sync_cert_attacks(2).py` / `test_base_sync_cert_chain(2).py`, seats the oracle
on the scenario's own base line (the case-14 `_seat_oracle_on_base` shape) so every case
is non-vacuous, and returns `(scenario, head_oid, anchor)` so BOTH gate consumers can be
driven through the SAME tampered head under IDENTICAL config.

Public surface (iteration-speed split):
  * `ATTACK_CASE_NAMES` -- static ordered list of the 11 case names.
  * `build_attack_case(name, tmp_path, monkeypatch) -> (scenario, head_oid, anchor)` --
    build EXACTLY one case; re-arms the oracle seam for that case. Parametrize over
    `ATTACK_CASE_NAMES` so each attack case is its own pytest item (per-item `tmp_path`/
    `monkeypatch` isolation is strictly MORE correct than the old shared-generator sweep).
  * `iter_attack_cases(tmp_path, monkeypatch)` -- thin back-compat loop yielding
    `(name, scenario, head_oid, anchor)`; callers must drive case N BEFORE consuming N+1
    (each case's `scenario.repo_dir` is only the active oracle target for its own turn).

`CARRY_CONFIG` pins `base_sync_carry_max_chain=2` so case 7 (chain over cap) refuses
without needing to build a 5+-link chain; no other case's chain is long enough for the
cap to matter, so this is a safe shared constant.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import base_sync_oracle  # noqa: E402
from base_sync_repo import (  # noqa: E402
    LIVING_DOC_PATH,
    build_scenario,
    break_remote,
    craft_merge_with_parents,
    diverge_base_only,
    diverge_living_doc,
    force_merge_commit,
    make_certified_sync_merge,
    rewrite_origin_base,
    tamper_smuggle_edit,
)

CARRY_CONFIG = {
    "review": {"approval_survives_safe_base_sync": True, "base_sync_carry_max_chain": 2},
}


def _subdir(tmp_path, name: str) -> Path:
    """`build_scenario` runs `git -C <root> clone ...` immediately, so `<root>` must
    already EXIST. Each case gets its OWN fresh subdirectory so the back-compat loop
    (all cases share one `tmp_path`) never collides on a scenario root."""
    d = Path(tmp_path) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tree_of(scenario, commit_sha: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(scenario.repo_dir), "rev-parse", f"{commit_sha}^{{tree}}"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _seat(scenario, monkeypatch) -> None:
    """Case-14 shape -- see `test_base_sync_cert_attacks.py::_seat_oracle_on_base`."""
    scenario.git("fetch", "--quiet", "origin", scenario.base_ref, check=True)
    scenario.git("checkout", "--quiet", "-B", scenario.base_ref,
                 f"origin/{scenario.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: scenario.repo_dir)


# ---------------------------------------------------------------------------
# Per-case builders. Each returns (scenario, head_oid, anchor) and re-arms the
# oracle seam (via `_seat`) for its own scenario.repo_dir.
# ---------------------------------------------------------------------------

def _case_attack1_smuggled_hunk(tmp_path, monkeypatch):
    # smuggled hunk outside the conflicted region (condition 4)
    s = build_scenario(_subdir(tmp_path, "a1"))
    diverge_base_only(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tampered = tamper_smuggle_edit(s, h1, LIVING_DOC_PATH, "SMUGGLED SEMANTIC HUNK\n")
    _seat(s, monkeypatch)
    return s, tampered, h0


def _case_attack2_hand_resolution(tmp_path, monkeypatch):
    # hand-resolved bytes: verify()-clean but not resolver-reproducible (cond 5)
    s = build_scenario(_subdir(tmp_path, "a2"))
    diverge_living_doc(s)
    h0 = s.head()
    hand_resolved = (
        "# Fixture Living Doc\n\n### Z0: seed entry\n"
        "### Z97: design-side change\n### Z98: base-side change\n"
    )
    tampered = force_merge_commit(s, {LIVING_DOC_PATH: hand_resolved})
    _seat(s, monkeypatch)
    return s, tampered, h0


def _case_attack3_second_parent_off_base(tmp_path, monkeypatch):
    # second parent off-base (condition 1)
    s = build_scenario(_subdir(tmp_path, "a3"))
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tree = _tree_of(s, h1)
    crafted = craft_merge_with_parents(s, tree, [h0, h1])
    _seat(s, monkeypatch)
    return s, crafted, h0


def _case_attack4a_squash(tmp_path, monkeypatch):
    # squash collapses the merge shape (condition 1)
    s = build_scenario(_subdir(tmp_path, "a4a"))
    diverge_living_doc(s)
    h0 = s.head()
    make_certified_sync_merge(s)
    s.git("reset", "--quiet", "--soft", h0, check=True)
    s.git("commit", "--quiet", "-m", "squash: collapsed base-sync", check=True)
    squashed = s.head()
    _seat(s, monkeypatch)
    return s, squashed, h0


def _case_attack4b_rebase(tmp_path, monkeypatch):
    # rebase collapses the merge shape (condition 1)
    s = build_scenario(_subdir(tmp_path, "a4b"))
    (s.repo_dir / "design-only.txt").write_text("design work\n", encoding="utf-8")
    s.git("add", "--", "design-only.txt", check=True)
    s.git("commit", "--quiet", "-m", "design: unrelated work", check=True)
    h0 = s.head()
    diverge_base_only(s)
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("rebase", f"origin/{s.base_ref}", check=True)
    rebased = s.head()
    _seat(s, monkeypatch)
    return s, rebased, h0


def _case_attack4c_amend(tmp_path, monkeypatch):
    # amend collapses the merge shape (condition 1)
    s = build_scenario(_subdir(tmp_path, "a4c"))
    h0 = s.head()
    diverge_living_doc(s)
    s.git("commit", "--quiet", "--amend", "-m", "amended: reworded", check=True)
    amended = s.head()
    _seat(s, monkeypatch)
    return s, amended, h0


def _case_attack6_ordinary_commit_in_middle(tmp_path, monkeypatch):
    # an ordinary commit in the middle of an otherwise-certified chain
    s = build_scenario(_subdir(tmp_path, "a6"))
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    make_certified_sync_merge(s)
    (s.repo_dir / "ordinary.txt").write_text("an ordinary commit\n", encoding="utf-8")
    s.git("add", "--", "ordinary.txt", check=True)
    s.git("commit", "--quiet", "-m", "design: ordinary unrelated commit", check=True)
    diverge_base_only(s, extra_line="### Zb: advance 2\n")
    h3 = make_certified_sync_merge(s)
    _seat(s, monkeypatch)
    return s, h3, h0


def _case_attack7_chain_over_cap(tmp_path, monkeypatch):
    # chain over the (config-pinned) cap of 2
    s = build_scenario(_subdir(tmp_path, "a7"))
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    make_certified_sync_merge(s)
    diverge_base_only(s, extra_line="### Zb: advance 2\n")
    make_certified_sync_merge(s)
    diverge_base_only(s, extra_line="### Zc: advance 3\n")
    h3 = make_certified_sync_merge(s)
    _seat(s, monkeypatch)
    return s, h3, h0


def _case_attack9a_anchor_is_merged_base_commit(tmp_path, monkeypatch):
    # anchor is the merged-in base commit (never a first-parent ancestor)
    s = build_scenario(_subdir(tmp_path, "a9a"))
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    m = s.origin_head()
    h1 = make_certified_sync_merge(s)
    _seat(s, monkeypatch)
    return s, h1, m


def _case_attack9b_off_branch_sha(tmp_path, monkeypatch):
    # off-branch sha never on the first-parent chain
    s = build_scenario(_subdir(tmp_path, "a9b"))
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    off_branch = craft_merge_with_parents(s, f"{h0}^{{tree}}", [], message="off-branch orphan")
    _seat(s, monkeypatch)
    return s, h1, off_branch


def _case_attack10_stale_base_broken_remote(tmp_path, monkeypatch):
    # stale-ref: base rewritten + remote broken after a valid seat
    s = build_scenario(_subdir(tmp_path, "a10"))
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    _seat(s, monkeypatch)
    rewrite_origin_base(s)
    break_remote(s)
    return s, h1, h0


# Ordered dispatch table -- the KEYS define ATTACK_CASE_NAMES (order preserved).
_CASE_BUILDERS = {
    "attack1_smuggled_hunk": _case_attack1_smuggled_hunk,
    "attack2_hand_resolution": _case_attack2_hand_resolution,
    "attack3_second_parent_off_base": _case_attack3_second_parent_off_base,
    "attack4a_squash": _case_attack4a_squash,
    "attack4b_rebase": _case_attack4b_rebase,
    "attack4c_amend": _case_attack4c_amend,
    "attack6_ordinary_commit_in_middle": _case_attack6_ordinary_commit_in_middle,
    "attack7_chain_over_cap": _case_attack7_chain_over_cap,
    "attack9a_anchor_is_merged_base_commit": _case_attack9a_anchor_is_merged_base_commit,
    "attack9b_off_branch_sha": _case_attack9b_off_branch_sha,
    "attack10_stale_base_broken_remote": _case_attack10_stale_base_broken_remote,
}

ATTACK_CASE_NAMES = list(_CASE_BUILDERS.keys())


def build_attack_case(name, tmp_path, monkeypatch):
    """Build EXACTLY one attack case, returning `(scenario, head_oid, anchor)`.

    Re-arms the oracle seam (`base_sync_oracle._oracle_code_dir`) for THIS case's
    `scenario.repo_dir` via `_seat`, so the case is the active oracle target the
    moment it is built. Callers drive the predicate under test against the returned
    head/anchor before building the next case."""
    try:
        builder = _CASE_BUILDERS[name]
    except KeyError:
        raise KeyError(
            f"unknown attack case {name!r}; valid: {ATTACK_CASE_NAMES}"
        ) from None
    return builder(tmp_path, monkeypatch)


def iter_attack_cases(tmp_path, monkeypatch):
    """Thin back-compat loop -- yield `(name, scenario, head_oid, anchor)` for every
    Phase 4-5 single-shot attack, lazily (one case built per `next()`), preserving the
    "drive case N BEFORE consuming N+1" contract of the pre-split generator."""
    for name in ATTACK_CASE_NAMES:
        scenario, head_oid, anchor = build_attack_case(name, tmp_path, monkeypatch)
        yield name, scenario, head_oid, anchor
