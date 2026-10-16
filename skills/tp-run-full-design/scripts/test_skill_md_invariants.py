"""Grep-level lint tests over skills/tp-run-full-design/SKILL.md.

These assert that load-bearing literal phrases survive future edits. They
are not a substitute for end-to-end behavior tests (see detailed-design
§Test Strategy "Phase 4 known limitation") — that coverage comes from
dogfood orchestrator runs. But they catch silent prose drift on the
phrases the orchestrator's runtime interpretation depends on.
"""
from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

import pytest

# SLOTS lives in the shared html_briefing package, which is PRO-TIER as of
# `html-pro-tier` (the live-briefing/cockpit stack ships pro-only). One source of
# truth, consumed by this lint AND the briefing DAG producer. In the FREE core
# build html_briefing is absent, so the SLOTS-dependent lints skip cleanly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "_shared" / "html_briefing"),
)
import skill_text  # noqa: E402

try:
    from tier_sequence import SLOTS  # noqa: E402

    _HTML_BRIEFING_PRESENT = True
except ModuleNotFoundError:
    SLOTS = ()  # html_briefing is pro-tier; absent in the free core build
    _HTML_BRIEFING_PRESENT = False


SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

# Repo root = skills/tp-run-full-design/scripts/ -> up 3.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# The 10 dispatch slots in pipeline order are imported from tier_sequence.SLOTS
# (module-level above) so the dispatch-loop and budget-table invariants assert
# against the same shared set — a dropped slot fails both here and in the
# briefing DAG producer.


@functools.lru_cache(maxsize=1)
def _body() -> str:
    return skill_text.read_skill_text("tp-run-full-design")


@pytest.mark.skipif(not _HTML_BRIEFING_PRESENT, reason="SLOTS lives in pro-tier html_briefing; N/A in free core")
def test_dispatch_loop():
    body = _body()

    # Every slot appears as a named slot-section heading. Iterate the slot
    # list as a tuple so a dropped section fails on the exact missing name.
    # Backtick-delimited so `design` does not match `design-audit`/`design-learn`
    # and `plan` does not match `plan-audit`. (SLOTS is module-level.)
    heading_lines = [ln for ln in body.splitlines() if ln.lstrip().startswith("#")]
    for slot in SLOTS:
        token = f"`{slot}`"
        assert any(token in ln for ln in heading_lines), (
            f"slot {slot!r} must appear as a named slot-section heading "
            f"(expected a heading line containing {token})"
        )


@pytest.mark.skipif(not _HTML_BRIEFING_PRESENT, reason="SLOTS lives in pro-tier html_briefing; N/A in free core")
def test_budget_table():
    body = _body()
    section = body.split("\n## Per-slot budget table", 1)[1].split("\n## ", 1)[0]

    # Every slot from Task 3.1 has a budget row. Backtick-delimited so `design`
    # does not match `design-audit`/`design-learn` and `plan` not `plan-audit`.
    table_rows = [ln for ln in section.splitlines() if "|" in ln]
    for slot in SLOTS:
        token = f"`{slot}`"
        assert any(token in ln for ln in table_rows), (
            f"budget table must have a row for slot {slot!r}"
        )


def test_return_clipping():
    body = _body()
    section = body.split("\n## Return clipping", 1)[1].split("\n## ", 1)[0]

    # Ordering: read tokens -> parse -> clip (discard raw reply).
    i_tok = section.index("subagent_tokens")
    i_parse = section.index("parse_tier_return")
    i_clip = section.index("discards the raw reply")
    assert i_tok < i_parse < i_clip, (
        "on-return order must be subagent_tokens -> parse_tier_return -> clip"
    )


