"""Tests for cheap_tier.py — the eligibility table and the two-key loader.

design: cheap-tier-offload (Tasks 1.1, 1.2).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_tier as ct  # noqa: E402
import model_policy  # noqa: E402

EIGHT = {"task", "runbook", "base_sync_splice", "pr_fix_reproducer", "classifier_judge",
         "history_line", "handoff", "docs_draft"}
PREP = {"review_slice", "review_refs", "ci_log_triage", "repro_scaffold"}  # review-prep
CORE_EXCLUDED = {"review", "impl-audit", "certify", "phase-check", "generator",
                 "phase-worker", "reader", "council", "design", "plan", "orchestrator", "merge_gate",
                 "land", "ci_local", "ci_local_stamp", "finalizer", "severity", "confirm"}


# --- Task 1.1: table, exclusions, loader, slot_rung ---------------------------------


def test_slots_are_the_twelve_rows_and_all_ship_on_but_handoff():
    assert set(ct.SLOTS) == EIGHT | PREP
    assert all(isinstance(s, ct.Slot) for s in ct.SLOTS.values())
    # operator 2026-10-07: every slot ships its local-first rung; handoff stays on Opus
    for n, s in ct.SLOTS.items():
        want = None if n == "handoff" else s.rungs[0]
        assert s.default == want, n


def test_slot_rows_shape():
    s = ct.SLOTS
    assert s["task"].rungs == ("sonnet-xhigh",) and s["task"].oracle == "task_verify"
    assert (s["runbook"].kind, s["runbook"].effect, s["runbook"].rungs) == (
        "code", "effectful", ("code",))
    assert s["base_sync_splice"].rungs == ("local-xhigh", "sonnet-xhigh")
    assert s["pr_fix_reproducer"].rungs == ("local-xhigh", "sonnet-xhigh")
    for name in ("classifier_judge", "history_line", "handoff", "docs_draft"):
        assert s[name].rungs == ("local-medium", "sonnet-medium"), name
    for name in ("history_line", "handoff", "docs_draft"):
        assert (s[name].phase, s[name].oracle, s[name].on_fail) == (3, "prose_shape", "drop")
    for row in s.values():
        assert row.kind in ("model", "code") and row.effect in ("pure", "effectful")
        assert row.on_fail in ("drop", "escalate")
        assert (row.kind == "code") == (row.rungs == ("code",))


def test_excluded_is_core_list_plus_digest_post():
    assert ct.EXCLUDED == frozenset(CORE_EXCLUDED | {"digest_post"})


def test_mirror_and_flag_values():
    assert ct.MIRROR == {"local-medium": "sonnet-medium", "local-xhigh": "sonnet-xhigh"}
    assert ct.FLAG_VALUES == (None, "on", "ab")


SHIPPED = {s: r.default for s, r in ct.SLOTS.items() if r.default is not None}


def test_roles_keys_are_skipped_first():
    assert ct.load_slots({"models": {"review": "opus"}}) == SHIPPED
    every_role = {r: model_policy.DEFAULTS[r] for r in model_policy.ROLES}
    assert ct.load_slots({"models": every_role}) == SHIPPED


@pytest.mark.parametrize("models,needle", [
    ({"digest_post": "code", "nope": "code"}, "excluded"),   # excluded before unknown
    ({"finalizer": "sonnet-xhigh"}, "excluded"),
    ({"nope": "code", "runbook": "sonnet-medium"}, "unknown"),  # unknown before rung
    ({"runbook": "sonnet-medium"}, "rung"),
    ({"handoff": "local-xhigh"}, "rung"),
    ({"task": "local-medium"}, "rung"),
])
def test_loader_refusal_order(models, needle):
    with pytest.raises(ValueError, match=needle):
        ct.load_slots({"models": models})


@pytest.mark.parametrize("removed", ["flake_triage", "decisions_entry"])
def test_removed_slot_is_unknown(removed):
    with pytest.raises(ValueError, match="unknown"):
        ct.load_slots({"models": {removed: "local-medium"}})


def test_loader_accepts_legal_rungs():
    models = {"runbook": "code", "handoff": "sonnet-medium", "task": "sonnet-xhigh",
              "review": "opus"}
    assert ct.load_slots({"models": models}) == {
        **SHIPPED, "runbook": "code", "handoff": "sonnet-medium", "task": "sonnet-xhigh"}


@pytest.mark.parametrize("config", [None, [], "x", 3, {}, {"models": None},
                                    {"models": ["runbook"]}])
def test_loader_none_or_non_dict_gives_only_the_shipped_defaults(config):
    assert ct.load_slots(config) == SHIPPED


@pytest.mark.parametrize("slot", sorted(ct.SLOTS))
def test_off_removes_the_slot_even_one_that_ships_a_default(slot):
    """models.<slot>: "off" is legal for every slot and opts the repo out of it."""
    assert ct.load_slots({"models": {slot: "off"}}) == {k: v for k, v in SHIPPED.items()
                                                        if k != slot}
    assert ct.slot_rung(slot, {"models": {slot: "off"}}, cheap_flag="on") is None


def test_off_leaves_the_other_defaults_in_place():
    got = ct.load_slots({"models": {"task": "off", "handoff": "local-medium"}})
    assert got == {**{k: v for k, v in SHIPPED.items() if k != "task"},
                   "handoff": "local-medium"}


def test_rung_refusal_names_off():
    with pytest.raises(ValueError, match=r"models\.task: rung 'opus'.*\bor 'off'\)"):
        ct.load_slots({"models": {"task": "opus"}})


@pytest.mark.parametrize("flag", [None, "on", "ab"])
@pytest.mark.parametrize("present", [True, False])
def test_slot_rung_truth_table(flag, present):
    config = {"models": {"handoff": "sonnet-medium"} if present else {}}
    want = "sonnet-medium" if (flag in ("on", "ab") and present) else None
    assert ct.slot_rung("handoff", config, cheap_flag=flag) == want


def test_slot_rung_unknown_slot_raises():
    for flag in (None, "on", "ab"):
        with pytest.raises(ValueError):
            ct.slot_rung("flake_triage", {}, cheap_flag=flag)


def test_slot_rung_flag_off_never_reads_a_bad_config():
    bad = {"models": {"review_slice": "local-medium", "merge_gate": "code"}}
    assert ct.slot_rung("handoff", bad, cheap_flag=None) is None
    with pytest.raises(ValueError):
        ct.slot_rung("handoff", bad, cheap_flag="on")


# --- Task 1.2: resolve and task_table -----------------------------------------------

LABELS = ("routed/ok", "MISSING", "router-down")
LEASES = ("free", "busy", "unchecked")


def test_resolve_matrix():
    for rung, mirror in ct.MIRROR.items():
        for label in LABELS:
            for lease in LEASES:
                got, why = ct.resolve(rung, route_label=label, lease_state=lease)
                if (label, lease) == ("routed/ok", "free"):
                    assert got == rung, (rung, label, lease)
                    continue
                assert got == mirror, (rung, label, lease)
                assert why.startswith(f"{rung}->{mirror}: "), why
                assert (label in why) if label != "routed/ok" else (f"lease {lease}" in why)
    assert ct.resolve("local-medium", route_label="routed/ok", lease_state="busy") == (
        "sonnet-medium", "local-medium->sonnet-medium: lease busy")
    for rung in ("sonnet-medium", "sonnet-xhigh", "code"):
        for label in LABELS:
            for lease in LEASES:
                assert ct.resolve(rung, route_label=label, lease_state=lease)[0] == rung


BT = chr(96)


def _task(tid, files, targets, *extra):
    lines = [f"### Task {tid}: t{tid}", f"**File**: {files}", f"**Targets**: {targets}",
             "**Red**: r.", "**Green**: g.", *extra, "**Done when**: passes."]
    return "\n".join(lines) + "\n"


def _q(path):
    return f"{BT}{path}{BT}"


PLAN = "# P\n\n## Phase 1: Things\n\n" + "\n".join([
    _task("1.1", _q("pkg/a.py"), _q("pkg/test_a.py::test_x")),
    _task("1.2", _q("pkg/b.py"), _q("pkg/test_a.py::test_y"), "**Kind**: clerical"),
    _task("1.3", ", ".join(_q(f"pkg/h{i}.py") for i in range(4)), _q("pkg/test_h.py::t")),
    _task("1.4", _q("pkg/c.py"), "none"),
    _task("1.5", _q("pkg/d.py"), _q("pkg/test_a.py::test_z"), "**Status**: Done"),
])


def test_task_table():
    import copy
    import task_eligibility as te
    rows = te.classify_phase(PLAN, 1, max_files=3, runner_ok=True, exists=lambda p: True)
    by = {r["task_id"]: r for r in rows}
    assert [by[t]["tier"] for t in ("1.1", "1.2", "1.3", "1.4")] == [
        "local", "local", "local", "local"]
    assert by["1.5"]["excluded"] and by["1.1"]["start_rung"] == "local-medium"
    before = copy.deepcopy(rows)
    out = {r["task_id"]: r for r in ct.task_table(rows)}
    assert rows == before  # the input rows are not mutated
    local = out["1.1"]
    assert (local["tier"], local["floored_from"], local["start_rung"]) == (
        "sonnet", "local", "sonnet-xhigh")
    assert local["reasons"] == by["1.1"]["reasons"] + ["cheap-tier: no --local"]
    clerical = out["1.2"]
    assert (clerical["tier"], clerical["start_rung"]) == ("sonnet", "sonnet-medium")
    assert by["1.3"]["reasons"] == ["too-many-files"]  # recorded, but still local
    assert by["1.4"]["reasons"] == ["test-not-runnable:targets-none"]
    assert out["1.3"]["tier"] == "sonnet" and out["1.3"]["floored_from"] == "local"
    # A no-oracle row is local too: without --local it is floored to its sonnet mirror, and
    # its reply still needs an Opus diff review to land (task_verify, no_oracle_review).
    assert (by["1.4"]["tier"], by["1.4"]["start_rung"]) == ("local", "local-xhigh")
    assert (out["1.4"]["tier"], out["1.4"]["floored_from"], out["1.4"]["start_rung"]) == (
        "sonnet", "local", "sonnet-xhigh")
    assert out["1.5"] == by["1.5"]
    assert list(out) == [r["task_id"] for r in rows]


# --- Task 3.1: the tp-drafter agents ------------------------------------------------


def test_drafter_agent_rows():
    import agent_ref
    assert model_policy.AGENTS["tp-drafter"] == ("drafter", "rung:local", "medium")
    assert model_policy.AGENTS["tp-drafter-xhigh"] == ("drafter", "rung:local", "xhigh")
    for name in ("tp-drafter", "tp-drafter-xhigh"):  # plugin.json lists both (audit note 1)
        assert agent_ref.resolve(name).endswith(f":{name}")
