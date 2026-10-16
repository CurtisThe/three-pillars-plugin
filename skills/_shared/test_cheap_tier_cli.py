"""Tests for cheap_tier_cli.py — the `spec` and `task-table` subcommands.

design: cheap-tier-offload (Tasks 3.2, 3.3, 6.6).

Every case uses a tmp repo root that holds only `.three-pillars/config.json` (no
`.claude-plugin/plugin.json`), with `local_lease.acquire` monkeypatched, so no test
reaches a router, a lease or a model.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_ref  # noqa: E402
import cheap_tier_cli as cli  # noqa: E402

ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-30T00:00:00Z"}
LOCAL = {"enabled": True, "model": "qwen3-coder", "fallback_model": "sonnet"}


@pytest.fixture
def lease(monkeypatch):
    """Record every lease probe; the probe answers `free` unless a test sets it."""
    calls = []
    state = {"value": ("free", "unowned")}

    def fake_acquire(*args, **kwargs):
        calls.append((args, kwargs))
        return state["value"]

    monkeypatch.setattr(cli.local_lease, "acquire", fake_acquire)
    return calls, state


def _root(tmp_path: Path, config) -> Path:
    cfg = tmp_path / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(config if isinstance(config, str) else json.dumps(config), encoding="utf-8")
    return tmp_path


def _spec(capsys, root: Path, slot: str, *extra: str) -> tuple[int, dict | None, str]:
    code = cli.main(["spec", "--slot", slot, "--root", str(root), *extra])
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


# --- Task 3.2: spec -------------------------------------------------------------------


def test_spec_null_when_the_slot_is_off_or_unset(tmp_path, capsys, lease):
    """Always on (2.4): null needs `models.<slot>: "off"` or a slot with no shipped default."""
    off = _root(tmp_path, {"models": {"handoff": "off", "docs_draft": "off"}})
    for slot in ("handoff", "docs_draft"):
        assert _spec(capsys, off, slot) == (0, {"slot": slot, "rung": None}, "")
    bare = _root(tmp_path / "bare", {})
    for extra in ((), ("--cheap-tier", "on")):
        assert _spec(capsys, bare, "handoff", *extra)[:2] == (
            0, {"slot": "handoff", "rung": None})
    assert lease[0] == []


def test_spec_absent_flag_reads_the_config(tmp_path, capsys, lease):
    """An absent flag is `on`, so a bad config is refused (it was never read when off)."""
    root = _root(tmp_path, "{not json")
    code, spec, err = _spec(capsys, root, "handoff")
    assert (code, spec) == (2, None) and len(err.strip().splitlines()) == 1


def test_spec_code_slot_has_no_agent_and_no_probe(tmp_path, capsys, lease):
    root = _root(tmp_path, {"models": {"runbook": "code"}})
    code, spec, _err = _spec(capsys, root, "runbook", "--cheap-tier", "ab",
                             "--route", json.dumps(ROUTED))
    assert code == 0
    assert spec == {"slot": "runbook", "rung": "code", "oracle": "exit_code",
                    "on_fail": "escalate", "mode": "on"}  # `ab` runs as `on` (2.4)
    assert lease[0] == []


def test_spec_unrouted_floors_to_the_sonnet_mirror_without_probing(tmp_path, capsys, lease):
    root = _root(tmp_path, {"models": {"handoff": "local-medium"}, "local_implement": LOCAL})
    code, spec, _err = _spec(capsys, root, "handoff", "--cheap-tier", "on")
    assert code == 0
    assert spec["rung"] == "sonnet-medium" and "missing-route" in spec["why"]
    assert spec["model"] == "sonnet" and spec["agent"] == "tp-drafter"
    assert lease[0] == []  # an unrouted site never takes the machine-wide lease


def test_spec_routed_and_free_keeps_the_local_rung(tmp_path, capsys, lease):
    root = _root(tmp_path, {"models": {"base_sync_splice": "local-xhigh"},
                            "local_implement": LOCAL})
    code, spec, _err = _spec(capsys, root, "base_sync_splice", "--cheap-tier", "on",
                             "--route", json.dumps(ROUTED))
    assert code == 0 and len(lease[0]) == 1
    assert spec == {
        "slot": "base_sync_splice", "rung": "local-xhigh",
        "why": "local-xhigh: routed/ok, lease free", "agent": "tp-drafter-xhigh",
        "agent_ref": agent_ref.resolve("tp-drafter-xhigh"), "model": "qwen3-coder",
        "oracle": "zero_drop", "on_fail": "drop", "mode": "on"}


def test_spec_routed_but_busy_floors(tmp_path, capsys, lease):
    lease[1]["value"] = ("busy", "slot held by abcd1234")
    root = _root(tmp_path, {"models": {"handoff": "local-medium"}, "local_implement": LOCAL})
    _code, spec, _err = _spec(capsys, root, "handoff", "--cheap-tier", "on",
                              "--route", json.dumps(ROUTED))
    assert spec["rung"] == "sonnet-medium" and spec["why"].endswith("lease busy")


def test_spec_agent_ref_uses_the_framework_root(tmp_path, capsys, lease):
    """The tmp repo root has no plugin.json, yet both drafter refs resolve."""
    assert not (tmp_path / ".claude-plugin").exists()
    root = _root(tmp_path, {"models": {"handoff": "sonnet-medium",
                                       "pr_fix_reproducer": "sonnet-xhigh"}})
    for slot, agent in (("handoff", "tp-drafter"), ("pr_fix_reproducer", "tp-drafter-xhigh")):
        code, spec, _err = _spec(capsys, root, slot, "--cheap-tier", "on")
        assert code == 0 and spec["agent"] == agent
        assert spec["agent_ref"] == agent_ref.resolve(agent)


def test_spec_without_local_implement_block_gives_sonnet(tmp_path, capsys, lease):
    root = _root(tmp_path, {"models": {"handoff": "local-medium",
                                       "history_line": "sonnet-medium"}})
    for slot in ("handoff", "history_line"):  # classifier_judge is 6.6-gated (no route)
        code, spec, _err = _spec(capsys, root, slot, "--cheap-tier", "on")
        assert code == 0 and spec["model"] == "sonnet"


def test_spec_never_returns_haiku_unrouted(tmp_path, capsys, lease):
    root = _root(tmp_path, {"models": {"handoff": "local-medium"},
                            "local_implement": dict(LOCAL, model="haiku")})
    _code, spec, _err = _spec(capsys, root, "handoff", "--cheap-tier", "on")
    assert "haiku" not in spec["model"]


@pytest.mark.parametrize("models", [{"council": "sonnet-medium"}, {"flake_triage": "code"}])
def test_spec_reads_the_raw_config(tmp_path, capsys, lease, models):
    """load_repo_config would prune these keys; spec refuses them instead."""
    root = _root(tmp_path, {"models": models})
    code, spec, err = _spec(capsys, root, "handoff", "--cheap-tier", "on")
    assert (code, spec) == (2, None)
    assert len(err.strip().splitlines()) == 1 and next(iter(models)) in err


@pytest.mark.parametrize("config", ["{not json", "[1, 2]"])
def test_spec_bad_config_exits_2(tmp_path, capsys, lease, config):
    code, spec, err = _spec(capsys, _root(tmp_path, config), "handoff", "--cheap-tier", "on")
    assert (code, spec) == (2, None) and len(err.strip().splitlines()) == 1


@pytest.mark.parametrize("slot", ["task", "no_such_slot"])
def test_spec_task_or_unknown_slot_exits_2(tmp_path, capsys, lease, slot):
    code, spec, err = _spec(capsys, _root(tmp_path, {}), slot, "--cheap-tier", "on")
    assert (code, spec) == (2, None) and len(err.strip().splitlines()) == 1


def test_spec_unresolved_agent_exits_3(tmp_path, capsys, lease, monkeypatch):
    def broken(agent, root=None):
        raise agent_ref.AgentRefError(agent, "no plugin.json")

    monkeypatch.setattr(cli.agent_ref, "resolve", broken)
    root = _root(tmp_path, {"models": {"handoff": "sonnet-medium"}})
    code, spec, err = _spec(capsys, root, "handoff", "--cheap-tier", "on")
    assert (code, spec) == (3, None)
    assert err.startswith("agent-unresolved: tp-drafter")


# --- Task 3.3: task-table -------------------------------------------------------------


def _task(tid: str, files: str, targets: str, *extra: str) -> str:
    return "\n".join([f"### Task {tid}: t{tid}", f"**File**: {files}",
                      f"**Targets**: {targets}", "**Red**: r", "**Green**: g", *extra]) + "\n"


PLAN = "# P\n\n## Phase 1: Things\n\n" + "\n".join([
    _task("1.1", "`pkg/a.py`", "`pkg/test_a.py::test_x`"),
    _task("1.2", "`pkg/b.py`", "`pkg/test_a.py::test_y`", "**Kind**: clerical"),
    _task("1.3", "`pkg/z.py`", "`gone/test_z.py::test_z`"),
])


def _plan_root(tmp_path: Path, config) -> tuple[Path, Path]:
    root = _root(tmp_path, config)
    for rel in ("pkg/a.py", "pkg/b.py", "pkg/test_a.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    plan = root / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    return root, plan


def _table(capsys, root: Path, plan: Path, *extra: str) -> tuple[int, list | None]:
    code = cli.main(["task-table", "--plan", str(plan), "--phase", "1", "--root", str(root),
                     *extra])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else None)


@pytest.mark.parametrize("mode", ["on", "ab"])
def test_task_table_on(tmp_path, capsys, mode):
    import cheap_tier
    import task_eligibility as te
    root, plan = _plan_root(tmp_path, {"models": {"task": "sonnet-xhigh"}})  # no local block
    code, rows = _table(capsys, root, plan, "--cheap-tier", mode)
    assert code == 0
    want = cheap_tier.task_table(te.phase_rows(PLAN, 1, root))
    assert rows == json.loads(json.dumps(want))
    by = {r["task_id"]: r for r in rows}
    assert (by["1.1"]["tier"], by["1.1"]["start_rung"]) == ("sonnet", "sonnet-xhigh")
    assert (by["1.2"]["tier"], by["1.2"]["start_rung"]) == ("sonnet", "sonnet-medium")
    assert by["1.3"]["tier"] == "sonnet"  # target-missing stays local, then floored to sonnet
    assert by["1.3"]["floored_from"] == "local" and "target-missing" in by["1.3"]["reasons"]


@pytest.mark.parametrize("extra", [(), ("--cheap-tier", "on")])
def test_task_table_off(tmp_path, capsys, extra):
    """`models.task: "off"` is the lever's one opt-out; the run flag no longer matters."""
    root, plan = _plan_root(tmp_path, {"models": {"task": "off"}})
    assert _table(capsys, root, plan, *extra) == (1, [])


