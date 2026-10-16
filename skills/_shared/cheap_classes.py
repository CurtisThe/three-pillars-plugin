#!/usr/bin/env python3
"""cheap_classes.py — the one cheap/judgment class table (the guard).

design: one-cheap-engine (Task 1.1, Part A)

Every model_policy.AGENTS key, model_policy.ROLES / ENGINE_ROLES entry,
cheap_tier.SLOTS key, cheap_tier.EXCLUDED dispatch role and named non-agent
site has exactly one class:

- "cheap": easy work — drafters and runbooks, council members, review finders,
  the context scout, the PR comment classifier, explainer drafts, base-sync
  windows and implementation task workers (the task slot);
- "judgment": stays on Opus — generators (design, detail, plan, design-learn,
  PR), the council synth, the Opus check, verdicts, auditors, the certifier,
  the finalizer and every gate.

klass(name) looks up an exact row first, then fnmatch glob rows (council-*,
tp-task-worker-*); an unclassed name raises KeyError, so a new agent or site
must be classed before it can be routed. Stdlib-only; no model is called here.
"""
from __future__ import annotations

import fnmatch

CHEAP = "cheap"
JUDGMENT = "judgment"

CLASSES: dict[str, str] = {
    # model_policy.AGENTS — exact names
    "tp-generator": JUDGMENT,
    # phase dispatcher (strata-spend-leaks): cheap-class for model policy only. Slot 7 dispatches it
    # bare, so the agent_caps.CAPS row and cheap_engine.engine_for result it now gets are never
    # applied: do not cap or engine-resolve it.
    "tp-worker": CHEAP,
    "tp-readonly-auditor": JUDGMENT,
    "tp-impl-auditor": JUDGMENT,
    "tp-certifier": JUDGMENT,
    "tp-phase-checker": JUDGMENT,
    "tp-review-confirmer": JUDGMENT,
    "tp-review-confirmer-deep": JUDGMENT,
    "tp-review-confirmer-medium": CHEAP,  # Strata-only finder copy (strata-effort-every-call)
    "tp-finalizer": JUDGMENT,
    "tp-runbook": CHEAP,
    "tp-spawn-host": CHEAP,
    "tp-drafter": CHEAP,
    "tp-drafter-xhigh": CHEAP,
    "tp-task-worker": CHEAP,
    "tp-explainer": CHEAP,  # explainer drafts (explainer-agent); its check is a pinned opus span
    "council-synth": JUDGMENT,  # exact row beats the council-* glob
    # model_policy.AGENTS — glob rows
    "council-*": CHEAP,
    "tp-task-worker-*": CHEAP,
    # model_policy.ROLES
    "review": JUDGMENT,
    "fix": JUDGMENT,
    "classifier": CHEAP,
    "design_run": JUDGMENT,
    # model_policy.ENGINE_ROLES
    "council_member": CHEAP,
    "review_finder": CHEAP,
    "context_scout": CHEAP,
    "explainer": CHEAP,  # the explainer role (explainer-agent): drafts follow the one rule
    # cheap_tier.SLOTS (operator 2026-10-06: cheap tier on all slots, handoff included)
    "task": CHEAP,
    "runbook": CHEAP,
    "base_sync_splice": CHEAP,
    "pr_fix_reproducer": CHEAP,
    "classifier_judge": CHEAP,
    "history_line": CHEAP,
    "handoff": CHEAP,
    "docs_draft": CHEAP,
    "review_slice": CHEAP,
    "review_refs": CHEAP,
    "ci_log_triage": CHEAP,
    "repro_scaffold": CHEAP,
    # dispatch roles (AGENTS row roles and cheap_tier.EXCLUDED)
    "drafter": CHEAP,
    "audit-member": CHEAP,  # council members
    "impl-audit": JUDGMENT,
    "certify": JUDGMENT,
    "phase-check": JUDGMENT,
    "generator": JUDGMENT,
    "phase-worker": JUDGMENT,
    "reader": JUDGMENT,
    "council": JUDGMENT,  # the synth step
    "design": JUDGMENT,
    "plan": JUDGMENT,
    "orchestrator": JUDGMENT,
    "merge_gate": JUDGMENT,
    "land": JUDGMENT,
    "ci_local": JUDGMENT,
    "ci_local_stamp": JUDGMENT,
    "finalizer": JUDGMENT,
    "severity": JUDGMENT,
    "confirm": JUDGMENT,
    "digest_post": JUDGMENT,
    # named non-agent sites
    "pr_classifier": CHEAP,
    "base_sync_window": CHEAP,
    "explainer_draft": CHEAP,
}


def _is_glob(name: str) -> bool:
    return any(c in name for c in "*?[")


def klass(name: str) -> str:
    """The class of `name`: an exact row, else the first matching glob row;
    KeyError when unclassed."""
    if name in CLASSES:
        return CLASSES[name]
    for pattern, cls in CLASSES.items():
        if _is_glob(pattern) and fnmatch.fnmatchcase(name, pattern):
            return cls
    raise KeyError(f"{name!r} has no cheap_classes.CLASSES row (cheap or judgment)")


def cheap_sites() -> set[str]:
    """Every CLASSES row (name or glob) whose class is cheap."""
    return {name for name, cls in CLASSES.items() if cls == CHEAP}
