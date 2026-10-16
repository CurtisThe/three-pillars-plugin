"""test_strata_effort_guard.py — the Strata effort guard.

design: strata-effort-every-call (Task 3.3). Behaviors 3, 5 and 6: every
Strata-routable agent and engine role sits in the `strata_effort` inventory at a
`medium`/`xhigh` effort, a Strata site with no inventory entry fails the guard,
and every medium->xhigh escalation path is still present.

The negative cases build a minimal framework root (only the agents the inventory
names, so a tmp root lacks nothing except the thing under test) and inject the
break through `check`'s parameters, a tmp doc copy, or `model_policy.AGENTS`.
Each asserts exactly one problem line — the guard is one line per break.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import angles  # noqa: E402
import cheap_tier  # noqa: E402
import cheap_tier_cli  # noqa: E402
import ladder_rungs  # noqa: E402
import model_policy  # noqa: E402
import role_engine  # noqa: E402
import strata_effort  # noqa: E402
import strata_effort_check  # noqa: E402

REPO = HERE.parents[1]
SITES = strata_effort.SITES
# Every agent the inventory names (S3's glob is satisfied by the council pair), so
# a tmp root reports nothing except the break under test.
SITE_AGENTS = ("council-ada", "council-ada-medium", "tp-drafter", "tp-drafter-xhigh",
               "tp-explainer", "tp-review-confirmer-deep", "tp-review-confirmer-medium",
               "tp-runbook", "tp-task-worker-local-medium", "tp-task-worker-local-xhigh")


def fw_root(tmp_path: Path, agents=SITE_AGENTS) -> Path:
    """A framework root holding `agents` as `agents/<name>.md`."""
    root = tmp_path / "fw"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    for name in agents:
        (root / "agents" / f"{name}.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    return root


def test_check_is_clean_on_the_repo():
    assert strata_effort_check.check(REPO) == []


def test_a_council_site_missing_from_the_inventory_fails(tmp_path):
    sites = tuple(s for s in SITES if s.id != "S3")
    assert strata_effort_check.check(fw_root(tmp_path), sites=sites) == [
        "council-ada-medium: no inventory site"]


def test_an_engine_role_with_no_effort_and_no_site_fails(tmp_path):
    roles = tuple(model_policy.ENGINE_ROLES) + ("mystery_role",)
    lines = strata_effort_check.check(fw_root(tmp_path), roles=roles)
    assert len(lines) == 1
    assert "mystery_role" in lines[0]


def test_a_strata_agent_at_a_bare_high_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(model_policy, "AGENTS",
                        {**model_policy.AGENTS, "tp-new-local": ("drafter", "rung:local", "high")})
    lines = strata_effort_check.check(fw_root(tmp_path, SITE_AGENTS + ("tp-new-local",)))
    assert len(lines) == 1
    assert "tp-new-local" in lines[0] and "high" in lines[0]


def test_a_site_id_in_a_doc_with_no_inventory_entry_fails(tmp_path):
    root = fw_root(tmp_path)
    doc = root / "skills" / "council" / "strata-members.md"
    doc.parent.mkdir(parents=True)
    text = (REPO / "skills" / "council" / "strata-members.md").read_text(encoding="utf-8")
    doc.write_text(text + "\n\n`child_spawn.py start --site S9` runs the new site.\n",
                   encoding="utf-8")
    lines = strata_effort_check.check(root)
    assert len(lines) == 1
    assert "S9" in lines[0]


def test_cli_exits_0_on_the_repo_and_1_with_the_lines(tmp_path):
    ok = subprocess.run([sys.executable, str(HERE / "strata_effort_check.py")],
                        capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = subprocess.run([sys.executable, str(HERE / "strata_effort_check.py"),
                          "--root", str(fw_root(tmp_path, ("council-ada",)))],
                         capture_output=True, text=True, timeout=60)
    assert bad.returncode == 1
    assert "council-ada-medium" in bad.stdout


# --- Behavior 6: every medium -> xhigh escalation path is still there --------

def test_the_task_worker_ladder_steps_medium_up_to_xhigh():
    assert ladder_rungs.quality_next("local-medium") == "local-xhigh"
    assert strata_effort.effort(ladder_rungs.agent("local-medium")) == "medium"
    assert strata_effort.effort(ladder_rungs.agent("local-xhigh")) == "xhigh"


def test_the_drafter_escalation_pair_is_intact():
    assert cheap_tier_cli.DRAFTERS == {"medium": "tp-drafter", "xhigh": "tp-drafter-xhigh"}
    assert strata_effort.effort(cheap_tier_cli.DRAFTERS["medium"]) == "medium"
    assert strata_effort.effort(cheap_tier_cli.DRAFTERS["xhigh"]) == "xhigh"


def test_the_deep_finder_stays_round_one_at_xhigh():
    assert angles.review_agent(1) == "tp-review-confirmer-deep"
    assert strata_effort.effort("tp-review-confirmer-deep") == "xhigh"
    assert strata_effort.strata_agent("tp-review-confirmer-deep") == "tp-review-confirmer-deep"


def test_every_slot_local_rung_states_a_strata_effort():
    rungs = [rung for slot in cheap_tier.SLOTS.values() if slot.kind == "model"
             for rung in slot.rungs if rung.startswith("local-")]
    assert rungs
    assert all(ladder_rungs.effort(r) in strata_effort.STRATA_EFFORTS for r in rungs)


# --- Behaviors 1-3: the efforts the inventory states -------------------------

def test_every_engine_role_resolves_at_a_strata_effort(tmp_path):
    for role in model_policy.ENGINE_ROLES:
        row = role_engine.resolve(role, {}, root=tmp_path, available=lambda: True, local=True)
        assert row["effort"] in strata_effort.STRATA_EFFORTS, role


@pytest.mark.parametrize("agent, want", [
    ("council-ada", "high"),                      # the Opus/Sonnet side is unmoved
    ("tp-review-confirmer", "high"),
    ("tp-review-confirmer-deep", "xhigh"),
    ("tp-task-worker-local-xhigh", "xhigh"),
    ("tp-drafter-xhigh", "xhigh"),
    ("council-ada-medium", "medium"),
    ("tp-review-confirmer-medium", "medium"),
    ("tp-task-worker-local-medium", "medium"),
    ("tp-drafter", "medium"),
])
def test_each_pinned_agent_keeps_its_stated_effort(agent, want):
    assert strata_effort.effort(agent) == want
