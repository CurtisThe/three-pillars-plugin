"""Replay oracle: the six real 2026-10-16 base-syncs resolve their History/archive files (Task 4.4).

Each entry is a real `PR:head:base` triple from the 10-16 fleet (`basesync-generator-catalog`
detailed-design Test Strategy). The driver runs in a detached temp worktree cut from THIS repo, so
the historical conflicts are replayed rather than a synthetic shape. Every case SKIPS cleanly when
the commits are unreachable (shallow clone, or a clone predating these shas) or outside a git
checkout.

Expectations (Behavior 12): `product_roadmap.md`, `product_roadmap_archive.md` and
`architecture_archive.md` are auto-resolved on every replay; no bullet line occurs twice in a
merged History/archive file; no dated bullet is in both the merged live doc and the merged archive.
Each path that still defers is listed in STILL_DEFERRED with its `replay-causes.md` class, and its
outcome reason must carry that class. The duplicate / re-added checks excuse only a duplication
that already exists on the head or base input side. One extra excuse, for replay 307b: its head
(0b6a7c47d) is the defective PR itself and already holds the 2026-10-15 certifier-lean bullet twice
in product_roadmap.md while the base rolled it to the archive; the merge carries the head's surplus
copy forward. That is a carried-forward head-side duplicate, not a merge defect.
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
from task_scope import _git_env as clean_git_env  # noqa: E402
from test_replay_real_syncs import ROOT, _git, _commit_exists, _is_shallow  # noqa: E402

pytestmark = pytest.mark.skipif(not ROOT, reason="needs a git checkout")

DOCS = "three-pillars-docs/"
PRM = DOCS + "product_roadmap.md"
PRA = DOCS + "product_roadmap_archive.md"
ARCHA = DOCS + "architecture_archive.md"
KI = DOCS + "known_issues.md"
HISTORY_PATHS = (PRM, PRA, ARCHA)

# name, head, base, measured census (auto, deferred)
PAIRS = [
    ("305", "a3709a150", "66bbfd717", (2, 0)),
    ("306", "ff63a85c9", "765cfec04", (4, 0)),
    ("307a", "85d1484d2", "765cfec04", (3, 0)),
    ("307b", "0b6a7c47d", "cd3b61af0", (3, 0)),
    ("308a", "f8f9a221c", "cd3b61af0", (4, 0)),
    ("308b", "bdbfc8e95", "612763046", (4, 0)),
]

# (sync, path) -> hunk class from replay-causes.md: unkeyed '- Guards:' / '- Fleet:' prose edits
# still defer. Anything not listed must be auto-resolved. `known_issues.md` left this list at Task
# 2.3: its `N Low issues \u2192` count line is the `low-count-line` class now.
STILL_DEFERRED = {
    ("306", PRM): "generic-prose",
    ("308a", PRM): "generic-prose",
}

BULLET = re.compile(r"^\s*[-*] \S")
DATED = re.compile(r"^\s*[-*] \**(\d{4}-\d{2}-\d{2})\**.*?(`[^`]+`)")


def _show(rev, path):
    r = _git("show", f"{rev}:{path}", check=False)
    return r.stdout if r.returncode == 0 else ""


def _replay(tmp_path, name, head, base):
    wt = tmp_path / f"wt-{name}"
    _git("worktree", "add", "-q", "--detach", str(wt), head)
    try:
        report = merge_back(str(wt), base)
        texts = {}
        for p in HISTORY_PATHS:
            f = wt / p
            texts[p] = f.read_text(encoding="utf-8") if f.is_file() else None
        return report, texts
    finally:
        subprocess.run(["git", "-C", str(wt), "merge", "--abort"], capture_output=True,
                       env=clean_git_env())
        _git("worktree", "remove", "--force", str(wt), check=False)


def _bullet_counts(text):
    counts = {}
    for ln in (text or "").splitlines():
        if BULLET.match(ln):
            counts[ln] = counts.get(ln, 0) + 1
    return counts


def _dated_key_counts(text):
    counts = {}
    for ln in (text or "").splitlines():
        m = DATED.match(ln)
        if m:
            counts[m.groups()] = counts.get(m.groups(), 0) + 1
    return counts


def _skip_unless_reachable(name, head, base):
    if _is_shallow() or not (_commit_exists(head) and _commit_exists(base)):
        pytest.skip(f"{name}: shallow clone or commit unreachable")


@pytest.mark.parametrize("name,head,base,baseline", PAIRS)
def test_census_never_falls_below_pinned_baseline(tmp_path, name, head, base, baseline):
    _skip_unless_reachable(name, head, base)
    pinned_auto, pinned_deferred = baseline
    report, _texts = _replay(tmp_path, name, head, base)
    assert len(report.auto_resolved) >= pinned_auto, report.to_json()
    assert len(report.deferred) <= pinned_deferred, report.to_json()
    for outcome in report.outcomes:
        assert "resolver raised" not in outcome.get("reason", ""), outcome


@pytest.mark.parametrize("name,head,base,baseline", PAIRS)
def test_history_and_archive_files_resolve_without_duplicates(tmp_path, name, head, base,
                                                              baseline):
    _skip_unless_reachable(name, head, base)
    report, texts = _replay(tmp_path, name, head, base)
    outcomes = {o.get("path"): o for o in report.outcomes}
    for path in HISTORY_PATHS + (KI,):
        cls = STILL_DEFERRED.get((name, path))
        if cls is None:
            assert path not in report.deferred, (path, report.to_json())
            assert path not in report.partially_resolved, (path, report.to_json())
            continue
        assert path not in report.auto_resolved, (path, report.to_json())
        assert cls in outcomes.get(path, {}).get("reason", ""), (path, outcomes.get(path))
    for path in HISTORY_PATHS:
        merged = texts[path]
        if (name, path) in STILL_DEFERRED or merged is None:
            continue
        assert not re.search(r"^(<{7}|={7}|>{7})", merged, re.M), f"{path}: conflict marker"
        sides = [_bullet_counts(_show(head, path)), _bullet_counts(_show(base, path))]
        for line, n in _bullet_counts(merged).items():
            if n > 1:
                assert any(s.get(line, 0) > 1 for s in sides), f"{name} {path}: duplicate {line!r}"


@pytest.mark.parametrize("name,head,base,baseline", PAIRS)
def test_no_archived_bullet_is_readded_to_the_live_doc(tmp_path, name, head, base, baseline):
    _skip_unless_reachable(name, head, base)
    if (name, PRM) in STILL_DEFERRED:
        pytest.skip(f"{name}: live doc still defers ({STILL_DEFERRED[(name, PRM)]})")
    _report, texts = _replay(tmp_path, name, head, base)
    live, archive = texts[PRM], texts[PRA]
    overlap = set(_dated_key_counts(live)) & set(_dated_key_counts(archive))
    pre_existing = set()
    for rev in (head, base):
        pre_existing |= (set(_dated_key_counts(_show(rev, PRM)))
                         & set(_dated_key_counts(_show(rev, PRA))))
    head_dupes = {k for k, n in _dated_key_counts(_show(head, PRM)).items() if n > 1}
    readded = overlap - pre_existing - head_dupes
    assert not readded, sorted(readded)
