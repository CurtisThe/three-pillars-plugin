"""design_run_send.py — deliver one line into a design run's Claude input box.

`tmux send-keys` into a Claude Code TUI can leave the text sitting unsent in the input
box (a first message, a later relay). `deliver` types the line the careful way: wait for
the input box, clear it with `C-e C-u` (never `Escape`: it interrupts a working run),
`send-keys -l`, `Enter`, then re-read the box; text still there gets one more `Enter`.
Dim text after the prompt char is the TUI's autocomplete ghost, i.e. an empty box.
A selection menu (`❯ 1. Yes`, `Do you want to`) is never the input box: with one showing
`deliver` sends no keys (it would answer the menu). A typed line that still reads not-delivered
or unverified is confirmed from the transcript (`in_transcript`: the line above an empty box)
before that outcome is reported; text still in the box stays not-delivered.
Outcomes: delivered | unverified | not-delivered | menu | no-session | tmux-error.
Every tmux, clock and sleep call is injectable (design-run-launch.md).

CLI: design_run_send.py <slug> <line>    # exit 0 on delivered, 1 otherwise
"""
from __future__ import annotations

import os
import re
import shlex
import sys
import time
from typing import Callable, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_tmux as drt  # noqa: E402

DELIVERED, UNVERIFIED, NOT_DELIVERED = "delivered", "unverified", "not-delivered"
MENU = "menu"
NO_SESSION, TMUX_ERROR = "no-session", "tmux-error"
PROMPT_CHARS = (">", "❯")
MENU_CURSOR = "❯"  # a menu row is `❯ <n>.`; the input box prompt is `>`
BOX_CHARS = " │┃|"
POLL_SECONDS = 1.0
SETTLE_SECONDS = 0.5
CONFIRM_SECONDS = 30.0  # how long a typed line may take to show in the transcript
MENU_TAIL_LINES = 8

_CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")
_MENU_ROW = re.compile(r"^\d+\.\s")
_tmux_runner = drt._tmux_runner


def manual_command(slug: str, line: str) -> str:
    """The command that re-delivers `line` to `<slug>`'s run by hand."""
    return f"python3 {os.path.abspath(__file__)} {slug} {shlex.quote(line)}"


def _dim_after(params: "list[int]", dim: bool) -> bool:
    """The dim/grey state after one SGR sequence (`ESC[...m`) given its parameters."""
    i = 0
    while i < len(params):
        p = params[i]
        if p in (0, 22, 39):
            dim = False
        elif p in (2, 90):
            dim = True
        elif p in (38, 48) and i + 1 < len(params) and params[i + 1] in (5, 2):
            n = 2 if params[i + 1] == 5 else 4  # 38;5;N / 38;2;R;G;B
            args = params[i + 1:i + 1 + n]
            if p == 38 and len(args) == n:
                dim = (240 <= args[1] <= 250) if n == 2 else args[1] == args[2] == args[3] <= 160
            i += n
        elif 30 <= p <= 37 or 1 == p:
            dim = False
        i += 1
    return dim


def _styled_chars(line: str) -> "list[tuple[str, bool]]":
    """`line` as (char, dim) pairs: escape sequences removed, SGR dim state tracked."""
    out, dim, pos = [], False, 0
    for m in _CSI.finditer(line):
        out += [(c, dim) for c in line[pos:m.start()]]
        if m.group(2) == "m":
            dim = _dim_after([int(x) for x in m.group(1).split(";") if x.isdigit()] or [0], dim)
        pos = m.end()
    return out + [(c, dim) for c in line[pos:]]


def _box(frame: str) -> "Optional[tuple[int, str, bool]]":
    """`(line index, text, ghost)` of the last input-box line, else None (see `box_text`)."""
    lines = frame.splitlines()
    for idx in range(len(lines) - 1, -1, -1):
        chars = _styled_chars(lines[idx])
        i = 0
        while i < len(chars) and chars[i][0] in BOX_CHARS:
            i += 1
        if i < len(chars) and chars[i][0] in PROMPT_CHARS:
            if chars[i][0] == MENU_CURSOR and _MENU_ROW.match("".join(c for c, _ in chars[i + 1:]).lstrip(BOX_CHARS)):
                continue  # a selection-menu row, not the input box
            rest = [(c, d) for c, d in chars[i + 1:] if c not in BOX_CHARS]
            text = "".join(c for c, _ in chars[i + 1:]).strip(BOX_CHARS)
            return idx, text, bool(rest) and all(d for _, d in rest)
    return None


