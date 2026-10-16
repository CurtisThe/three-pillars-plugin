#!/usr/bin/env python3
"""bg_wait.py — one bounded wait on a background command (Behavior 2).

design: prompt-cache-aware-dispatch (Task 1.1)

Start form the caller uses (run with `run_in_background`, `<M>` under
`.tp-scratch/bg/`):

    mkdir -p .tp-scratch/bg && rm -f <M> && { <cmd>; } > <M>.out 2> <M>.err; echo $? > <M>

The `mkdir` comes first so the form works on a run that has not used the dir
yet. The command's stdout streams to `<M>.out` while it runs and its stderr to
`<M>.err` — never `2>&1` into the output file, because a caller that reads JSON
out of `<M>.out` (Slot 7's `run_tier_3_5.py` result) must be able to parse it.
The exit code lands in the marker `<M>` only when it finishes. `bg_wait.py --marker <M>` prints exactly
one line — `done <exit>`, `running`, or `error: …` — and exits 0/0/2. While it
prints `running` the caller simply re-runs `bg_wait.py`; each wait is clamped to
`wait_budget.WAIT_BUDGET_S` so it always answers inside the prompt-cache TTL and
never hangs. A missing marker *and* missing output is an error at once.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from wait_budget import WAIT_BUDGET_S


def out_path(marker: Path) -> Path:
    """The output file that pairs with a marker: `<marker>.out`."""
    return marker.with_name(marker.name + ".out")


def read_marker(marker: Path) -> int | None:
    """The marker's exit code; None while it is missing or still empty."""
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not text:
        return None
    return int(text)  # ValueError for a non-integer — the caller reports it


def wait(
    marker: Path,
    *,
    for_s: float = WAIT_BUDGET_S,
    interval_s: float = 5,
    clock=time.monotonic,
    sleep=time.sleep,
) -> tuple[str, int]:
    """Wait up to `for_s` (clamped to the budget) for the marker to hold an int."""
    marker = Path(marker)
    if not marker.exists() and not out_path(marker).exists():
        return f"error: no marker or output for {marker}", 2
    deadline = clock() + max(0.0, min(float(for_s), WAIT_BUDGET_S))
    while True:
        try:
            code = read_marker(marker)
        except ValueError:
            return f"error: marker {marker} holds no exit code", 2
        if code is not None:
            return f"done {code}", 0
        remaining = deadline - clock()
        if remaining <= 0:
            return "running", 0
        sleep(min(interval_s, remaining))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--marker", required=True, type=Path)
    parser.add_argument("--for", dest="for_s", type=int, default=WAIT_BUDGET_S)
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args(argv)
    line, exit_code = wait(args.marker, for_s=args.for_s, interval_s=args.interval)
    print(line)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
