"""Prose guard: `local-dispatch.md` runs a local rung under the runaway ceiling, and
`tp-worker` can `TaskStop` it (run-throughput 1.7).

design: run-throughput (Part S, runaway ceiling; detailed-design-runaway.md §Dispatcher
protocol) as retargeted by prompt-cache-aware-dispatch 1.5: `## 3.` now holds ONE background
spawn template for every rung, so this guard reads only that block's protocol prose — from
`**Local rung` to the first line-start fence after the block closes — and leaves the template's
shape to `test_local_dispatch_spawn.py` and the no-ceiling rule to Task 1.4's code test.
hybrid's CONTRACT FIRST / ROUTE text survives.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DISPATCH = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
TP_WORKER_MD = ROOT / "agents" / "tp-worker.md"


def _section(text: str, head: str, nxt: str) -> str:
    start = text.index(head)
    end = text.find(nxt, start + len(head))
    return text[start:end if end != -1 else len(text)]


SEC3 = _section(DISPATCH, "\n## 3.", "\n## 4.")
SEC2 = _section(DISPATCH, "\n## 2.", "\n## 3.")
PY_BLOCKS = re.findall(r"```python\n(.*?)```", SEC3, re.S)


def test_local_template_renders_with_ladder_keys():
    rendered = PY_BLOCKS[0].format(model="haiku", id="1.1", tier="local", rung="local-medium", n=1,
                                   agent_ref="three-pillars:tp-task-worker-local-medium")
    assert 'model="haiku"' in rendered and "task 1.1 local-medium attempt 1" in rendered
    assert 'subagent_type="three-pillars:tp-task-worker-local-medium"' in rendered


def _local_protocol() -> str:
    """The §3 "Local rung" prose, through the one background template, up to the next fence."""
    start = SEC3.index("**Local rung")
    m = re.search(r"```python\n.*?```", SEC3, re.S)
    end = re.compile(r"^```", re.M).search(SEC3, m.end()).start()
    return SEC3[start:end]


def test_local_protocol_names_the_watchdog_steps():
    proto = _local_protocol()
    for needle in ("attempt_watchdog.py poll", "--finished", "attempt_watchdog.py orphans",
                   "orphan-mark", "attempt_watchdog.py arm", "TaskStop",
                   "background-spawn-failed", "orphan-holds-gpu", "timeout 300000"):
        assert needle in proto, needle


def test_done_branch_releases_the_lease():
    proto = _local_protocol()
    done = proto[proto.index("On `done`"):]
    assert "local_lease.py release" in done[:600]


def test_poll_output_goes_to_p_not_w():
    proto = _local_protocol()
    assert ".poll.json" in proto and ".watch.json" in proto
    assert "| tee <P>" in proto
    assert "--watch-json" not in proto or "never `W`" in proto


def test_runaway_branch_stops_discards_and_escalates():
    proto = _local_protocol()
    run = proto[proto.index("On `runaway`"):]
    for needle in ("TaskStop", "local_lease.py release", "task_verify.py discard",
                   "--outcome FAIL", "runaway-orphan"):
        assert needle in run, needle


def test_section2_local_bullet_points_at_the_ceiling():
    bullet = SEC2[SEC2.index("- `local`:"):SEC2.index("- `sonnet` / `opus`:")]
    assert "background" in bullet and "local_lease.py acquire" in bullet
    assert "never spawned in the foreground" in bullet


def test_hybrid_text_survives():
    for needle in ("CONTRACT FIRST", "attempt_start_check.py", "ROUTE:", "--route '<ROUTE json>'",
                   "--route-from <d>/decisions.md"):
        assert needle in DISPATCH, needle
    # Q4 (operator ruling): the opus rungs spawn their own variants; nothing runs inline.
    opus = SEC2[SEC2.index("- `sonnet` / `opus`:"):]
    assert "never does a task itself" in " ".join(opus[:400].split())


def test_tp_worker_tools_include_taskstop():
    if not TP_WORKER_MD.is_file():
        pytest.skip("agents/tp-worker.md not in this install")
    text = TP_WORKER_MD.read_text(encoding="utf-8")
    front = text.split("\n---", 1)[0]
    tools = json.loads(re.search(r"^tools:\s*(\[.*\])\s*$", front, re.M).group(1))
    assert "TaskStop" in tools and "Agent" in tools


def test_dispatch_doc_stays_under_cap():
    # strata-session-isolation 5.2: re-pinned 260 → 275 (child-spawn wiring)
    assert len(DISPATCH.splitlines()) <= 275
