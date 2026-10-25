"""slow_first.py — order pytest items slowest-first from a previous head's junit report.

design: Task 1.5 of the ci-local-speed-part2 design in this dev repo (the design id is
a dev-repo label only; the module itself ships and reads nothing dev-repo specific).

A 12-minute test that starts last holds the stage's tail: with xdist's load scheduler
the worker that draws it finishes after every other worker has drained, so the stage
pays its duration twice over. A prior head's junit report already carries each test's
duration, so the next run can deal the slowest items into the first chunks and let them
run while everything else drains behind them.

Every reader here is fail-soft by design: junit data is an optimisation, never a
correctness input, so a missing, empty, malformed or DTD-bearing report yields "no
data" (an empty dict / None) rather than an error the caller has to handle.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405 — DTD-free input only (see _DTD)
from pathlib import Path

JUNIT_NAME = "pytest-main.xml"

# Same rule as `scripts/ci_manifest.py`'s `_DTD`: ElementTree resolves external
# entities, so a report that declares one is refused outright.
_DTD = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.I)


def junit_key(nodeid: str) -> tuple[str, str]:
    """The `(classname, name)` pytest writes into its junit report for `nodeid`.

    pytest's own rule (`_pytest.junitxml.mangle_test_address`): partition the address
    at the first `[`, split the path part on `::`, turn the first part's `/` into `.`
    and drop the trailing `.py`, put the parameters back on the last part. The
    classname is every part before the last, joined on `.`.
    """
    path, possible_open_bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = names[0].replace("/", ".").removesuffix(".py")
    names[-1] += possible_open_bracket + params
    return ".".join(names[:-1]), names[-1]


def load(directory: Path) -> dict:
    """`{(classname, name): seconds}` from `directory / JUNIT_NAME`.

    The max time wins when a key appears twice (a re-collected module). Any bad input
    — no file, empty file, malformed XML, a DTD/entity declaration, a non-numeric
    `time` — returns `{}`: no data, never an error.
    """
    try:
        text = (Path(directory) / JUNIT_NAME).read_text(encoding="utf-8")
    except OSError:
        return {}
    if _DTD.search(text):
        return {}
    try:
        root = ET.fromstring(text)  # nosec B314 — DTD-free input only (checked above)
    except (ET.ParseError, ValueError):
        return {}
    durations: dict[tuple[str, str], float] = {}
    for case in root.iter("testcase"):
        try:
            seconds = float(case.get("time", ""))
        except ValueError:
            continue
        key = (case.get("classname", ""), case.get("name", ""))
        if key[1] == "":
            continue
        if seconds > durations.get(key, float("-inf")):
            durations[key] = seconds
    return durations


def order(items, durations: dict, *, key, workers: int = 1) -> list:
    """`items` in descending duration, unknown ones last in their original order.

    `key(item)` is the item's junit address; its duration is looked up under
    `junit_key(key(item))`. With `workers > 1` and at least `2 * workers` items, the
    ranked list is dealt over each worker's first chunk the way xdist's
    `LoadScheduling.schedule` deals them: `chunk = max(len(items) // workers // 4, 2)`
    is its `node_chunksize` with no `--maxschedchunk`, and the ranked item `r` goes to
    position `(r % workers) * chunk + r // workers` (a short list keeps that relative order), so the slowest start on every
    worker at once instead of all landing in one worker's first chunk. A scheduler
    that is not load-based still gets a valid order — just a less even one.
    """
    items = list(items)
    known = [it for it in items if junit_key(str(key(it))) in durations]
    unknown = [it for it in items if junit_key(str(key(it))) not in durations]
    known.sort(key=lambda it: -durations[junit_key(str(key(it)))])
    if workers > 1 and len(items) >= 2 * workers:
        chunk = max(len(items) // workers // 4, 2)
        head = known[:workers * chunk]
        # Order the dealt items by their target slot: a permutation for any len(head),
        # and exactly the xdist deal when head is full (the slots are then 0..n-1).
        slots = sorted(range(len(head)), key=lambda r: (r % workers) * chunk + r // workers)
        dealt = [head[r] for r in slots]
        return dealt + known[workers * chunk:] + unknown
    return known + unknown


def newest_other(parent: Path, head: Path) -> Path | None:
    """The newest sibling head dir under `parent` that holds a `JUNIT_NAME`.

    A previous attempt's report is the one to read. `head` (this attempt's dir) is
    ignored, as is any dir without the main report. Any `OSError` returns None.
    """
    try:
        best: tuple[float, Path] | None = None
        for child in Path(parent).iterdir():
            if not child.is_dir() or child == Path(head):
                continue
            report = child / JUNIT_NAME
            if not report.is_file():
                continue
            mtime = report.stat().st_mtime
            if best is None or mtime >= best[0]:
                best = (mtime, child)
    except OSError:
        return None
    return best[1] if best else None
