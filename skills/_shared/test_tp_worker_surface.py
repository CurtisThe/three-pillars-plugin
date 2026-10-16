"""tp-worker's declared surface: it runs on Sonnet and can spawn `tp-task-worker`.

design: local-implement-and-review (operator ruling on the final #165 review, (D)),
superseded in part by strata-spend-leaks Task 2.1.

Under `/tp-run-full-design --local`, Slot 7's `tp-worker` spawns `tp-task-worker` at
depth 2, so its frontmatter must keep the `Agent` tool. The #165 ruling (D) pinned its
model to Opus; the strata-spend-leaks operator ruling supersedes that pin: the phase
dispatcher is orchestration and runs on `sonnet` (Opus only on a retry, per
`tp-run-full-design/run-safety.md` ## Retry & max-attempts). Both are read as data: the
frontmatter through `weight_class.parse_frontmatter`, and the `tools` value as the JSON
list it is.
"""
from __future__ import annotations

import json
from pathlib import Path

from weight_class import parse_frontmatter

WORKER = Path(__file__).resolve().parents[2] / "agents" / "tp-worker.md"


def test_tp_worker_is_sonnet_and_can_spawn_agents():
    fm = parse_frontmatter(WORKER.read_text(encoding="utf-8"))
    assert fm.get("model") == "sonnet"
    tools = json.loads(fm["tools"])
    assert isinstance(tools, list) and "Agent" in tools
