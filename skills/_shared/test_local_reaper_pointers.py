"""test_local_reaper_pointers.py — the docs that hand stop handling to `local-reaper.md`
(m44-orphan-reaper Phase 3).

`local-reaper.md` is the one main-thread protocol for stopping a runaway local attempt; the
docs a dispatcher or orchestrator follows point to it at the site where the stop happens.
Pinned by token per site (section- or step-scoped), not by prose. One block per doc, so later
tasks append their own sites (`tp-phase-implement`, `tp-run-full-design`) below.
"""
from __future__ import annotations

from pathlib import Path

import skill_text

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REAPER = "local-reaper.md"


def _read(rel: str) -> str:
    """A doc under the framework root, by its repo-relative path."""
    if rel == "skills/tp-run-full-design/SKILL.md":
        return skill_text.read_skill_text("tp-run-full-design")
    return (ROOT / rel).read_text(encoding="utf-8")


def _slice(text: str, head: str, nxt: str) -> str:
    """``text`` from ``head`` up to the next ``nxt`` (or the end), raw."""
    start = text.index(head)
    end = text.find(nxt, start + len(head))
    return text[start:end if end != -1 else len(text)]


def _between(text: str, head: str, nxt: str) -> str:
    """``_slice``, whitespace-normalized so a pinned phrase may wrap across lines."""
    return " ".join(_slice(text, head, nxt).split())


# --- skills/_shared/local-dispatch.md (Task 3.2) --------------------------------------------

DISPATCH = _read("skills/_shared/local-dispatch.md")
DISPATCH_SEC3 = _slice(DISPATCH, "\n## 3.", "\n## 4.")


def _dispatch_local_step(n: int) -> str:
    """§3 "Local rung" numbered step ``n`` (a line-start ``n. `` up to ``n + 1. ``)."""
    local = DISPATCH_SEC3[DISPATCH_SEC3.index("**Local rung"):]
    return _between(local, f"\n{n}. ", f"\n{n + 1}. ")


def test_dispatch_step1_settles_90():
    step = _dispatch_local_step(1)
    assert "**Orphan check**" in step
    assert "attempt_watchdog.py orphans --dir <L> --phase <N> --settle-s 90" in step


def test_dispatch_step5_points_to_reaper():
    step = _dispatch_local_step(5)
    assert step.startswith("5. On `runaway`")
    assert "TaskStop(<agent id>)" in step
    assert "attempt_watchdog.py orphan-mark --state <W>" in step
    fallback = step[step.index("orphan-mark"):]
    assert REAPER in fallback and "trigger" in fallback


def test_dispatch_section5_points_to_reaper():
    sec5 = _between(DISPATCH, "\n## 5. Full-design differences", "\n## 6.")
    assert REAPER in sec5
    assert "orphan-mark" in sec5 and "TaskStop" in sec5


# --- skills/tp-phase-implement/SKILL.md (Task 3.3) ------------------------------------------

PHASE_IMPL = _read("skills/tp-phase-implement/SKILL.md")


def test_phase_implement_step_4b_sweeps():
    """The existing step 4b (``--local`` only) runs the interactive sweep, incl. on env-error."""
    step = _between(PHASE_IMPL, "\n4b. **Local ladder (`--local` only).**", "\n")
    assert REAPER in step
    assert "attempt_reaper.py sweep" in step
    assert "env-error" in step


def test_phase_implement_step_4b_sweep_is_interactive_only():
    """Audit m2: a full-design tp-worker (``--auto``) never runs the sweep itself."""
    step = _between(PHASE_IMPL, "\n4b. **Local ladder (`--local` only).**", "\n")
    assert ("(interactive only; under full-design the orchestrator sweeps per "
            "`local-reaper.md` §Full-design)") in step


# --- skills/tp-run-full-design/SKILL.md (Task 3.4) ------------------------------------------

RUN_FULL = _read("skills/tp-run-full-design/SKILL.md")


def test_run_full_design_slot7_points_to_reaper():
    """Slot 7: the background dispatch and the reaper loop are `--local`-only."""
    slot7 = _between(RUN_FULL, "\n### Slot 7 — `phase-implement`", "\n### ")
    assert REAPER in slot7
    sentence = next((s for s in slot7.split(". ") if "run_in_background=True" in s), "")
    assert "`--local` only" in sentence and REAPER in sentence


def test_run_full_design_dispatch_points_to_reaper():
    """The nested dispatch names the reaper; every rung spawns, so no row stays inline."""
    sec = _between(RUN_FULL, "\n## Phase-implement dispatch — nested per task", "\n## ")
    assert REAPER in sec
    assert "stay inline" not in sec
