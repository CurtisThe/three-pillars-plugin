#!/usr/bin/env python3
"""context_rollover_plan.py - what a rollover saves into, and when background agents hold it.

design: fleet-watcher-reliability (Task 1.3). Two decisions the driver used to make
implicitly, now named and testable:

- **The target.** A run is *live* when `tp-designs/<slug>/` exists (save with
  `/tp-session-save`, restore with `/tp-session-restore`), *archived* when that dir is
  absent and `completed-tp-designs/<slug>/` exists (Tier 5.6 moved it; `/tp-session-save`
  refuses without the live dir, so the save line asks for the handoff at the completed-dir
  path under the same six headings, and the resume line reads it back with no restore
  step), and *no target* (`None`) otherwise: a seed-only run, a slug mismatch.
- **The ask.** `only_background` is True when background agents are the one thing holding
  the run: the classifier's kind is `background` and, with the background lines taken out,
  the pane and transcript are at a turn boundary. `ask_line` is the one save-and-wait
  line the driver then types.

The target's lines are single lines on purpose: each is typed into the input box and
submitted once. Stdlib only; reads directory existence and nothing else.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover as cr  # noqa: E402
import pane_activity  # noqa: E402

__all__ = ["DOCS", "RESUME_LINE", "HEADINGS", "Target", "save_line", "restore_line",
           "resume_line", "live_target", "archived_target", "target", "ask_line",
           "only_background"]

DOCS = "three-pillars-docs"
# A template: `resume_line(slug)` fills `{slug}`; never send RESUME_LINE itself.
RESUME_LINE = ("Continue this design run from its handoff: read "
               "three-pillars-docs/tp-designs/{slug}/handoff.md and resume exactly "
               "where it stopped.")
# The headings `/tp-session-save` writes, in its order.
HEADINGS = ("Phase", "Decisions", "State", "Next", "Open Questions", "Carried Forward")


@dataclass(frozen=True)
class Target:
    """Where this run's handoff lives and the lines that save it and resume from it.

    `handoff_path` is relative to the run's worktree (posix). `restore_line` is None for
    an archived run: there is no `/tp-session-restore` without the live dir, so the resume
    line is sent straight after `/clear`.
    """
    handoff_path: str
    save_line: str
    restore_line: Optional[str]
    resume_line: str


def save_line(slug: str) -> str:
    return f"/tp-session-save {slug}"


def restore_line(slug: str) -> str:
    return f"/tp-session-restore {slug}"


def resume_line(slug: str) -> str:
    """The live resume line, naming this run's own handoff (never a `<slot>` placeholder)."""
    return RESUME_LINE.format(slug=slug)


def live_target(slug: str) -> Target:
    """The live target, built from the slug alone (no file is read)."""
    return Target(f"{DOCS}/tp-designs/{slug}/handoff.md", save_line(slug),
                  restore_line(slug), resume_line(slug))


def archived_target(slug: str) -> Target:
    path = f"{DOCS}/completed-tp-designs/{slug}/handoff.md"
    return Target(
        path,
        (f"Write a handoff for this design run to {path} (gitignored, never committed) "
         f"under the headings {', '.join(HEADINGS[:-1])} and {HEADINGS[-1]}, then stop "
         f"and wait."),
        None,
        f"Continue this design run from its handoff: read {path} and resume exactly "
        f"where it stopped.")


def target(worktree: str, slug: str) -> Optional[Target]:
    """The rollover target for `<slug>` in `worktree`, from which design dir exists.

    The live dir wins over the completed dir; neither is None.
    """
    root = Path(worktree, DOCS)
    if (root / "tp-designs" / slug).is_dir():
        return live_target(slug)
    if (root / "completed-tp-designs" / slug).is_dir():
        return archived_target(slug)
    return None


def ask_line(target: Target, size: int) -> str:
    """The one save-and-wait line sent to a run that background agents are holding."""
    return (f"Context is at {size} tokens and this run is due for a rollover, but "
            f"background agents are still running. Wait for them to finish, then do "
            f"this and stop: {target.save_line}")


def only_background(records: "list[dict]", pane, idle_s: float) -> bool:
    """True when background agents are the only thing between this run and a boundary.

    The classifier must name `background` (a shell, spinner or card outranks it), and the
    pane minus its background lines plus the transcript must be a turn boundary. The idle
    stretch was already waited out by the caller, so it is passed as satisfied.
    """
    if pane_activity.classify(pane).kind != "background":
        return False
    rest = "\n".join(ln for ln in pane.splitlines()
                     if not pane_activity.is_background_line(ln))
    return cr.at_turn_boundary(records, rest, idle_s, idle_s)[0]
