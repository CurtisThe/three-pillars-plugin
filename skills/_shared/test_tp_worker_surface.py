"""tp-worker's declared surface: it runs on Opus and can spawn `tp-task-worker`.

design: local-implement-and-review (operator ruling on the final #165 review, (D)).

Under `/tp-run-full-design --local`, Slot 7's Opus `tp-worker` spawns `tp-task-worker`
at depth 2, so its frontmatter must keep `model: opus` and the `Agent` tool. Both are
read as data: the frontmatter through `weight_class.parse_frontmatter`, and the
`tools` value as the JSON list it is.
"""
from __future__ import annotations

import json
from pathlib import Path

from weight_class import parse_frontmatter

WORKER = Path(__file__).resolve().parents[2] / "agents" / "tp-worker.md"


def test_tp_worker_is_opus_and_can_spawn_agents():
    fm = parse_frontmatter(WORKER.read_text(encoding="utf-8"))
    assert fm.get("model") == "opus"
    tools = json.loads(fm["tools"])
    assert isinstance(tools, list) and "Agent" in tools
