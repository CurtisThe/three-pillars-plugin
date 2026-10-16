"""Pin: the one-time sweep of stale pending text on the repo's own living docs.

Seven merged-and-archived designs still carried pending prose on master's living
docs (a live inventory row, a `Done — PR (pending)` cell, `(awaiting PR)` tokens).
No in-flight design can write text for them, so `final_doc_state.check` must report
`verified` for each, now and from here on. A frozen temp-repo case keeps the pin
meaningful after the sweep: the pre-sweep `task-worker-sonnet` line must still be
reported as drift with a `hand-edit` fix, so the attribution rule cannot go blind.

Oracle: example, per skills/_shared/test-fragility.md. Assertions read the JSON
payload fields (`verdict`, `fix`), not rendered prose.

design: design-complete-final-doc-state
"""

from __future__ import annotations

from pathlib import Path

import pytest

import final_doc_state

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = "three-pillars-docs"
KI = f"{DOCS}/known_issues.md"

# Merged and archived designs the sweep closed (frozen set).
SWEPT_SLUGS = (
    "fragile-test-prevention",
    "task-worker-sonnet",
    "cheap-tier-default-flag-everywhere",
    "consumer-repo-parity",
    "reviewer-delete-guard",
    "basesync-autoresolve-coverage",
    "ci-local-speed",
)

# known_issues.md line 458 as it stood before the sweep, verbatim.
PRE_SWEEP_LINE = (
    "- ~~Tokens exclude cache~~: **resolved 2026-09-29** by `task-worker-sonnet` "
    "(awaiting PR); the bullet moved to "
    "[known_issues_resolved.md](known_issues_resolved.md) §L139."
)


@pytest.mark.parametrize("slug", SWEPT_SLUGS)
def test_swept_slug_is_verified_on_the_repos_living_docs(slug):
    out = final_doc_state.check(REPO_ROOT, slug)
    assert out["verdict"] == "verified", (out["rows"], out["pending"], out["fix"])


def test_pre_sweep_task_worker_sonnet_line_is_drift_with_a_hand_edit(tmp_path):
    slug = "task-worker-sonnet"
    (tmp_path / DOCS / "completed-tp-designs" / slug).mkdir(parents=True)
    (tmp_path / KI).write_text(PRE_SWEEP_LINE + "\n", encoding="utf-8")
    out = final_doc_state.check(tmp_path, slug)
    assert out["verdict"] == "drift"
    assert f"hand-edit {KI}:1" in out["fix"]
