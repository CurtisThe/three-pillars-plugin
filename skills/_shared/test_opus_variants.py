"""test_opus_variants.py — the opus rungs are real, generated worker variants (Q4).

design: run-throughput (operator ruling Q4, PR #178 fix pass)

`tp-task-worker-opus-medium` / `-opus-xhigh` are produced by `agent_variants.py` from the
`tp-task-worker.md` base like the other four (no hand-copied drift), carry `model: opus`
and their rung's effort, pass the dispatch floor for their role, and the ladder spawns
them by a resolved reference instead of running the rung inline.
"""
from __future__ import annotations

from pathlib import Path

import agent_variants
import dispatch_select
import ladder_rungs
import model_policy
import weight_class

ROOT = Path(__file__).resolve().parents[2]
OPUS = ("tp-task-worker-opus-medium", "tp-task-worker-opus-xhigh")


def test_generator_owns_both_opus_variants():
    assert set(OPUS) <= set(agent_variants.variants())
    assert agent_variants.check(ROOT) == []
    base = (ROOT / "agents" / "tp-task-worker.md").read_text(encoding="utf-8")
    for name in OPUS:
        rung = name.removeprefix("tp-task-worker-")
        assert (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8") == \
            agent_variants.render(base, rung)


def test_opus_variants_frontmatter_is_opus_at_the_rung_effort():
    for name in OPUS:
        fm = weight_class.parse_frontmatter((ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8"))
        assert (fm["model"], fm["effort"]) == ("opus", name.rsplit("-", 1)[1])


def test_opus_variants_pass_their_floor():
    for name in OPUS:
        spec = model_policy.agent_spec(name)
        assert dispatch_select.enforce_floor(spec["role"], name) == (name, None)


def test_every_rung_has_a_distinct_spawned_agent():
    agents = [ladder_rungs.agent(r) for r in ladder_rungs.RUNGS]
    assert None not in agents and len(set(agents)) == len(ladder_rungs.RUNGS)
    assert ladder_rungs.agent("opus-medium") != ladder_rungs.agent(ladder_rungs.quality_next("opus-medium"))
