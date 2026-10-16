"""Tests for the consumer-repo-parity Phase 1 schema additions (Task 1.3).

Split out of test_repo_config.py (past its soft cap): the new blocks
(ci.gate_command, the three review booleans, and the top-level test / models /
commit_guard) are accepted by the jsonschema validator, an unknown key in each
new block is still rejected, and the later tasks' writes succeed through the
Task 1.2 writer (the enum-only models.review value still raises).
Run with: python3 -m pytest skills/_shared/test_repo_config_new_keys.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402

jsonschema = pytest.importorskip("jsonschema")
Draft202012Validator = jsonschema.Draft202012Validator

SCHEMA = json.loads(
    (Path(__file__).resolve().parent / "repo-config.schema.json").read_text(encoding="utf-8")
)
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def _cfg(**extra) -> dict:
    cfg = {"schema_version": 1}
    cfg.update(extra)
    return cfg


def _errors(cfg):
    return list(VALIDATOR.iter_errors(cfg))


# --- ci.gate_command (string|null, minLength 1) -------------------------------

def test_ci_gate_command_accepts_string_and_null():
    assert _errors(_cfg(ci={"gate_command": "pytest -q"})) == []
    assert _errors(_cfg(ci={"gate_command": None})) == []


def test_ci_gate_command_rejects_empty_and_non_string():
    assert _errors(_cfg(ci={"gate_command": ""}))
    assert _errors(_cfg(ci={"gate_command": 5}))


# --- the three new review booleans --------------------------------------------

@pytest.mark.parametrize("key", ["require_ci_local_stamp", "require_review_proof",
                                 "instructions_declined"])
@pytest.mark.parametrize("value", [True, False])
def test_review_new_booleans_accepted(key, value):
    assert _errors(_cfg(review={key: value})) == []


@pytest.mark.parametrize("key", ["require_ci_local_stamp", "require_review_proof",
                                 "instructions_declined"])
def test_review_new_booleans_reject_non_bool(key):
    assert _errors(_cfg(review={key: "no"}))


# --- test block -----------------------------------------------------------------

def test_test_block_accepts_all_shapes():
    assert _errors(_cfg(test={"command": "pytest -q", "runner": "pytest",
                              "recorded_at": "2026-09-26T00:00:00Z"})) == []
    assert _errors(_cfg(test={"command": None, "runner": "other",
                              "recorded_at": None})) == []


def test_test_block_rejects_bad_values():
    assert _errors(_cfg(test={"command": 5}))
    assert _errors(_cfg(test={"runner": "shell"}))
    assert _errors(_cfg(test={"recorded_at": 5}))


# --- models block ----------------------------------------------------------------

@pytest.mark.parametrize("role", ["review", "fix", "classifier"])
@pytest.mark.parametrize("model", ["opus", "sonnet", "haiku", "fable"])
def test_models_roles_accept_the_four_aliases(role, model):
    assert _errors(_cfg(models={role: model})) == []


@pytest.mark.parametrize("role", ["review", "fix", "classifier"])
def test_models_roles_reject_inherit_and_full_id(role):
    assert _errors(_cfg(models={role: "inherit"}))
    assert _errors(_cfg(models={role: "claude-opus-4-1"}))


def test_models_design_run_accepts_any_non_empty_string():
    assert _errors(_cfg(models={"design_run": "opus"})) == []
    assert _errors(_cfg(models={"design_run": "claude-opus-4-1"})) == []
    assert _errors(_cfg(models={"design_run": ""}))
    assert _errors(_cfg(models={"design_run": 5}))


# --- commit_guard block ----------------------------------------------------------

def test_commit_guard_accepts_full_block():
    assert _errors(_cfg(commit_guard={
        "offered_at": "2026-09-26T00:00:00Z", "applied_at": None,
        "declined": False, "file_size": True, "deny_no_verify": True})) == []


def test_commit_guard_rejects_bad_value():
    assert _errors(_cfg(commit_guard={"file_size": "yes"}))
    assert _errors(_cfg(commit_guard={"deny_no_verify": 1}))
    assert _errors(_cfg(commit_guard={"offered_at": 5}))


# --- local_implement.attempt_wall_clock_s (run-throughput Task 1.1) --------------

def test_local_implement_attempt_wall_clock_s_accepted():
    assert _errors(_cfg(local_implement={"attempt_wall_clock_s": 60})) == []
    assert _errors(_cfg(local_implement={"attempt_wall_clock_s": 1200})) == []


def test_local_implement_attempt_wall_clock_s_rejected():
    assert _errors(_cfg(local_implement={"attempt_wall_clock_s": 30}))
    assert _errors(_cfg(local_implement={"attempt_wall_clock_s": True}))
    assert _errors(_cfg(local_implement={"attempt_wall_clock_s": "20m"}))


def test_local_implement_unknown_key_still_rejected():
    assert _errors(_cfg(local_implement={"some_future_key": 1}))


def test_prune_keeps_attempt_wall_clock_s_and_drops_max_output_tokens():
    cfg = {"schema_version": 1,
           "local_implement": {"enabled": True, "attempt_wall_clock_s": 1200,
                               "max_output_tokens": 1200}}
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    assert pruned["local_implement"]["attempt_wall_clock_s"] == 1200
    assert pruned["local_implement"]["enabled"] is True
    assert "max_output_tokens" not in pruned["local_implement"]
    assert any("local_implement.max_output_tokens" in w for w in warnings)


# --- the Task 1.2 writer now succeeds on the new keys ---------------------------

def _seeded_repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    cfg_dir = root / ".three-pillars"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"schema_version": 1}) + "\n",
                                          encoding="utf-8")
    return root


def test_update_config_creates_test_block(tmp_path):
    root = _seeded_repo(tmp_path)
    rcl.update_config(root, "test.command", "pytest -q")
    written = json.loads((root / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    assert written["test"]["command"] == "pytest -q"


def test_update_config_models_review_inherit_still_raises(tmp_path):
    root = _seeded_repo(tmp_path)
    with pytest.raises(ValueError):
        rcl.update_config(root, "models.review", "inherit")


# --- local_implement.registry_files (run-throughput Task 5.2) ----------------------

def test_registry_files_accepted_and_rejected():
    assert _errors(_cfg(local_implement={"registry_files": []})) == []
    assert _errors(_cfg(local_implement={"registry_files": ["skills/_shared/hot_patch.py"]})) == []
    assert _errors(_cfg(local_implement={"registry_files": "a.py"}))
    assert _errors(_cfg(local_implement={"registry_files": [1]}))


def test_prune_keeps_registry_files():
    cfg = {"schema_version": 1, "local_implement": {"registry_files": ["a.py"]}}
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    assert pruned["local_implement"]["registry_files"] == ["a.py"]
    assert warnings == []


# --- plan_audit.couplings (run-throughput Task 5.7) ------------------------------

def test_plan_audit_couplings_accepted():
    assert _errors(_cfg(plan_audit={"couplings": []})) == []
    assert _errors(_cfg(plan_audit={"couplings": [
        {"when_new": "skills/_shared/*hot_patch*",
         "requires_listed": "skills/_shared/hot_patch.py"}]})) == []
    assert _errors(_cfg(plan_audit={
        "couplings": [
            {"when_new": "a/*.py", "requires_listed": "b/c.py"},
            {"when_new": "d/*", "requires_listed": "e/f.py"},
        ]})) == []


def test_plan_audit_couplings_rejected():
    # non-list, non-dict item, missing/empty/non-string required fields,
    # unknown key in the block or the item
    assert _errors(_cfg(plan_audit={"couplings": "no"}))
    assert _errors(_cfg(plan_audit={"couplings": [1]}))
    assert _errors(_cfg(plan_audit={"couplings": [
        {"requires_listed": "a.py"}]}))
    assert _errors(_cfg(plan_audit={"couplings": [
        {"when_new": "a/*.py"}]}))
    assert _errors(_cfg(plan_audit={"couplings": [
        {"when_new": "", "requires_listed": "a.py"}]}))
    assert _errors(_cfg(plan_audit={"couplings": [
        {"when_new": "a/*.py", "requires_listed": ""}]}))
    assert _errors(_cfg(plan_audit={"couplings": [
        {"when_new": 5, "requires_listed": "a.py"}]}))
    assert _errors(_cfg(plan_audit={"couplings": [
        {"when_new": "a/*.py", "requires_listed": "a.py", "extra": 1}]}))
    assert _errors(_cfg(plan_audit={"some_future_key": 1}))


def test_prune_keeps_plan_audit_couplings():
    cfg = {"schema_version": 1, "plan_audit": {
        "couplings": [{"when_new": "skills/_shared/*hot_patch*",
                       "requires_listed": "skills/_shared/hot_patch.py"}]}}
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    assert pruned["plan_audit"]["couplings"] == [
        {"when_new": "skills/_shared/*hot_patch*",
         "requires_listed": "skills/_shared/hot_patch.py"}]
    assert warnings == []


# --- merge_from_main.generators (basesync-autoresolve-coverage Task 2.3) ---------

_GEN = {"path": ".claude-plugin/plugin.json",
        "write": ["python3", "x.py", "--write"],
        "check": ["python3", "x.py", "--check"]}


def test_merge_from_main_generators_accepted():
    assert _errors(_cfg(merge_from_main={"generators": [dict(_GEN)]})) == []
    assert _errors(_cfg(merge_from_main={"generators": []})) == []
    # `check` is optional
    assert _errors(_cfg(merge_from_main={"generators": [
        {"path": "a.json", "write": ["x"]}]})) == []


def test_merge_from_main_rejects_unknown_keys():
    assert _errors(_cfg(merge_from_main={"some_future_key": 1}))
    assert _errors(_cfg(merge_from_main={"generators": [dict(_GEN, extra=1)]}))


def test_merge_from_main_rejects_malformed_generator_items():
    assert _errors(_cfg(merge_from_main={"generators": "no"}))
    assert _errors(_cfg(merge_from_main={"generators": [1]}))
    assert _errors(_cfg(merge_from_main={"generators": [{"write": ["x"]}]}))
    assert _errors(_cfg(merge_from_main={"generators": [{"path": "a.json"}]}))
    assert _errors(_cfg(merge_from_main={"generators": [
        {"path": "", "write": ["x"]}]}))
    assert _errors(_cfg(merge_from_main={"generators": [
        {"path": "a.json", "write": "python3 x.py"}]}))
    assert _errors(_cfg(merge_from_main={"generators": [
        {"path": "a.json", "write": ["x", 1]}]}))
    assert _errors(_cfg(merge_from_main={"generators": [
        {"path": "a.json", "write": ["x"], "check": "x --check"}]}))


def test_prune_keeps_merge_from_main_generators():
    cfg = _cfg(merge_from_main={"generators": [dict(_GEN)]})
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    assert pruned["merge_from_main"] == {"generators": [_GEN]}
    assert warnings == []
