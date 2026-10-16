"""Live test: the committed baseline manifest against the real files and the hand-read oracle.

design: cheap-tier-local-routing 9.1 (detailed-design-posthoc.md, Baseline; detailed-design.md,
Notes 9; plan Task 9.1). The oracle literals are the independent hand read, pinned here and never
fitted: 158 = 72 local / 27 fallback / 59 never-spawned, and the final rules give 159, one row
apart. The check runs `posthoc_baseline.py check` over the real worktrees and router archive, so
in-range extras print as `late rows: n` and pass; a missing or reclassified row fails.

The skip keys on the real data only (each pinned design's telemetry in some worktree root, and a
`router-*.log` in the archive), never on worktree dir names or on the manifest existing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import warnings
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cheap_ab_state  # noqa: E402
import router_stats  # noqa: E402

REPO = HERE.parent.parent
MANIFEST_REL = "fixtures/posthoc/baseline-manifest.json"
MANIFEST = HERE / MANIFEST_REL
UNTIL = "2026-10-01T22:00:00Z"
UTC_OFFSET = "-06:00"

# The hand-read oracle, 158 rows (detailed-design-posthoc.md, Baseline), read at 2026-10-01T23:26Z.
HAND = {"local": 72, "fallback": 27, "never-spawned": 59}
# The final rules' count on the same files (detailed-design.md, Notes 9).
RULES_TOTAL = 159

# The designs whose `role: task` `local-*` rows fall in range, read from the real telemetry.
PINNED = ("fragile-test-prevention", "cheap-tier-review-prep", "basesync-autoresolve-coverage",
          "ci-local-speed", "cheap-tier-default-flag-everywhere", "fable-first-stops",
          "task-worker-sonnet")


def _absent_data() -> str | None:
    """Why the real baseline data is not on this host, else None."""
    roots = cheap_ab_state.worktree_roots(REPO)
    for slug in PINNED:
        if not any((Path(root) / "three-pillars-docs" / sub / slug / "dispatch-telemetry.ndjson").is_file()
                   for root in roots for sub in ("tp-designs", "completed-tp-designs")):
            return f"no dispatch telemetry for {slug} in any worktree root (base-sync first)"
    archive = router_stats.log_path(os.environ).parent / "router-archive"
    if not any(archive.glob("router-*.log")):
        return f"no router-*.log under {archive}"
    return None


@pytest.fixture(scope="module")
def live() -> None:
    reason = _absent_data()
    if reason:
        pytest.skip(reason)


def _recorded() -> dict:
    assert MANIFEST.is_file(), f"baseline manifest not committed: {MANIFEST}"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_total_is_the_rules_count(live):
    recorded = _recorded()
    assert len(recorded["rows"]) == RULES_TOTAL
    assert sum(recorded["per_design"].values()) == RULES_TOTAL


def test_manifest_classes_differ_from_the_hand_read_by_one_row(live):
    counts = Counter(row["class"] for row in _recorded()["rows"])
    assert set(counts) <= set(HAND), f"unknown classes: {sorted(set(counts) - set(HAND))}"
    assert sum(abs(counts[c] - HAND[c]) for c in HAND) == 1, dict(counts)


def test_manifest_covers_every_pinned_design(live):
    per = _recorded()["per_design"]
    missing = [slug for slug in PINNED if slug not in per]
    assert not missing, f"pinned designs absent from the manifest: {missing}"
    extra = sorted(set(per) - set(PINNED))
    if extra:
        warnings.warn(f"designs in the manifest beyond the pinned set: {extra}", stacklevel=1)


def test_check_against_the_real_files_passes(live):
    proc = subprocess.run(
        [sys.executable, "posthoc_baseline.py", "check", "--root", str(REPO), "--until", UNTIL,
         "--utc-offset", UTC_OFFSET, "--manifest", MANIFEST_REL],
        cwd=HERE, capture_output=True, text=True, timeout=300, check=False)
    assert proc.returncode == 0, f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
