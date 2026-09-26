"""Fail-closed attack pins for `living_doc_carry.certify_link_carry` (Phase 2, task 2.4).

Every fixture is a SOUNDNESS pin: if a crafted attack fails to refuse, that is a bug in
`living_doc_carry.py`, never in the test. `certify_link_carry` carries no oracle guard (the
public entry owns it), so these direct calls are non-vacuous by construction — each fixture
reaches (and fails at) the specific relaxed-cond5 guard under test.

The load-bearing pin is `test_m1_coincidence_attack_*`: a non-carry path whose committed blob
EQUALS the deterministic mechanical union. Against a (hypothetical) implementation that ran the
carry-set check only on the byte-MISMATCH branch, it would ride the byte-exact `continue` and
CERTIFY; the shipped M1 gate — carry-set membership FIRST and UNCONDITIONAL per path — refuses.
The fixture is genuinely discriminating: the committed blob is `_mechanical_resolution`'s own
output, so the byte-exact branch really is reachable.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from living_doc_carry import _mechanical_resolution, certify_link_carry  # noqa: E402
from base_sync_repo import (  # noqa: E402
    OTHER_PATH,
    build_scenario,
    diverge_living_doc,
    force_merge_commit,
)

KI = "three-pillars-docs/known_issues.md"


def _scenario_in(tmp_path, name: str):
    """`build_scenario` rooted in a fresh sub-directory (its clone cwd must pre-exist)."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _whole_file_conflict(s, path, *, base, origin, design) -> str:
    """Establish `base` as the merge base of a conflict on `path`, then diverge the base branch
    to `origin` and the design branch to `design`. Returns h0 (design tip)."""
    (s.origin_dir / path).parent.mkdir(parents=True, exist_ok=True)
    (s.origin_dir / path).write_text(base, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", "base: seed")
    s.git("fetch", "--quiet", "origin", s.base_ref)
    s.git("merge", "--quiet", "--ff-only", f"origin/{s.base_ref}")
    (s.origin_dir / path).write_text(origin, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", "base: diverge")
    (s.repo_dir / path).write_text(design, encoding="utf-8")
    s.git("add", "--", path)
    s.git("commit", "--quiet", "-m", "design: diverge")
    return s.head()


# ---- (1) non-carry code conflict → M1 refuse ----


def test_attack_non_carry_code_conflict_refuses(tmp_path):
    path = "skills/foo.py"
    h0 = _whole_file_conflict(s := build_scenario(tmp_path), path,
                              base="x = 1\n", origin="x = 2\n", design="x = 3\n")
    h1 = force_merge_commit(s, {path: "x = 99  # hand-resolved\n"})
    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "non-carry path differs from clean mechanical merge"


# ---- (2) M1 coincidence attack (REQUIRED) — committed == mechanical union, still refuses ----


def test_m1_coincidence_attack_committed_equals_mechanical_union_refuses(tmp_path):
    path = "skills/foo.py"   # a NON-carry path bearing a log-insert-shaped conflict
    base = "# foo module log\n\n## History\n\n- **2026-06-01** — genesis\n"
    origin = "# foo module log\n\n## History\n\n- **2026-07-02** — base entry\n- **2026-06-01** — genesis\n"
    design = "# foo module log\n\n## History\n\n- **2026-07-01** — design entry\n- **2026-06-01** — genesis\n"
    h0 = _whole_file_conflict(s := build_scenario(tmp_path), path,
                              base=base, origin=origin, design=design)

    # The committed blob is the deterministic mechanical union itself — so the byte-exact
    # `continue` branch is genuinely reachable. Only the UNCONDITIONAL M1 gate stops the carry.
    mech = _mechanical_resolution(base, design, origin)
    assert mech is not None, "fixture must actually reach the mechanical-union branch"

    h1 = force_merge_commit(s, {path: mech})
    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False, "M1: a non-carry path must never ride the byte-exact continue"
    assert lc.reason == "non-carry path differs from clean mechanical merge"


# ---- (3) masquerade set → M1 refuse ----

_MASQUERADE = [
    "three-pillars-docs/foo.json",
    "skills/x/SKILL.md",
    "three-pillars-docs/specs/framework/x.md",
    "three-pillars-docs/project-context.md",
    "CLAUDE.md",
]


def test_attack_masquerade_paths_refuse(tmp_path):
    for i, path in enumerate(_MASQUERADE):
        s = build_scenario(_scenario_in(tmp_path, f"m{i}"), living_doc_path=path)
        diverge_living_doc(s, path=path)
        h0 = s.head()
        h1 = force_merge_commit(s, {path: "hand-resolved masquerade content\n"})
        lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
        assert lc.ok is False, path
        assert lc.reason == "non-carry path differs from clean mechanical merge", path


# ---- (4) zero-drop is NEVER relaxed inside the carry-set ----


def test_attack_carry_path_drop_refuses(tmp_path):
    s = build_scenario(tmp_path)   # known_issues.md is a carry-set path
    diverge_living_doc(s)
    h0 = s.head()
    # Keeps the design-side entry but DROPS the base-side atom → verify flags the drop.
    dropping = ("# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
                "- **2026-01-02** — design-side change\n")
    h1 = force_merge_commit(s, {KI: dropping})
    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "zero-drop verifier detected a content drop"


# ---- (5) marker guard: a not-actually-resolved blob never rides the carry ----


def test_attack_conflict_markers_refuse(tmp_path):
    markers = ("<<<<<<< HEAD", "=======", "||||||| base", ">>>>>>> origin")
    for i, marker_line in enumerate(markers):
        s = build_scenario(_scenario_in(tmp_path, f"mk{i}"))
        diverge_living_doc(s)
        h0 = s.head()
        # Keeps both atoms (so it's not a drop) but leaves a stray conflict sigil in the blob.
        committed = (
            "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
            "- **2026-01-02** — design-side change\n"
            f"{marker_line}\n"
            "- **2026-01-01** — base-side change\n"
        )
        h1 = force_merge_commit(s, {KI: committed})
        lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
        assert lc.ok is False, marker_line
        assert lc.reason == "committed blob retains unresolved conflict markers", marker_line


# ---- (6) containment: an out-of-conflict edit → cond4 refuse ----


def test_attack_out_of_conflict_edit_refuses_cond4(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)   # conflict on KI only
    h0 = s.head()
    hand = (
        "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
        "- **2026-01-01** — base-side change\n- **2026-01-02** — design-side change\n"
    )
    # Also edit OTHER_PATH — a file that was never in conflict → change outside the region.
    h1 = force_merge_commit(s, {KI: hand, OTHER_PATH: "smuggled out-of-conflict edit\n"})
    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "change outside the conflicted region (condition 4)"