def test_every_tier_dispatched():
    """Task 8.1: every non-worker tier executes via subagent dispatch, never
    inline in the orchestrator's own conversation (one execution model, no
    double definitions). Positive completeness over the tier tuple."""
    body = _body()

    # Each non-worker tier resolves to a dispatched slot heading. (pickup and
    # the Mode-C interactive design front-end are intentionally excluded — they
    # are not autonomous-dispatch slots; the worker/phase-implement tier was
    # already dispatched.)
    NON_WORKER_TIERS = (
        "design", "detail", "design-audit", "plan", "plan-audit",
        "impl-audit", "design-learn",
    )
    heading_lines = [ln for ln in body.splitlines() if ln.lstrip().startswith("#")]
    for tier in NON_WORKER_TIERS:
        assert any(f"`{tier}`" in ln for ln in heading_lines), (
            f"tier {tier!r} must have a slot-section heading"
        )

    # The design-pipeline (Tier 2) and consolidation (Tier 5) sections frame
    # execution as subagent dispatch, not as the orchestrator running the skill
    # in its own context.
    tier2 = body.split("\n## Tier 2", 1)[1].split("\n## ", 1)[0]
    tier5 = body.split("\n## Tier 5", 1)[1].split("\n## ", 1)[0]
    for name, sec in (("Tier 2", tier2), ("Tier 5", tier5)):
        assert "dispatch" in sec.lower(), (
            f"{name} must describe execution via subagent dispatch"
        )


def test_phase_implement_dispatch():
    """Nested per task (local-implement-and-review 7.3): what the nested dispatch reads and
    spawns exists. Behaviour, not wording (#165 rulings): the files, workers and headings its
    section names resolve."""
    body = _body()
    section = body.split("\n## Phase-implement dispatch", 1)[1].split("\n## ", 1)[0]
    _assert_refs_resolve(section)


# --------------------------------------------------------------------------- #
# phase-subagent-protocol — invariant test (Task 4.1)
# --------------------------------------------------------------------------- #
def test_phase_implement_auto_serial_note():
    """Task 4.1 (rewritten by local-implement-and-review 7.3) — tp-phase-implement
    ## Auto Mode's Slot-7 rules point at `local-dispatch.md` and `tp-task-worker`, and at
    orchestrator sections. Behaviour, not wording (#165 rulings): each reference resolves."""
    phase_md = SKILL_MD.parent.parent / "tp-phase-implement" / "SKILL.md"
    phase_body = phase_md.read_text(encoding="utf-8")
    auto_section = phase_body.split("\n## Auto Mode", 1)[1].split("\n## ", 1)[0]
    _assert_refs_resolve(auto_section, phase_body)


def _assert_refs_resolve(span: str, *more_docs: str) -> None:
    """Every repo file, `tp-*worker` agent and `## heading` the span cites exists."""
    files = re.findall(r"`((?:skills|agents)/[\w./-]+\.\w+)`", span)
    agents = set(re.findall(r"`(tp-[\w-]*worker)`", span))
    heads = {h.strip() for d in (_body(), *more_docs) for h in re.findall(r"^## (.+)$", d, re.M)}
    assert files and agents and all((REPO_ROOT / f).is_file() for f in files), files
    assert all((REPO_ROOT / "agents" / f"{a}.md").is_file() for a in agents), agents
    assert set(re.findall(r"`## ([^`]+)`", span)) <= heads


# ---------------------------------------------------------------------------
# orchestrator-pipeline-modes — Task 2.1 tests
# ---------------------------------------------------------------------------

PIPELINE_MODES_MD = SKILL_MD.parent / "pipeline-modes.md"


def test_skill_md_line_cap():
    """Task 2.1 — SKILL.md must not exceed the pinned absolute line cap (≤1100).

    The file is grandfathered over the 500-line hard cap; this absolute cap
    assertion bounds creep from future edits.  Pin is set to the post-edit
    count; if SKILL.md is later trimmed, lower the cap accordingly.
    """
    lines = _body().splitlines()
    assert len(lines) <= 1100, (
        f"SKILL.md is {len(lines)} lines — exceeds the 1100-line absolute cap; "
        "move prose to pipeline-modes.md or another companion doc"
    )


def test_pipeline_modes_md_exists():
    """Task 2.1 — pipeline-modes.md companion doc must exist."""
    assert PIPELINE_MODES_MD.exists(), (
        f"pipeline-modes.md must exist at {PIPELINE_MODES_MD}"
    )
