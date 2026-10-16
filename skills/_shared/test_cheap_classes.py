"""Tests for cheap_classes.py — the one cheap/judgment class table (the guard).

design: one-cheap-engine (Task 1.1). Every agent, role, engine role, cheap-tier slot
and named non-agent site has exactly one class; an unclassed name raises.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_classes as cc  # noqa: E402
import cheap_tier  # noqa: E402
import model_policy  # noqa: E402

SITES = ("pr_classifier", "base_sync_window", "explainer_draft")
COUNCIL_MEMBER_ROLE = model_policy.AGENTS["council-*"][0]


def _names():
    return (list(model_policy.AGENTS) + list(model_policy.ROLES)
            + list(model_policy.ENGINE_ROLES) + list(cheap_tier.SLOTS) + list(SITES))


def test_every_agent_role_and_slot_is_classed():
    for name in _names():
        assert cc.klass(name) in ("cheap", "judgment"), name
    assert set(cc.CLASSES.values()) <= {"cheap", "judgment"}


def test_unclassed_site_raises():
    with pytest.raises(KeyError):
        cc.klass("tp-new-agent")


@pytest.mark.parametrize("name", [
    "tp-generator", "tp-readonly-auditor", "tp-impl-auditor",
    "tp-certifier", "tp-finalizer", "tp-review-confirmer", "tp-review-confirmer-deep",
    "impl-audit", "certify", "review", "council-synth",
])
def test_judgment_covers_generators_gates_and_finalizer(name):
    assert cc.klass(name) == "judgment"


@pytest.mark.parametrize("name", [
    "council-architect", "council_member", "review_finder", "context_scout",
    "tp-drafter", "tp-drafter-xhigh", "tp-runbook", "runbook", "task",
    "tp-task-worker", "tp-task-worker-local-xhigh", "tp-worker", "classifier", "classifier_judge",
    "pr_classifier", "base_sync_window", "base_sync_splice", "explainer_draft",
    "handoff", "history_line", "docs_draft",
])
def test_cheap_covers_design_easy_sites(name):
    assert cc.klass(name) == "cheap"


def test_cheap_sites_are_the_cheap_rows():
    assert cc.cheap_sites() == {n for n, c in cc.CLASSES.items() if c == "cheap"}


def test_excluded_roles_are_judgment():
    assert COUNCIL_MEMBER_ROLE not in cheap_tier.EXCLUDED
    for name in cheap_tier.EXCLUDED - {COUNCIL_MEMBER_ROLE}:
        assert cc.klass(name) == "judgment", name