def test_task_table_bad_config_exits_2(tmp_path, capsys):
    root, plan = _plan_root(tmp_path, {"models": {"council": "sonnet-medium"}})
    assert _table(capsys, root, plan, "--cheap-tier", "on") == (2, None)


def test_task_table_imports_the_derivation():
    """No resolve_runner / configured_max_files call of its own (plan.md Deviations 6)."""
    import ast
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    called = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
              for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not called & {"resolve_runner", "configured_max_files"}
    assert "phase_rows" in called


# --- Task 4.3: slots, the Tier 1 preflight ---------------------------------------------


def test_slots_prints_the_map(tmp_path, capsys):
    import cheap_tier
    root = _root(tmp_path, {"models": {"task": "sonnet-xhigh", "review": "opus"}})
    assert cli.main(["slots", "--root", str(root)]) == 0
    shipped = {s: r.default for s, r in cheap_tier.SLOTS.items() if r.default}  # every slot but handoff
    assert json.loads(capsys.readouterr().out) == {**shipped, "task": "sonnet-xhigh"}  # ROLES skipped
    bare = _root(tmp_path / "bare", {"schema_version": 1})
    assert cli.main(["slots", "--root", str(bare)]) == 0
    assert json.loads(capsys.readouterr().out) == shipped


@pytest.mark.parametrize("config", [
    {"models": {"council": "sonnet-medium"}},   # excluded
    {"models": {"flake_triage": "code"}},       # unknown (removed, plan.md Deviations 2)
    {"models": {"runbook": "sonnet-medium"}},   # a rung outside the slot's rungs
    "{not json",
])
def test_slots_refuses_on_the_raw_config(tmp_path, capsys, config):
    """Read raw, so an excluded or unknown key is refused, never pruned (Deviations 7)."""
    root = _root(tmp_path, config)
    assert cli.main(["slots", "--root", str(root)]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("cheap-tier: ") and len(err.splitlines()) == 1


# --- Task 6.6: the classifier gate (reads the verdict file only) ----------------------


def test_classifier_gate(tmp_path, capsys, lease, monkeypatch):
    assert cli.CLASSIFIER_VERDICT.parts[-3:] == ("tp-pr-iterate", "eval", "classifier-rung.json")
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))  # eval/ is dev-only
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                and "run_eval" in ast.dump(n)]
    path = tmp_path / "classifier-rung.json"
    monkeypatch.setattr(cli, "CLASSIFIER_VERDICT", path)
    root = _root(tmp_path / "repo", {"models": {"classifier_judge": "local-medium"},
                                     "local_implement": LOCAL})
    routed = ("--route", json.dumps(ROUTED))

    def rung(*extra):
        return _spec(capsys, root, "classifier_judge", "--cheap-tier", "on", *extra)[1]["rung"]

    assert rung(*routed) is None  # no verdict file: today's path
    good = {"rung": "local-medium", "thresholds_met": True, "local_model": LOCAL["model"],
            "route": ROUTED["base_url"], "at": "2026-09-30T00:00:00+00:00"}
    for bad in ({"thresholds_met": False}, {"thresholds_met": "yes"},
                {"local_model": "other-model"}, {"route": "http://127.0.0.1:9"}):
        path.write_text(json.dumps({**good, **bad}), encoding="utf-8")
        assert rung(*routed) is None, bad
    path.write_text(json.dumps(good), encoding="utf-8")
    assert rung() is None  # no route passed (MISSING): every site today
    path.write_text(json.dumps({**good, "route": None}), encoding="utf-8")
    assert rung() is None, "a null-route verdict matched a missing route"
    assert rung(*routed) is None, "a null-route verdict matched a real route"
    path.write_text(json.dumps({**good, "local_model": None}), encoding="utf-8")
    assert rung(*routed) is None, "a null-local_model verdict matched the configured model"
    for key in ("route", "local_model"):
        path.write_text(json.dumps({k: v for k, v in good.items() if k != key}), encoding="utf-8")
        assert rung(*routed) is None, f"a verdict missing {key} matched anyway"
    path.write_text(json.dumps(good), encoding="utf-8")
    assert rung(*routed) == "local-medium"
    path.write_text("{not json", encoding="utf-8")
    assert rung(*routed) is None
    path.unlink()
    assert _spec(capsys, root, "classifier_judge")[1] == {"slot": "classifier_judge", "rung": None}
