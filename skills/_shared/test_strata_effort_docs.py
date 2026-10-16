"""test_strata_effort_docs.py — Strata site docs name the effort-aware spawn resolver.

design: strata-effort-every-call (Task 3.2). Every site doc that spawns a Strata
agent names `strata_effort.py spawn` as the source of its agent reference, and no
doc tells a site to log the retired `local-high` rung. Prose assertions are
substring presence, never order (test-fragility.md).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_every_site_doc_names_the_spawn_resolver():
    for rel in (
        "skills/council/strata-members.md",
        "skills/tp-pr-iterate/strata-finders.md",
        "skills/_shared/phase-check.md",
        "skills/_shared/strata-spawn.md",
    ):
        assert "strata_effort.py spawn" in _read(rel), rel


def test_spawn_doc_has_no_local_high_rung():
    assert "local-high" not in _read("skills/_shared/strata-spawn.md")


def test_finders_slot_lost_rerun_names_the_base_agent():
    doc = _read("skills/tp-pr-iterate/strata-finders.md")
    assert "review_agent" in doc
