"""test_cheap_tier_lever_sites.py — the run flag and the Tier 3 task lever in the docs.

design: cheap-tier-offload (Tasks 4.3, 4.4; D2, D7)

The flag's semantics live once, in `skills/tp-run-full-design/cheap-tier.md`. The
orchestrator's SKILL.md advertises the flag and points there from its flag list,
Tier 1 and Tier 3, and every `--local`-gated tier-table line also names the
cheap-tier task lever. Imports `test_cheap_tier_sites.py`'s helpers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from test_cheap_tier_sites import ROOT, argument_hint, find_violations  # noqa: E402
import skill_text  # noqa: E402

RUN_DIR = ROOT / "skills" / "tp-run-full-design"
DISPATCH_MD = ROOT / "skills" / "_shared" / "local-dispatch.md"
WORKER_MD = ROOT / "agents" / "tp-worker.md"
TASK_TABLE_CMD = "<TP>/skills/_shared/cheap_tier_cli.py task-table"
SKILL_MD = RUN_DIR / "SKILL.md"
CHEAP_MD = RUN_DIR / "cheap-tier.md"
POINTER = "cheap-tier.md"
LEVER = "cheap-tier task lever"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """From `heading` (a whole line) to the next heading of the same or a higher level."""
    depth = len(heading.split(" ", 1)[0])
    start = text.index(f"\n{heading}\n") + 1
    nxt = re.compile(rf"^#{{1,{depth}}} ", re.M).search(text, start + len(heading) + 1)
    return text[start:nxt.start()] if nxt else text[start:]


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return _flat(text[i:text.index(end, i)])


def _line(text: str, needle: str, *, starts: bool = False) -> str:
    for line in text.splitlines():
        if (line.startswith(needle) if starts else needle in line):
            return line
    raise AssertionError(f"no line {'starting with' if starts else 'containing'} {needle!r}")


def test_run_flag_pointers():
    text = skill_text.read_skill_text("tp-run-full-design")
    hint = argument_hint(SKILL_MD)
    assert "[--local] [--cheap-tier[=ab]]" in hint, hint
    flag = _line(_section(text, "## Arguments"), "- `--cheap-tier[=ab]`", starts=True)
    assert POINTER in flag
    assert POINTER in _section(text, "## Tier 1 — Pickup")
    assert POINTER in _section(text, "## Tier 3")
    slot7 = _section(text, "### Slot 7 — `phase-implement`")
    assert "per-task cheap dispatch" in slot7
    compose = _line(text, "worker_prompt = compose(")
    assert "route=R if --local" in compose and "tier_table=T," in compose
    dispatch = _flat(_section(text, "## Phase-implement dispatch — nested per task"))
    assert ("Per-task cheap dispatch is the default: the worker prompt carries the phase's tier table"
            in dispatch)
    step1 = _line(text, "1. **Branch setup**", starts=True)
    assert "retries" in step1 and "ROUTE:" in step1
    assert LEVER in step1 and "CHEAP_TIER:" in step1 and POINTER in step1
    assert "<!-- cheap-tier:" not in text  # the orchestrator holds no stub (7.4)


def test_cheap_tier_md_states_the_semantics():
    doc = _flat(_text(CHEAP_MD))
    assert len(_text(CHEAP_MD).splitlines()) <= 100
    # D2: --local never implies the flag, and wins when both are set.
    assert "`--local` does not imply `--cheap-tier`" in doc
    assert "When both are set, `--local` wins" in doc
    # Tier 1: the raw-config load_slots refusal (plan.md Deviations 7) and its log line.
    tier1 = _flat(_section(_text(CHEAP_MD), "## Tier 1 — the slot preflight"))
    for needle in ("cheap_tier_cli.py slots", "raw", "cheap_tier.load_slots",
                   "load_repo_config", "refuse before Tier 2",
                   "[tp-run-full-design/tier-1] cheap-tier <mode>: slots=<list>",
                   # impl-audit #10: a --local run exports TP_LOCAL for flagless callers
                   "export `TP_LOCAL=on`", "role_engine.run_local"):
        assert needle in tier1, needle
    # Tier 3 (D7): task-table, a CHEAP_TIER line, and no ROUTE line.
    tier3 = _flat(_section(_text(CHEAP_MD), "## Tier 3 — the task lever (D7)"))
    for needle in ("cheap_tier_cli.py task-table", "--cheap-tier <mode>",
                   "`CHEAP_TIER: <mode>` line and **no** `ROUTE:` line", "retries too",
                   "local-dispatch.md", "Exit 1", "Exit 2"):
        assert needle in tier3, needle
    assert "cheap_tier_cli.py spec" not in doc  # spec calls live only in stubs
    assert "skills/_shared/cheap-dispatch.md" in doc
    # impl-audit #9: opus rows spawn (local-dispatch.md §2); ab is not shadow-only
    assert "No row starts on Opus" in tier3 and "spawns its own `opus-*` variant" in tier3
    assert "stay inline" not in doc
    # one-cheap-engine 3.5: `ab` is a deprecated spelling of `on`, so the run doc no
    # longer describes shadow arms — cheap-dispatch.md §`ab` mode is the only place left.
    assert "`--cheap-tier=ab` is deprecated and now runs as `on`" in doc
    assert "Three things still run cheap for real under `ab`" not in doc
    assert "picks shadow A/B" not in doc
    dispatch = _flat(_text(ROOT / "skills" / "_shared" / "cheap-dispatch.md"))
    assert "The task lever is unrouted too" in dispatch
    assert "Only the task lever and the classifier eval have a route source" not in dispatch
    assert "At a pure slot it never changes the real artifact, unless" in dispatch


def test_task_lever_branch():
    """D7: under a `CHEAP_TIER:` line the worker's permission and table come from task-table."""
    doc = _text(DISPATCH_MD)
    step1 = _between(doc, "1. **Permission**", "2. **Override warning**")
    for needle in ("`CHEAP_TIER:`", TASK_TABLE_CMD, "--cheap-tier <mode>", "exit 0",
                   "skip `local_implement_config.py --check full_design`"):
        assert needle in step1, needle
    step5 = _between(doc, "5. **Tier table**", "## 2. Per row")
    assert "`CHEAP_TIER:`" in step5 and "task-table" in step5
    assert "never recomputed through `task_eligibility.py`" in step5
    import test_local_dispatch_literal as literal
    cmds = [c for c in literal.documented_commands() if TASK_TABLE_CMD in c]
    assert cmds and not any(literal.computed(c) for c in cmds), cmds
    worker = _text(WORKER_MD)
    assert "**Tier table (`--local`, or a `CHEAP_TIER:` line)**" in worker
    assert "local-dispatch.md` §1" in _line(worker, "**Tier table (")
    # the worker names no rung (its own `model: sonnet` pin + identity sentence are not rungs)
    rest = "\n".join(line for line in worker.splitlines()
                     if line != "model: sonnet" and "`sonnet` model default" not in line)
    assert re.search("sonnet", rest, re.I) is None


def test_slots_command_exists_and_the_guard_stays_clean():
    import cheap_tier_cli
    assert "slots" in cheap_tier_cli._parser().format_help()
    assert find_violations(ROOT) == []
