"""Tests for model_policy.RUNG_EFFORTS and rung_model — the one rung→model map.

design: run-throughput (Task 2.1, Phase 1b). `RUNG_EFFORTS` is the two-level
effort vocabulary per model (few variants by design); `rung_model(rung,
local_cfg)` maps `local` rungs to `local_cfg["model"]`, `sonnet` rungs to
`local_cfg["fallback_model"]`, and `opus` rungs to None (the dispatcher's
inline Opus rung — hybrid's contract, unchanged). A bare family name is a
valid rung; an unknown family, an effort outside `RUNG_EFFORTS`, or a missing
`local_cfg` for a spawned family (Part A: `rung:<r>` with a missing
`local_cfg` is a `ValueError`) is a `ValueError`. No project import: the
`local_implement` block is passed in.
Run with: python3 -m pytest skills/_shared/test_model_policy_effort.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_policy as mp  # noqa: E402


CFG = {"model": "qwen3-coder", "fallback_model": "sonnet"}


# --- RUNG_EFFORTS -------------------------------------------------------------

def test_rung_efforts_are_two_levels_per_model():
    # design: few variants — two efforts per model, that is the whole ladder.
    assert mp.RUNG_EFFORTS == ("medium", "xhigh")


# --- rung_model: the one rung→model map ---------------------------------------

def test_rung_model_local_rungs_take_model():
    assert mp.rung_model("local", CFG) == "qwen3-coder"
    assert mp.rung_model("local-medium", CFG) == "qwen3-coder"
    assert mp.rung_model("local-xhigh", CFG) == "qwen3-coder"


def test_rung_model_sonnet_rungs_take_fallback_model():
    assert mp.rung_model("sonnet", CFG) == "sonnet"
    assert mp.rung_model("sonnet-medium", CFG) == "sonnet"
    assert mp.rung_model("sonnet-xhigh", CFG) == "sonnet"


def test_rung_model_opus_rungs_spawn_on_opus():
    # Q4 (operator ruling): the opus rungs spawn their own variants on opus, whatever
    # the local config, and need no local config at all.
    assert mp.rung_model("opus", CFG) == "opus"
    assert mp.rung_model("opus-medium", CFG) == "opus"
    assert mp.rung_model("opus-xhigh", CFG) == "opus"
    assert mp.rung_model("opus", None) == "opus"
    for eff in mp.RUNG_EFFORTS:
        assert mp.agent_spec(f"tp-task-worker-opus-{eff}", None, CFG) == {
            "role": "task", "model": "opus", "effort": eff}


@pytest.mark.parametrize(
    "rung",
    ["bogus", "bogus-medium", "local-max", "sonnet-max", "opus-max"],
)
def test_rung_model_rejects_unknown_families_and_efforts(rung):
    # `local-max`: an effort outside the two-level vocabulary is a rung that
    # does not exist, even though its family does.
    with pytest.raises(ValueError):
        mp.rung_model(rung, CFG)


@pytest.mark.parametrize("rung", ["local", "local-medium", "sonnet", "sonnet-xhigh"])
def test_rung_model_requires_local_cfg_for_spawned_families(rung):
    with pytest.raises(ValueError):
        mp.rung_model(rung, None)


# --- Task 3.1: effort vocabulary, the one agent table, gate floors -----------

import ast  # noqa: E402

import ladder_rungs  # noqa: E402

MP_FILE = Path(__file__).resolve().parent / "model_policy.py"


def test_efforts_vocabulary_holds_rung_efforts():
    assert mp.EFFORTS == ("low", "medium", "high", "xhigh", "max")
    assert set(mp.RUNG_EFFORTS) <= set(mp.EFFORTS)
    assert set(mp.ROLE_EFFORT.values()) <= set(mp.EFFORTS)


def test_effort_for_roles():
    assert mp.effort_for("design_run") == "high"
    assert mp.effort_for("review") == "high"  # Q2: the floor; round 1 is -deep/xhigh


@pytest.mark.parametrize("role", ["fix", "classifier", "audit", "bogus"])
def test_effort_for_rejects_roles_outside_role_effort(role):
    with pytest.raises(ValueError):
        mp.effort_for(role)


AGENT_ROWS = [
    ("tp-generator", "generator", "opus", "high"),
    ("tp-worker", "phase-worker", "sonnet", "high"),
    ("tp-readonly-auditor", "reader", "opus", "high"),
    ("tp-impl-auditor", "impl-audit", "opus", "xhigh"),
    ("tp-certifier", "certify", "opus", "xhigh"),
    ("tp-phase-checker", "phase-check", "opus", "medium"),
    ("tp-review-confirmer", "review", "opus", "high"),
    ("tp-review-confirmer-deep", "review", "opus", "xhigh"),
    ("tp-runbook", "runbook", "qwen3-coder", "medium"),
    ("tp-task-worker", "task", "opus", "xhigh"),
]


@pytest.mark.parametrize("name,role,model,effort", AGENT_ROWS)
def test_agent_spec_per_agents_row(name, role, model, effort):
    spec = mp.agent_spec(name, None, CFG)
    assert spec == {"role": role, "model": model, "effort": effort}
    assert name in mp.AGENTS
    assert spec["effort"] in mp.EFFORTS


def test_agent_spec_council_glob():
    assert mp.agent_spec("council-feynman") == {
        "role": "audit-member", "model": "sonnet", "effort": "high",
    }


@pytest.mark.parametrize(
    "name,model,effort",
    [
        ("tp-task-worker-local-medium", "qwen3-coder", "medium"),
        ("tp-task-worker-local-xhigh", "qwen3-coder", "xhigh"),
        ("tp-task-worker-sonnet-medium", "sonnet", "medium"),
        ("tp-task-worker-sonnet-xhigh", "sonnet", "xhigh"),
    ],
)
def test_agent_spec_four_variants_by_rule(name, model, effort):
    assert mp.agent_spec(name, None, CFG) == {
        "role": "task", "model": model, "effort": effort,
    }


@pytest.mark.parametrize(
    "name",
    ["tp-task-worker-opus-max",
     "tp-task-worker-local-max", "tp-task-worker-local", "general-purpose", "nope"],
)
def test_agent_spec_unknown_is_keyerror(name):
    with pytest.raises(KeyError):
        mp.agent_spec(name, None, CFG)


def test_agent_spec_rung_source_needs_local_cfg():
    with pytest.raises(ValueError):
        mp.agent_spec("tp-runbook")
    with pytest.raises(ValueError):
        mp.agent_spec("tp-task-worker-local-medium")


def test_review_agent_follows_models_review():
    cfg = {"models": {"review": "sonnet"}}
    assert mp.agent_spec("tp-review-confirmer", cfg)["model"] == "sonnet"
    # the gate pins never follow a config value
    assert mp.agent_spec("tp-impl-auditor", cfg)["model"] == mp.PINNED


def test_role_agent_is_the_non_glob_entry():
    assert mp.role_agent("impl-audit") == "tp-impl-auditor"
    assert mp.role_agent("certify") == "tp-certifier"
    assert mp.role_agent("review") == "tp-review-confirmer"
    assert mp.role_agent("task") == "tp-task-worker"
    assert mp.role_agent("audit-member") is None  # glob-only
    assert mp.role_agent("bogus") is None


def test_gate_roles():
    assert mp.GATE_ROLES == ("impl-audit", "certify", "review", "phase-check")


def test_floor_per_gate_role():
    pinned = {"model": "opus", "effort": "xhigh", "configurable": False}
    assert mp.floor("impl-audit") == pinned
    assert mp.floor("certify") == pinned
    # review-convergence 8.2: the phase-check gate is pinned opus, effort medium.
    assert mp.floor("phase-check") == {
        "model": "opus", "effort": "medium", "configurable": False,
    }
    assert mp.floor("review") == {"model": "opus", "effort": "high", "configurable": True}
    cfg = {"models": {"review": "sonnet"}}
    assert mp.floor("review", cfg) == {
        "model": "sonnet", "effort": "high", "configurable": True,
    }


@pytest.mark.parametrize("role", ["task", "reader", "runbook", "bogus"])
def test_floor_none_outside_gate_roles(role):
    assert mp.floor(role) is None


@pytest.mark.parametrize("rung", ladder_rungs.SPAWN_RUNGS)
def test_spawn_rung_agent_effort_matches_rung(rung):
    # 2.7's source: a rung's worker agent carries the rung's effort.
    spec = mp.agent_spec(ladder_rungs.agent(rung), None, CFG)
    assert spec["effort"] == ladder_rungs.effort(rung)
    assert spec["model"] == mp.rung_model(rung, CFG)


def test_model_policy_imports_no_project_module_and_stays_small():
    source = MP_FILE.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 301
    mods = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert mods <= set(sys.stdlib_module_names), mods
