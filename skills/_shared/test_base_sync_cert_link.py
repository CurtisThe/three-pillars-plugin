"""Real-git integration tests for the base-sync fixture builder (task 2.1's smoke section)
and `certify_link` RME conditions 1-2 (task 2.4: merge shape + recompute).

All fixture repos come from `fixtures/base_sync_repo.py` -- LOCAL clones/forks of the real
running checkout (never `git init`), so this checkout's HEAD is always an ancestor-or-equal of
each fixture's `origin/<base>` tip. `run_git` is never injected here: every test drives real
git objects (the module's own default `_make_default_git` seam).

Conditions 3-5 continue in `test_base_sync_cert_link2.py` (split per the plan's named escape
hatch to stay under the 300-line soft cap).
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
    build_scenario,
    break_remote,
    craft_merge_with_parents,
    diverge_base_only,
    diverge_living_doc,
    make_certified_sync_merge,
    rewrite_origin_base,
    shallow_clone,
    tamper_smuggle_edit,
)


def _tree_of(scenario, commit_sha: str) -> str:
    r = subprocess.run(["git", "-C", str(scenario.repo_dir), "rev-parse", f"{commit_sha}^{{tree}}"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


# ============================================================
# Task 2.1: builder smoke -- every hook works, offline, on a real clone
# ============================================================


def test_builder_offline_fetch_and_ancestry(tmp_path):
    s = build_scenario(tmp_path)
    r = s.git("fetch", "origin", s.base_ref, check=False)
    assert r.returncode == 0
    # this checkout's HEAD is an ancestor-or-equal of origin/<base>'s tip by construction.
    anc = s.git("merge-base", "--is-ancestor", s.head(), s.origin_head(), check=False)
    assert anc.returncode == 0


def test_builder_scripted_merge_helper_resolves_for_real(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h1 = make_certified_sync_merge(s)
    r = s.git("rev-list", "--parents", "-n1", h1, check=True)
    assert len(r.stdout.strip().split()) == 3   # h1 + 2 parents
    content = (s.repo_dir / LIVING_DOC_PATH).read_text(encoding="utf-8")
    assert "### Z1: design-side change" in content
    assert "### Z2: base-side change" in content   # renumbered by the real resolver


def test_builder_craft_merge_with_parents(tmp_path):
    s = build_scenario(tmp_path)
    h0 = s.head()
    single = craft_merge_with_parents(s, f"{h0}^{{tree}}", [h0])
    r = s.git("rev-list", "--parents", "-n1", single, check=True)
    assert r.stdout.strip() == f"{single} {h0}"


def test_builder_tamper_smuggle_edit(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h1 = make_certified_sync_merge(s)
    tampered = tamper_smuggle_edit(s, h1, LIVING_DOC_PATH, "SMUGGLED\n")
    assert tampered != h1
    orig_parents = s.git("rev-list", "--parents", "-n1", h1, check=True).stdout.strip()
    new_parents = s.git("rev-list", "--parents", "-n1", tampered, check=True).stdout.strip()
    assert orig_parents.split()[1:] == new_parents.split()[1:]   # same parents, new tree


def test_builder_broken_remote(tmp_path):
    s = build_scenario(tmp_path)
    break_remote(s)
    r = s.git("fetch", "origin", s.base_ref, check=False)
    assert r.returncode != 0


def test_builder_origin_rewrite(tmp_path):
    s = build_scenario(tmp_path)
    old_tip = s.origin_head()
    new_tip = rewrite_origin_base(s)
    assert new_tip != old_tip


def test_builder_shallow_clone(tmp_path):
    s = build_scenario(tmp_path)
    shallow_dir = shallow_clone(s, tmp_path / "shallow")
    r = subprocess.run(["git", "-C", str(shallow_dir), "rev-parse", "--is-shallow-repository"],
                       capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "true"


# ============================================================
# Task 2.4: certify_link conditions 1-2
# ============================================================


def test_happy_clean_certified_sync_merge(tmp_path):
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == ()


def test_happy_conflicted_certified_sync_merge(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    lc = certify_link(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason
    assert lc.conflicted_paths == (LIVING_DOC_PATH,)


def test_single_parent_commit_fails_condition1(tmp_path):
    s = build_scenario(tmp_path)
    h0 = s.head()
    single = craft_merge_with_parents(s, f"{h0}^{{tree}}", [h0])
    lc = certify_link(str(s.repo_dir), h0, single, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: expected 2 parents, found 1"


def test_octopus_merge_fails_condition1(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tree = _tree_of(s, h1)
    p2 = s.origin_head()
    third = s.origin_git("rev-parse", f"{p2}^", check=True).stdout.strip()   # a 3rd DISTINCT parent
    octopus = craft_merge_with_parents(s, tree, [h0, p2, third])
    lc = certify_link(str(s.repo_dir), h0, octopus, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: expected 2 parents, found 3"


def test_p1_not_h0_fails_condition1(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tree = _tree_of(s, h1)
    p2 = s.origin_head()
    wrong_parent = s.git("rev-parse", f"{h0}^", check=True).stdout.strip()
    crafted = craft_merge_with_parents(s, tree, [wrong_parent, p2])
    lc = certify_link(str(s.repo_dir), h0, crafted, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: first parent is not h0"


def test_second_parent_off_base_fails_condition1(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    tree = _tree_of(s, h1)
    off_base = s.git("rev-parse", "HEAD", check=True).stdout.strip()   # design_branch tip, not on base
    crafted = craft_merge_with_parents(s, tree, [h0, off_base])
    lc = certify_link(str(s.repo_dir), h0, crafted, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "second parent not on base branch"


def test_amended_head_move_fails_condition1(tmp_path):
    """Squash/rebase/amend head-moves all collapse to the SAME observable shape at the
    git-object level: either not a 2-parent commit (this test: an amend that keeps 1 parent
    but a different tree), or a 2-parent commit whose first parent isn't h0 (the dedicated
    p1-not-h0 test above)."""
    s = build_scenario(tmp_path)
    h0 = s.head()
    diverge_living_doc(s)
    amended_tree = _tree_of(s, s.head())
    amended = craft_merge_with_parents(s, amended_tree, [h0])
    lc = certify_link(str(s.repo_dir), h0, amended, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: expected 2 parents, found 1"
