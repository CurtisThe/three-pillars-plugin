#!/usr/bin/env python3
"""pane_activity.py — the one classifier of what a run's pane is doing.

design: fleet-watcher-reliability (Task 1.1). The rollover boundary, the delivery verdict
and the seat's status table all read the same pane text; before this they each searched it
their own way, so a run with `1 shell still running` looked idle to the rollover (it got
`/clear`ed mid-merge) while the word `background` in prose 13 lines above the bottom held
a run that was genuinely parked.

`classify(pane)` reads the pane's last `TAIL_LINES` lines and names one kind, in this
precedence: `card`, `shell`, `busy`, `background`, `idle` — plus `unknown` for a pane that
could not be read at all. `Activity.line` is the matched line, one-lined and clipped, for
the table to show. `HOLD_REASONS` is the closed set of kinds that block a turn boundary,
each with the reason a caller prints.

Pure and self-contained: the pane text is the argument, and this module imports nothing
from this repo, so every consumer shares one answer without an import cycle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Activity", "classify", "is_background_line", "CARD_MARKERS", "SPINNER_MARKER",
           "SHELL_RE", "BACKGROUND_RE", "TAIL_LINES", "HOLD_REASONS"]

# mirrors design_run_watch.PROMPT_MARKERS — the card the seat has to answer
CARD_MARKERS = ("Do you want to", "❯ 1.")
SPINNER_MARKER = "esc to interrupt"
SHELL_RE = re.compile(r"\b\d+ shells? still running\b")
# The harness's status line only, by its whole shape: the count opens the line or a `·`-joined
# segment, and the noun closes that segment (`  2 background tasks · ↓ to manage`, `⏵⏵ accept
# edits on · 2 background tasks · ↓ to manage`, `1 background agent running`). Never the bare
# word, a count inside prose, or a reply continuation the TUI wrapped onto its own visual line
# (`  2 background agents to finish; handoff saved.`): a parked run's own reply names background
# agents too, and reading it as `background` would hold the run and swallow its `parked`/`idle`
# events (PR #381 r1, r2, r2.1).
BACKGROUND_RE = re.compile(
    r"(?:^|·)\s*\d+ background (?:agents?|tasks?)(?: running)?\s*(?:·|$)")
TAIL_LINES = 12
MAX_LINE_CHARS = 80

HOLD_REASONS = {
    "card": "a card is open",
    "shell": "a shell is still running",
    "busy": "the run is busy",
    "background": "background agents in the pane",
}


def is_background_line(line: str) -> bool:
    """True when `line` is the harness's background-agent count line. The one test every
    caller uses — `classify`, the rollover's `only_background`, the watcher's idle gate."""
    return BACKGROUND_RE.search(line) is not None


# (kind, matcher) in precedence order: a card outranks a live shell, which outranks a
# spinner, which outranks a background agent.
_MATCHES = (
    ("card", lambda ln: any(m in ln for m in CARD_MARKERS)),
    ("shell", lambda ln: SHELL_RE.search(ln) is not None),
    ("busy", lambda ln: SPINNER_MARKER in ln),
    ("background", is_background_line),
)


@dataclass(frozen=True)
class Activity:
    """What the pane shows: `kind` (the six kinds) and the matched `line` (empty when the
    kind has no line to show — `idle`, `unknown`)."""
    kind: str
    line: str = ""


def _display(line: str) -> str:
    """The matched line as one display line: whitespace collapsed, indentation gone,
    clipped so it can never wrap the status table's row."""
    return " ".join(line.split())[:MAX_LINE_CHARS]


def classify(pane) -> Activity:
    """Name the activity in `pane` (the window's visible text, or None when unreadable).

    Only the last `TAIL_LINES` lines count: the TUI's live frame, not the scrollback above
    it. Never raises.
    """
    if pane is None:
        return Activity("unknown")
    lines = [ln for ln in pane.splitlines()[-TAIL_LINES:] if ln.strip()]
    for kind, matches in _MATCHES:
        for line in lines:
            if matches(line):
                return Activity(kind, _display(line))
    return Activity("idle")
