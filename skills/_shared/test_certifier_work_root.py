"""The certifier opens its checkout through wt_root.py; no surface asks for harness isolation.

design: worktrees-under-wt-only (Task 2.6). The scan half uses `wt_layout_scan`, the
shipped checker for the isolation literal. The doc halves go through boolean helpers, so no
assert reads prose directly: a protocol section holds the contract, and each caller's
dispatch item carries one clause that points at it.
"""
from __future__ import annotations

import re
from pathlib import Path

import wt_layout_scan

ROOT = Path(__file__).resolve().parent.parent.parent
PROTOCOL = "skills/_shared/certification-protocol.md"
AGENT = "agents/tp-certifier.md"
CALLERS = ("skills/tp-run-full-design/tier-5-closeout.md", "skills/tp-design-audit/SKILL.md",
           "skills/tp-implementation-audit/SKILL.md", "skills/tp-phase-review/SKILL.md")
OPEN, REAP = "wt_root.py open --role cert", "wt_root.py reap --role cert"
_NEW_ITEM = re.compile(r"\s*(?:[-*]|\d+\.)\s")


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _contract_names(*needles: str) -> bool:
    """Every needle sits in the protocol's `## Certifier contract` section."""
    body = _text(PROTOCOL).split("\n## Certifier contract", 1)[1].split("\n## ", 1)[0]
    return all(n in body for n in needles)


def _agent_names(*needles: str) -> bool:
    text = _text(AGENT)
    return all(n in text for n in needles)


def _dispatch_clause(rel: str) -> bool:
    """The list item holding the certifier dispatch passes `WORKTREE:` and points at the contract."""
    lines = _text(rel).splitlines()
    start = next(i for i, line in enumerate(lines) if 'agent_ref("tp-certifier")' in line)
    end = start + 1
    while end < len(lines) and lines[end].strip() and not _NEW_ITEM.match(lines[end]):
        end += 1
    item = "\n".join(lines[start:end])
    return "WORKTREE:" in item and ("§Certifier contract" in item or OPEN in item)


def test_contract_opens_passes_and_reaps_the_certifier_checkout():
    assert _contract_names(OPEN, "WORKTREE:", REAP)


def test_certifier_agent_runs_in_the_worktree_when_given_one():
    assert _agent_names("WORKTREE:")


def test_every_caller_dispatch_opens_through_the_contract():
    missing = [rel for rel in CALLERS if not _dispatch_clause(rel)]
    assert missing == []


def test_no_certifier_surface_still_asks_for_isolation():
    hits = wt_layout_scan.scan([ROOT / "skills", ROOT / "agents"])
    assert {rel for rel, _line, _rule, _text in hits} & {PROTOCOL, AGENT, *CALLERS} == set()
