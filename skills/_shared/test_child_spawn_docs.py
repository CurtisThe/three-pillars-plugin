#!/usr/bin/env python3
"""test_child_spawn_docs.py — the `child-spawn.md` site protocol stays true to the CLI.

design: strata-session-isolation 5.1 (+ 5.2 for the S1 wiring). The doc is what a site
(local-dispatch, cheap-dispatch, council, tp-pr-iterate) follows when it spawns a Strata agent, so
three things must hold: every command line it shows is a subcommand the CLI actually accepts, the
in-process fallback carries the one log line that makes the lost server review visible, and the stop
rules are stated (the recorded process group, never a process name) with the Bash-timeout form.
Site S1 (`local-dispatch.md`) and site S2 (`cheap-dispatch.md` §Local rung) must name the
protocol's commands where their own steps run them. Sites S3 (`council/strata-members.md`) and
S4 (`tp-pr-iterate/strata-finders.md`) spawn through the loop in `strata-spawn.md`, so that loop
and those two docs' own spawn steps and hard-cap lines carry them too (5.4). Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402

DOC = (HERE / "child-spawn.md").read_text(encoding="utf-8")
LOCAL = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
CHEAP = (HERE / "cheap-dispatch.md").read_text(encoding="utf-8")
SPAWN = (HERE / "strata-spawn.md").read_text(encoding="utf-8")
MEMBERS = (HERE.parent / "council" / "strata-members.md").read_text(encoding="utf-8")
FINDERS = (HERE.parent / "tp-pr-iterate" / "strata-finders.md").read_text(encoding="utf-8")

IN_PROCESS_LINE = "[child-spawn] in-process: <why> (server review lost for this session)"


def _subcommands() -> dict:
    parser = child_spawn._parser()
    subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return subs.choices


def test_doc_subcommands_exist():
    """Every `child_spawn.py <word>` the doc shows is a real subcommand of the CLI."""
    words = re.findall(r"child_spawn\.py\s+([a-z][a-z-]*)", DOC)
    assert words, "doc shows no child-spawn commands at all"
    assert set(words) <= set(_subcommands()), (
        f"doc names subcommands the CLI has no parser for: {sorted(set(words) - set(_subcommands()))}"
    )


def test_in_process_line():
    """The in-process fallback carries the log-line contract (design B8)."""
    assert " ".join(IN_PROCESS_LINE.split()) in " ".join(DOC.split())


def test_never_kill_by_name_and_timeout():
    """Signals go only to the recorded process group, and start/wait state the Bash timeout."""
    assert "recorded process group" in " ".join(DOC.split())
    assert "timeout 300000" in DOC
    timed = [ln for ln in DOC.splitlines() if "timeout 300000" in ln]
    assert any("start" in ln and "wait" in ln for ln in timed), (
        "the line stating timeout 300000 must name both start and wait"
    )


def test_local_dispatch_wired():
    """S1 (`local-dispatch.md`) follows the site protocol: probe/start/stop in §3, sweep in §1/§5."""
    assert "child-spawn.md" in LOCAL
    sec3 = LOCAL.split("## 3. Spawn templates", 1)[1].split("## 4. Halt", 1)[0]
    for needle in ("child_spawn.py probe", "child_spawn.py start", "child_spawn.py stop"):
        assert " ".join(sec3.split()).count(needle) >= 1, needle
    steps = [s for s in re.split(r"\n(?=\d+\. )", sec3) if "TaskStop(" in s]
    assert steps, "no §3 step names TaskStop("
    assert all("child_spawn.py stop" in " ".join(s.split()) for s in steps), (
        "the §3 step naming TaskStop( must name child_spawn.py stop for a child spawn"
    )
    sec1 = LOCAL.split("## 1. Preflight", 1)[1].split("## 2. Per row", 1)[0]
    sec5 = LOCAL.split("## 5. Full-design differences", 1)[1].split("## 6.", 1)[0]
    assert "child_spawn.py sweep" in " ".join(sec1.split())
    assert "child_spawn.py sweep" in " ".join(sec5.split())


def test_cheap_dispatch_wired():
    """S2 (`cheap-dispatch.md` §Local rung) follows the site protocol: probe/start/stop.

    design: strata-session-isolation 5.3. The section must cite the protocol and name every
    subcommand where its own steps run it — step 1 probes then starts the child, step 5 names
    `child_spawn.py stop` where it names `TaskStop`."""
    assert "child-spawn.md" in CHEAP
    local = CHEAP.split("## Local rung", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(local.split())
    for needle in ("child_spawn.py probe", "child_spawn.py start", "--site S2",
                   "child_spawn.py wait", "child_spawn.py stop"):
        assert needle in flat, needle
    step5 = re.search(r"^5\. .*?(?=^6\. |\Z)", local, re.S | re.M)
    assert step5, "§Local rung has no step 5"
    assert "child_spawn.py stop" in " ".join(step5.group(0).split())


def _bold_step(text: str, head: str, n: int) -> str:
    """Step *n* (`N. **`) under heading `head`, up to step n+1 or the next heading."""
    sec = text.split(head, 1)[1]
    m = re.search(rf"^{n}\. \*\*.*?(?=^{n + 1}\. \*\*|^## |\Z)", sec, re.S | re.M)
    assert m, f"{head} has no step {n}"
    return " ".join(m.group(0).split())


def _num_step(text: str, head: str, n: int) -> str:
    """Step *n* (`N. `) under heading `head`, up to step n+1 or the next heading."""
    sec = text.split(head, 1)[1]
    m = re.search(rf"^{n}\. .*?(?=^{n + 1}\. |^## |\Z)", sec, re.S | re.M)
    assert m, f"{head} has no step {n}"
    return " ".join(m.group(0).split())


def test_strata_spawn_wired():
    """S3/S4's shared loop (`strata-spawn.md`) spawns and waits through the child CLI.

    design: strata-session-isolation 5.4. Step 3 (Spawn) names `child_spawn.py start`, step 6
    (Release) names `child_spawn.py wait` with the 120 s per-call budget, and the doc cites the
    site protocol it follows."""
    assert "child-spawn.md" in SPAWN
    assert "child_spawn.py start" in _bold_step(SPAWN, "## The loop, per spawn", 3)
    step6 = _bold_step(SPAWN, "## The loop, per spawn", 6)
    assert "child_spawn.py wait" in step6
    assert "--budget-s 120" in step6


def test_hard_caps_name_stop():
    """S3/S4 hard-cap lines stop a child with `child_spawn.py stop`, never only `TaskStop`."""
    for name, text in (("strata-members.md", MEMBERS), ("strata-finders.md", FINDERS)):
        lines = [ln for ln in text.splitlines() if "TaskStop" in ln]
        assert lines, f"{name} names no TaskStop"
        bad = [ln for ln in lines if "child_spawn.py stop" not in ln]
        assert bad == [], (name, bad)


def test_site_spawns_wired():
    """Each S3/S4 spawn step cites the site protocol and starts a child; S3 and the S4 scout wait on it."""
    blocks = {
        "strata-members.md step 3": _num_step(MEMBERS, "## Serial members", 3),
        "strata-finders.md scout step 2": _num_step(FINDERS, "## Context scout", 2),
        "strata-finders.md §Serial finders": FINDERS.split("## Serial finders", 1)[1]
        .split("decide <attempt> <served> review_finder", 1)[0],
    }
    for name, block in blocks.items():
        assert "child_spawn.py start" in " ".join(block.split()), name
    for name in ("strata-members.md step 3", "strata-finders.md scout step 2"):
        flat = " ".join(blocks[name].split())
        for needle in ("child_spawn.py wait", "--reply-out"):
            assert needle in flat, (name, needle)
