"""Replay oracle: run the shipped merge driver on real 2026-09-30 base-syncs (Task 4.1).

Each entry is a real `PR:head:base` triple (`three-pillars-docs/tp-designs/
basesync-autoresolve-coverage/plan.md`'s header / `replay.sh`). The driver runs in a detached
temp worktree cut from THIS repo (never a fixture repo), so these tests exercise the real
historical conflicts rather than any synthetic shape. Every test here SKIPS cleanly (never
fails) when the commits are unreachable — a shallow clone, or a clone that predates these
shas — which is also why the module never asserts exact counts, only "never worse than the
oracle's measured baseline".
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from merge_driver import merge_back  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only
from living_doc_carry import certify_link_carry  # noqa: E402

# Outside a git checkout (a consumer install of the shipped skill) there is nothing to replay:
# skip the whole module instead of failing collection.
_TOP = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=os.path.dirname(__file__),
                      capture_output=True, text=True, check=False, env=clean_git_env())
ROOT = _TOP.stdout.strip() if _TOP.returncode == 0 else ""
pytestmark = pytest.mark.skipif(not ROOT, reason="not a git checkout: no real syncs to replay")

KI = "three-pillars-docs/known_issues.md"
KR = "three-pillars-docs/known_issues_resolved.md"
PRM = "three-pillars-docs/product_roadmap.md"
PRA = "three-pillars-docs/product_roadmap_archive.md"
ARCH = "three-pillars-docs/architecture.md"
ANGLES = "skills/tp-pr-iterate/scripts/angles.py"

# name, head, base, baseline (auto, partial, deferred)
# Baselines: basesync-three-way-verifier Phase 6 measured census (auto, partial, deferred).
PAIRS = [
    ("188", "592f9112", "b54717ab", (1, 1, 1)),
    ("191", "50406d16", "685ebb53", (2, 2, 3)),
    ("193", "ec041fb0", "976ed07b", (0, 1, 0)),
    ("194", "f49955a0", "976ed07b", (2, 0, 0)),
    ("196a", "d1d3d9a2", "adbb6d0b", (1, 0, 0)),
    ("196b", "d0cd24fb", "104dd993", (2, 0, 0)),
    ("rdg", "caf99e38", "c181447a", (2, 2, 1)),
]


def _git(*args, check=True):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True,
                          check=check, env=clean_git_env())


def _commit_exists(sha: str) -> bool:
    r = _git("cat-file", "-e", f"{sha}^{{commit}}", check=False)
    return r.returncode == 0


def _is_shallow() -> bool:
    return _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"


def _run_driver(tmp_path, name, head, base, *, keep_worktree_text=None):
    """Create a detached worktree on `head`, run the driver against `base`, always clean up.

    `keep_worktree_text` (a repo-relative path) returns `(report, text_or_None)`: the file's
    post-driver bytes, read from the worktree BEFORE it is torn down."""
    wt = tmp_path / f"wt-{name}"
    _git("worktree", "add", "-q", "--detach", str(wt), head)
    try:
        report = merge_back(str(wt), base)
        text = None
        if keep_worktree_text is not None:
            p = wt / keep_worktree_text
            text = p.read_text(encoding="utf-8") if p.is_file() else None
        return report, text
    finally:
        subprocess.run(["git", "-C", str(wt), "merge", "--abort"], capture_output=True,
                       env=clean_git_env())
        _git("worktree", "remove", "--force", str(wt), check=False)


@pytest.mark.parametrize("name,head,base,baseline", PAIRS)
def test_replay_never_falls_below_baseline(tmp_path, name, head, base, baseline):
    if _is_shallow() or not (_commit_exists(head) and _commit_exists(base)):
        pytest.skip(f"{name}: shallow clone or commit unreachable")
    baseline_auto, _baseline_partial, baseline_deferred = baseline
    report, _text = _run_driver(tmp_path, name, head, base)
    assert len(report.auto_resolved) >= baseline_auto, report.to_json()
    assert len(report.deferred) <= baseline_deferred, report.to_json()
    for outcome in report.outcomes:
        assert "resolver raised" not in outcome.get("reason", ""), outcome
    if name == "194":
        assert KR in report.auto_resolved, report.to_json()


def test_behavior_8_sync_196(tmp_path):
    names = {n: (h, b) for n, h, b, _ in PAIRS}
    head_a, base_a = names["196a"]
    head_b, base_b = names["196b"]
    if _is_shallow() or not (_commit_exists(head_a) and _commit_exists(base_a)
                             and _commit_exists(head_b) and _commit_exists(base_b)):
        pytest.skip("196: shallow clone or commit unreachable")

    report_b, _text = _run_driver(tmp_path, "196b", head_b, base_b)
    assert KI in report_b.auto_resolved, report_b.to_json()
    assert PRM in report_b.auto_resolved, report_b.to_json()

    # 196a: master (theirs) retitled M44 in place and the branch (ours) left it alone, so the old
    # title is excused by the three-way check and the file resolves with master's heading.
    report_a, ki_text = _run_driver(tmp_path, "196a", head_a, base_a, keep_worktree_text=KI)
    assert KI in report_a.auto_resolved, report_a.to_json()
    assert ki_text is not None
    assert not re.search(r"^(<{7}|={7}|>{7})", ki_text, re.M), "conflict marker left in the KI text"
    m44 = [ln for ln in ki_text.splitlines() if ln.startswith("### M44")]
    assert len(m44) == 1, m44
    assert m44[0].startswith("### M44: nested `TaskStop` is refused by the harness"), m44
    assert "runaway ceiling unverified" not in m44[0], m44

    base_sha = _git("rev-parse", "104dd993").stdout.strip()
    if not _commit_exists(base_sha) or _git(
            "merge-base", "--is-ancestor", base_sha, "origin/master", check=False
    ).returncode != 0:
        pytest.skip("104dd993 is not an ancestor of origin/master")
    h0 = _git("rev-parse", "d0cd24fb").stdout.strip()
    h1 = _git("rev-parse", "b532258c").stdout.strip()
    link = certify_link_carry(ROOT, h0, h1, base_ref="master")
    assert link.ok, link.reason


def test_behavior_8_9_driver_reviewer_delete_guard(tmp_path):
    name, head, base, _baseline = next(p for p in PAIRS if p[0] == "rdg")
    if _is_shallow() or not (_commit_exists(head) and _commit_exists(base)):
        pytest.skip("rdg: shallow clone or commit unreachable")

    # Exact counts, as measured in a prototype of Task 3.3 (stronger than the generic
    # "never below the plan.md-header baseline" check that the parametrized replay test enforces
    # for every triple).
    # Re-measured after basesync-three-way-verifier Phase 4 (`shaped-line-merge` wired in):
    # unchanged, and ARCH / PRM still defer as `generic-prose`. Re-measured again after Phase 5
    # (the design-dir `decisions.md` union lane): unchanged, 2/2/1 and the same `generic-prose` reasons.
    EXPECTED_AUTO, EXPECTED_PARTIAL, EXPECTED_DEFERRED = 2, 2, 1

    report, ki_text = _run_driver(tmp_path, name, head, base, keep_worktree_text=KI)
    assert len(report.auto_resolved) == EXPECTED_AUTO, report.to_json()
    assert len(report.partially_resolved) == EXPECTED_PARTIAL, report.to_json()
    assert len(report.deferred) == EXPECTED_DEFERRED, report.to_json()
    assert KI in report.auto_resolved, report.to_json()
    assert PRA in report.auto_resolved, report.to_json()
    assert ARCH in report.partially_resolved, report.to_json()
    assert PRM in report.partially_resolved, report.to_json()
    for path in (ARCH, PRM):
        outcome = next(o for o in report.outcomes if o["path"] == path)
        assert "generic-prose" in outcome["reason"], outcome
    assert ANGLES in report.deferred, report.to_json()

    if not _commit_exists("070aa04c"):
        return   # skip only the one byte-for-byte comparison that needs this sha
    oracle = _git("show", "070aa04c:" + KI).stdout
    assert ki_text == oracle
