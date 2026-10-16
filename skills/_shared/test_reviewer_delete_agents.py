"""Agent definitions name the reviewer-delete-guard boundary.

design: reviewer-delete-guard (Task 1.4)

Every read-mostly agent the `reviewer-delete-guard` hook scopes must say, in
its own definition, that deletes stay inside the `TP_SCRATCH` line of its
prompt and that the shared temp roots are off-limits. The generated
`tp-review-confirmer-deep` variant must carry the same paragraph (no drift).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import agent_variants  # noqa: E402
import reviewer_delete_hook  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
AGENTS = REPO / "agents"
# Substrings only: no shared-root path literal appears in a skills/ file.
REQUIRED = ("TP_SCRATCH", "pytest-of-$USER", "claude-$UID", "$TMPDIR",
            "reviewer-delete-guard")
EXPECTED_AGENTS = {"tp-review-confirmer", "tp-review-confirmer-deep",
                   "tp-review-confirmer-medium",
                   "tp-readonly-auditor", "tp-impl-auditor", "tp-phase-checker"}


def test_scoped_agents_are_exactly_the_read_mostly_ones():
    assert set(reviewer_delete_hook.READ_MOSTLY_AGENTS) == EXPECTED_AGENTS


@pytest.mark.parametrize("name", sorted(reviewer_delete_hook.READ_MOSTLY_AGENTS))
def test_definition_names_the_boundary(name):
    path = AGENTS / (name + ".md")
    assert path.is_file(), path
    body = path.read_text(encoding="utf-8")
    for needle in REQUIRED:
        assert needle in body, "%s lacks %r" % (name, needle)


def test_generated_deep_variant_has_no_drift():
    lines = agent_variants.check(REPO)
    assert not [ln for ln in lines if "tp-review-confirmer-deep" in ln], lines
