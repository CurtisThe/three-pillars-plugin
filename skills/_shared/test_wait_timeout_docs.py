#!/usr/bin/env python3
"""test_wait_timeout_docs.py — no shipped doc wraps a wait in a Bash timeout above the cache TTL,
and none tells the dispatcher to poll with a sleep loop.

design: strata-spend-leaks (Task 2.2), extended by prompt-cache-aware-dispatch (Task 1.6,
Behaviour 3; Task 1.9 closes the two gaps that lint's own examples left). Task 1.4 cut every wait
*default* to `wait_budget.WAIT_BUDGET_S` (270 s, inside the 300 s subagent cache TTL), but the prose
that runs those waits still wrapped them in `timeout 600000`, so the dispatcher woke after the TTL
had passed and re-wrote its whole context on every wake (design.md bug 3). These guards read the
shipped skill/agent docs — prose a dispatcher executes literally — and never `three-pillars-docs/`,
whose design logs record the old numbers as history (`skills/_shared/test-fragility.md`: match by
pattern, pin the shipped surface only).

- `test_no_bash_timeout_above_ttl`: every 5+-digit `timeout` in a shipped doc is at most
  `wait_budget.BASH_TIMEOUT_MS`. There is no allow list: the one line that needed the Bash tool's
  600000 ms maximum was the Tier 3.5 phase re-run, and Task 1.6 moved that to the background.
- `test_background_exemption_is_only_a_real_start_form`: the `BACKGROUND_RE` exemption is a *start*
  form, never a passing mention. A line that says the call runs in the foreground ("never
  `run_in_background`") keeps its timeout checked; only a line that actually starts a background
  command — an explicit `run_in_background` true, or a command ending in `&` — is exempt.
- `test_no_poll_loop_in_dispatch_prose`: the *dispatch* prose — the files that actually spawn and
  wait for workers — never tells the caller to poll with an `until`/`while ... do ... sleep` loop.
  The scan reads each file's WHOLE text and maps a match offset to a line number, so a loop written
  across several lines of prose is caught too. The pattern is `wait_ttl_hook.POLL_LOOP_RE`, the same
  one the runtime hook warns on, so prose and hook cannot drift apart.
- `test_poll_loop_pattern_examples`: that pattern matches a real poll loop (one-line and multi-line)
  and not ordinary prose — not prose that merely says "until", and not prose that says "do not
  sleep", where `do` starts no command.
- `test_no_540_second_wait_prose`: no shipped doc still says a wait runs 540 s.

Scope is design.md's own words — "any SKILL.md that cites `timeout 600000` *for a wait*". A
`run_in_background` Bash call never blocks the turn that launched it, so the TTL argument does not
reach it: `local-reaper.md`'s watch (7200000 ms over `attempt_reaper.MAX_WATCH_S` = 7000 s, seat
ruling 2026-10-02) is one, and `test_local_reaper_docs.py` pins it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import skill_text  # noqa: E402
import wait_budget  # noqa: E402
import wait_ttl_hook  # noqa: E402

ROOT = HERE.parent.parent  # the repo root; `skills/` and `agents/` sit under it

# The plan's literal: `timeout` / `timeout:` / an inline code span, then a 5+-digit ms value.
TIMEOUT_RE = re.compile(r"timeout:? *`?(\d{5,})")
# Prose that still describes a wait as running 540 s — the pre-Task-1.4 budget.
SEC_540_RE = re.compile(r"540 *s|up to 540")
# A background Bash call is not a wait the dispatcher sits in (see the docstring). The exemption is
# a START form: an explicit `run_in_background` true, a line whose own prose starts a background
# call ("one background Bash call (`run_in_background`, …)"), or a command ending in `&`. A mention
# of the flag is not a start, and a line that puts the call in the foreground ("never
# `run_in_background`", "in the foreground") is a foreground wait — its timeout stays checked.
BACKGROUND_RE = re.compile(r"run_in_background(`|\s*[:=]\s*[Tt]rue)|\bbackground\b|&\s*$")
FOREGROUND_RE = re.compile(r"\bnever\b|\bforeground\b")

# The lint's own example lines — never text taken from a shipped doc.
FG_NEVER_BG = "run it in the foreground, never `run_in_background`, with timeout 600000"
BG_START_COLON = "start it with `run_in_background: true` and Bash timeout 600000"
BG_START_EQUALS = "start it with `run_in_background=True` and Bash timeout 600000"
BG_START_AMP = "mkdir -p .tp-scratch/bg && { pytest -n 4; } > .tp-scratch/bg/M.out 2> .tp-scratch/bg/M.err &"
FG_NEVER_STARTED = "never start it in the background; run it with timeout 600000"
# A poll loop written the way prose writes it: the header, `do`, the `sleep`, `done` on their own
# lines. Only a whole-text scan sees it.
POLL_LOOP_MULTILINE = "until test -f .plan-audit-pass.json\ndo\n  sleep 5\ndone"
# Prose that tells the caller NOT to sleep: `do` starts no command, so it is not a loop.
PROSE_DO_NOT_SLEEP = "repeated while it prints `running`; do not sleep between polls"


def _doc_paths() -> list[Path]:
    """Every shipped skill/agent markdown: `skills/**/*.md` and top-level `agents/*.md`."""
    paths = sorted((ROOT / "skills").rglob("*.md"))
    paths += sorted(p for p in (ROOT / "agents").glob("*.md") if p.is_file())
    return paths


def _dispatch_paths() -> list[Path]:
    """The prose that spawns and waits for workers: the shared dispatch notes, the full-design
    skill end to end, and the worker agent itself."""
    paths = sorted(p for p in (ROOT / "skills" / "_shared").glob("*.md") if p.is_file())
    paths += sorted((ROOT / "skills" / "tp-run-full-design").rglob("*.md"))
    paths.append(ROOT / "agents" / "tp-worker.md")
    return paths


RUN_FULL_DESIGN_SKILL = ROOT / "skills" / "tp-run-full-design" / "SKILL.md"


def _text(path: Path) -> str:
    if path == RUN_FULL_DESIGN_SKILL:
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def _lines(paths: list[Path]) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in paths:
        for n, line in enumerate(_text(path).splitlines(), 1):
            out.append((path.relative_to(ROOT).as_posix(), n, line))
    return out


def _over_budget(line: str) -> list[int]:
    """Every 5+-digit timeout on `line` above `wait_budget.BASH_TIMEOUT_MS`."""
    return [int(m.group(1)) for m in TIMEOUT_RE.finditer(line)
            if int(m.group(1)) > wait_budget.BASH_TIMEOUT_MS]


def _flagged(line: str) -> bool:
    """True when the lint checks `line`: an over-budget timeout that is not a background start."""
    if not _over_budget(line):
        return False
    return not BACKGROUND_RE.search(line) or bool(FOREGROUND_RE.search(line))


def test_no_bash_timeout_above_ttl():
    """No shipped doc names a Bash timeout above `wait_budget.BASH_TIMEOUT_MS` in the foreground."""
    over = [(file, n, line.strip()[:80])
            for file, n, line in _lines(_doc_paths()) if _flagged(line)]
    assert over == [], over


def test_background_exemption_is_only_a_real_start_form():
    """A line that says the call runs foreground is checked; only a real start form is exempt."""
    for foreground in (FG_NEVER_BG, FG_NEVER_STARTED):
        assert _flagged(foreground), foreground
    for start in (BG_START_COLON, BG_START_EQUALS, BG_START_AMP):
        assert not _flagged(start), start


def _poll_loop_hits(paths: list[Path]) -> list[tuple[str, int, str]]:
    """`(file, line, snippet)` per `POLL_LOOP_RE` match in each file's WHOLE text.

    Whole text, not per-line: the multi-line `until …` / `do` / `sleep …` / `done` a fenced block
    can carry matches only across line boundaries. The match offset maps back to the line the
    header sits on, so a failure still points a reader at the prose.
    """
    hits: list[tuple[str, int, str]] = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
        text = _text(path)
        for match in wait_ttl_hook.POLL_LOOP_RE.finditer(text):
            hits.append((rel, text.count("\n", 0, match.start()) + 1, match.group(0)[:80]))
    return hits


def test_no_poll_loop_in_dispatch_prose():
    """No dispatch prose tells the caller to poll with a sleep loop — it waits through bg_wait."""
    assert _poll_loop_hits(_dispatch_paths()) == []


def test_the_prose_scan_reads_whole_text_not_single_lines(tmp_path: Path):
    """A multi-line `until … do … sleep … done` inside a prose file goes red, with its line."""
    doc = tmp_path / "prose.md"
    doc.write_text("Wait for the marker:\n\n" + POLL_LOOP_MULTILINE + "\n", encoding="utf-8")
    hits = _poll_loop_hits([doc])
    assert len(hits) == 1, hits
    assert hits[0][0].endswith("prose.md"), hits
    assert hits[0][1] == 3, hits  # the `until` header's line, not the file's start


def test_poll_loop_pattern_examples():
    """`POLL_LOOP_RE` matches a poll loop, one-line or multi-line, and not prose around it."""
    loops = [
        'until git -C <wt> log --oneline -1 | grep -q "2.1"; do sleep 5; done',
        "while true; do sleep 5; done",
        POLL_LOOP_MULTILINE,
    ]
    assert all(wait_ttl_hook.POLL_LOOP_RE.search(s) for s in loops), loops
    for prose in ("Do not proceed until the user resolves it.", PROSE_DO_NOT_SLEEP):
        assert not wait_ttl_hook.POLL_LOOP_RE.search(prose), prose


def test_no_540_second_wait_prose():
    """No shipped doc still says a wait runs 540 s — the budget is `wait_budget.WAIT_BUDGET_S`."""
    stale = [(file, n, line.strip()[:80]) for file, n, line in _lines(_doc_paths())
             if SEC_540_RE.search(line)]
    assert stale == [], stale
