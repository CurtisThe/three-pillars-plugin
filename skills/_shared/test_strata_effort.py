"""test_strata_effort.py — the Strata effort inventory, agent mapping and spawn.

design: strata-effort-every-call (Task 1.1). The examples come from design §Entities.
Behavior only: which agent a Strata dispatch spawns, the effort it states, and that
a request at a bare `high` is refused. The Opus/Sonnet efforts of the base agents are
pinned unchanged (Behavior 1, Opus side).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import cheap_classes
import model_policy
import strata_effort

SHARED = Path(__file__).resolve().parent
VARIANT = "council-ada-medium"
WANT = {"agent": VARIANT, "agent_ref": f"three-pillars:{VARIANT}",
        "effort": "medium", "rung": "local-medium"}


def fw_root(tmp_path: Path) -> Path:
    root = tmp_path / "fw"
    (root / "agents").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    (root / "agents" / f"{VARIANT}.md").write_text(f"---\nname: {VARIANT}\n---\n", encoding="utf-8")
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "three-pillars", "agents": [f"./agents/{VARIANT}.md"]}), encoding="utf-8")
    return root


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SHARED / "strata_effort.py"), *args],
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("base, want", [
    ("council-ada", "council-ada-medium"),
    ("tp-review-confirmer", "tp-review-confirmer-medium"),
])
def test_variant_bases_map_to_their_medium_variant(base, want):
    assert strata_effort.strata_agent(base) == want


@pytest.mark.parametrize("name", [
    "tp-review-confirmer-deep", "tp-task-worker-local-xhigh", "tp-drafter-xhigh", "council-ada-medium",
])
def test_deep_rung_drafter_and_variant_names_map_to_themselves(name):
    assert strata_effort.strata_agent(name) == name


def test_variant_bases_lists_only_unsuffixed_bases():
    names = ["council-ada", "council-ada-medium", "tp-review-confirmer", "tp-review-confirmer-deep",
             "tp-drafter", "tp-task-worker-local-medium"]
    assert sorted(strata_effort.variant_bases(names)) == ["council-ada", "tp-review-confirmer"]


@pytest.mark.parametrize("agent, want", [
    ("council-ada-medium", "medium"),
    ("tp-review-confirmer-medium", "medium"),
    ("council-ada", "high"),  # the Opus side keeps its effort
    ("tp-review-confirmer", "high"),  # literal: catches a lowered base effort
    ("tp-review-confirmer-deep", "xhigh"),
    ("tp-task-worker-local-xhigh", "xhigh"),
])
def test_effort_of_a_strata_variant_and_its_unchanged_base(agent, want):
    assert strata_effort.effort(agent) == want


def test_engine_role_effort_covers_every_engine_role_at_a_strata_effort():
    assert set(strata_effort.ENGINE_ROLE_EFFORT) == set(model_policy.ENGINE_ROLES)
    assert all(v in strata_effort.STRATA_EFFORTS for v in strata_effort.ENGINE_ROLE_EFFORT.values())
    assert strata_effort.role_effort("council_member") == "medium"


def test_spawn_refuses_an_agent_at_high():
    with pytest.raises(strata_effort.StrataEffortError):
        strata_effort.spawn("tp-generator")


def test_spawn_returns_the_variant_reference_and_effort(tmp_path):
    assert strata_effort.spawn("council-ada", root=fw_root(tmp_path)) == WANT


def test_cli_spawn_prints_the_json(tmp_path):
    res = cli("spawn", "council-ada", "--root", str(fw_root(tmp_path)))
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == WANT


def test_cli_refused_spawn_exits_1_with_one_stderr_line():
    res = cli("spawn", "tp-generator")
    assert res.returncode == 1
    assert res.stdout == ""
    assert len(res.stderr.strip().splitlines()) == 1


def test_confirmer_medium_is_a_cheap_class():
    assert cheap_classes.klass("tp-review-confirmer-medium") == "cheap"