def box_text(frame: str) -> "Optional[tuple[str, bool]]":
    """`(text, ghost)` of the last input-box line in a `capture-pane -p -e` frame, else None.

    The prompt line is the last line whose text, past box chars and spaces, starts with `>`
    or `❯` and is not a numbered menu row (`❯ <n>.`; typed `> 1. ...` is input text). `ghost` is True when all the text after the prompt char is dim/grey."""
    found = _box(frame)
    return found[1:] if found else None


def _plain(line: str) -> str:
    return "".join(c for c, _ in _styled_chars(line)).strip(BOX_CHARS)


def in_transcript(frame: str, line: str) -> bool:
    """True when `line` shows in the transcript ABOVE an empty or ghost input box: the TUI took
    it. Text still inside the box is unsent and never counts. Wrapped lines are joined."""
    found = _box(frame)
    if found is None or not _is_empty(found[1:]):
        return False
    above = " ".join(_plain(ln) for ln in frame.splitlines()[:found[0]])
    return " ".join(line.split()) in " ".join(above.split())


def has_menu(frame: str) -> bool:
    """True when the frame shows a selection menu (a `❯ <n>.` row, or `Do you want to` in
    its last lines): keys sent now would answer it, not type into the input box."""
    plain = [_plain(ln) for ln in frame.splitlines()]
    return (any(ln[:1] == MENU_CURSOR and _MENU_ROW.match(ln[1:].lstrip(BOX_CHARS))
                for ln in plain if ln)
            or any("Do you want to" in ln for ln in plain[-MENU_TAIL_LINES:]))


def _frame(runner: drt.Runner, wid: str) -> Optional[str]:
    rc, out = runner(["capture-pane", "-p", "-e", "-t", wid])
    return out if rc == 0 else None


def _is_empty(box: "Optional[tuple[str, bool]]") -> bool:
    return box is not None and (not box[0] or box[1])


def deliver(slug: str, line: str, runner: Optional[drt.Runner] = None, *,
            ready_timeout: float = 30.0, clock: Callable[[], float] = time.monotonic,
            sleep: Callable[[float], None] = time.sleep) -> str:
    """Type `line` into `<slug>`'s run window (lowest-index window) and press Enter."""
    runner = runner or _tmux_runner()
    if runner is None or runner(["has-session", "-t", f"={slug}"])[0] != 0:
        return NO_SESSION
    wid = drt.run_window(runner, slug)
    if wid is None:
        return NO_SESSION
    deadline = clock() + ready_timeout
    while True:  # wait for the input box to exist
        frame = _frame(runner, wid)
        if frame is not None and has_menu(frame):
            return MENU
        if frame is not None and box_text(frame) is not None:
            break
        left = deadline - clock()
        if left <= 0:
            return UNVERIFIED
        sleep(min(POLL_SECONDS, left))
    for keys in (["C-e"], ["C-u"], ["-l", line], ["Enter"]):
        if runner(["send-keys", "-t", wid, *keys])[0] != 0:
            return TMUX_ERROR
    outcome = NOT_DELIVERED
    for attempt in range(2):  # check, then one more Enter if the text is still in the box
        sleep(SETTLE_SECONDS)
        frame = _frame(runner, wid)
        if frame is not None and has_menu(frame):
            return MENU  # never press Enter into a menu
        box = box_text(frame) if frame is not None else None
        if box is None:
            outcome = UNVERIFIED
            break
        if _is_empty(box):
            return DELIVERED
        if attempt == 0 and runner(["send-keys", "-t", wid, "Enter"])[0] != 0:
            return TMUX_ERROR
    return _confirm(runner, wid, line, outcome, clock() + min(ready_timeout, CONFIRM_SECONDS),
                    clock, sleep)


def _confirm(runner: drt.Runner, wid: str, line: str, outcome: str, deadline: float,
             clock: Callable[[], float], sleep: Callable[[float], None]) -> str:
    """`outcome` (not-delivered / unverified, after typing) becomes delivered once the frame
    shows `line` in the transcript above an empty box: the TUI can take the Enter seconds late
    while it starts (seen 2026-10-09). Polls until `deadline`; types nothing."""
    while True:
        frame = _frame(runner, wid)
        if frame is not None and in_transcript(frame, line):
            return DELIVERED
        left = deadline - clock()
        if left <= 0:
            return outcome
        sleep(min(POLL_SECONDS, left))


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: design_run_send.py <slug> <line>", file=sys.stderr)
        return 2
    outcome = deliver(argv[0], argv[1], _tmux_runner())
    print(f"{outcome}: {argv[0]}")
    return 0 if outcome == DELIVERED else 1


if __name__ == "__main__":
    sys.exit(main())
