"""prune_invalid <-> jsonschema parity cross-check (Task 1.3).

design: consumer-repo-parity (Phase 1). The stdlib-only `repo_config_load.
prune_invalid` walks a *subset* of the JSON Schema keywords; this test pins that
the two agree: on the dev-shaped config and on 17 mutated configs, the set of
dotted keys `prune_invalid` drops is exactly the set of paths jsonschema reports
an error at. `importorskip("jsonschema")`, so it skips where jsonschema is
absent. The config is an inline literal (never the committed file).
Run with: python3 -m pytest skills/_shared/test_repo_config_jsonschema_parity.py
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


def _dev() -> dict:
    """A dev-shaped config literal (all new blocks present and valid)."""
    return {
        "schema_version": 1,
        "ci": {"expects_github_checks": False, "gate_command": None},
        "review": {
            "expects_copilot": False,
            "require_human_approval": True,
            "require_ci_local_stamp": True,
            "require_review_proof": False,
            "instructions_declined": False,
            "approval_survives_safe_base_sync": True,
            "automation_identities": ["curtisthebot"],
            "proof_dir": ".three-pillars/review-proof",
        },
        "models": {"review": "opus", "fix": "sonnet", "classifier": "haiku",
                   "design_run": "claude-opus-4-1"},
        "test": {"command": "pytest -q", "runner": "pytest", "recorded_at": None},
        "commit_guard": {"offered_at": None, "applied_at": None, "declined": False,
                         "file_size": True, "deny_no_verify": True},
        "local_implement": {"enabled": True, "attempt_wall_clock_s": 1200,
                            "registry_files": ["skills/_shared/hot_patch.py"]},
        "plan_audit": {"couplings": [
            {"when_new": "skills/_shared/*hot_patch*",
             "requires_listed": "skills/_shared/hot_patch.py"}]},
        "fragility": {"gating_rules": ["wall-clock"], "strict": False,
                      "merge_predicate": True},
    }


def _ct(**over) -> dict:
    """A valid `local_implement.client_timeouts` record, with overrides."""
    return {"applied_at": None, "declined": False, "values": {}, **over}


# The 13 mutations from the design (part B, Tests) plus the run-throughput
# Task 1.1 cases. Each returns the mutated config; the dev base config itself is
# the last case.
MUTATIONS = [
    ("angle-missing-model",
     lambda c: c["review"].__setitem__("angles",
                                       [{"name": "a", "prompt": "p", "role": "confirmer"}])),
    ("schema_version-true-fatal",
     lambda c: c.update(schema_version=True)),
    ("schema_version-1.0-kept",
     lambda c: c.update(schema_version=1.0)),
    ("base_sync_carry_max_chain-bool-dropped",
     lambda c: c["review"].update(base_sync_carry_max_chain=True)),
    ("base_sync_carry_max_chain-6.0-kept",
     lambda c: c["review"].update(base_sync_carry_max_chain=6.0)),
    ("models.review-inherit-dropped",
     lambda c: c["models"].update(review="inherit")),
    ("ci.gate_command-empty-dropped",
     lambda c: c["ci"].update(gate_command="")),
    ("ci.gate_command-null-kept",
     lambda c: c["ci"].update(gate_command=None)),
    ("test.runner-bad-dropped",
     lambda c: c["test"].update(runner="shell")),
    ("models.classifier-fullid-dropped",
     lambda c: c["models"].update(classifier="claude-opus-4-1")),
    ("commit_guard.file_size-bad-dropped",
     lambda c: c["commit_guard"].update(file_size="yes")),
    ("review-unknown-key-dropped",
     lambda c: c["review"].update(some_future_key=1)),
    ("test.recorded_at-bad-dropped",
     lambda c: c["test"].update(recorded_at=5)),
    ("local_implement.attempt_wall_clock_s-bool-dropped",
     lambda c: c["local_implement"].update(attempt_wall_clock_s=True)),
    ("local_implement.attempt_wall_clock_s-30-dropped",
     lambda c: c["local_implement"].update(attempt_wall_clock_s=30)),
    ("local_implement.registry_files-string-dropped",
     lambda c: c["local_implement"].update(registry_files="a.py")),
    ("local_implement.max_output_tokens-unknown-dropped",
     lambda c: c["local_implement"].update(max_output_tokens=1200)),
    ("local_implement.client_timeouts-empty-values-kept",
     lambda c: c["local_implement"].update(client_timeouts=_ct())),
    ("local_implement.client_timeouts-one-key-kept",
     lambda c: c["local_implement"].update(
         client_timeouts=_ct(values={"API_TIMEOUT_MS": 5}))),
    ("local_implement.client_timeouts.values-extra-key-dropped",
     lambda c: c["local_implement"].update(
         client_timeouts=_ct(values={"API_TIMEOUT_MS": 5, "NOPE_MS": 1}))),
    ("local_implement.client_timeouts.values-string-dropped",
     lambda c: c["local_implement"].update(
         client_timeouts=_ct(values={"API_TIMEOUT_MS": "5"}))),
    ("local_implement.client_timeouts-missing-declined-dropped",
     lambda c: c["local_implement"].update(
         client_timeouts={"applied_at": None, "values": {}})),
    ("plan_audit.couplings-not-array-dropped",
     lambda c: c["plan_audit"].update(couplings="no")),
    ("plan_audit.couplings-item-missing-requires_listed-dropped",
     lambda c: c["plan_audit"]["couplings"].__setitem__(0,
                                                         {"when_new": "a/*.py"})),
    ("fragility.gating_rules-not-array-dropped",
     lambda c: c["fragility"].update(gating_rules="wall-clock")),
    ("fragility.strict-string-dropped",
     lambda c: c["fragility"].update(strict="yes")),
    ("fragility-unknown-key-dropped",
     lambda c: c["fragility"].update(loud=True)),
    ("fragility.merge_predicate-string-dropped",
     lambda c: c["fragility"].update(merge_predicate="no")),
    ("review.proof_dir-not-string-dropped",
     lambda c: c["review"].update(proof_dir=5)),
    ("review.proof_dir-empty-dropped",
     lambda c: c["review"].update(proof_dir="")),
    ("forge-gitea-kept",
     lambda c: c.update(forge={"kind": "gitea", "host": "gitea.lan",
                               "web_base": "https://gitea.lan",
                               "recorded_at": "2026-10-08T00:00:00+00:00"})),
    ("forge-web_base-only-kept",
     lambda c: c.update(forge={"web_base": "https://h:30008"})),
    ("forge.kind-gitlab-dropped", lambda c: c.update(forge={"kind": "gitlab"})),
    ("forge-unknown-key-dropped",
     lambda c: c.update(forge={"kind": "gitea", "token": "x"})),
]


def _json_paths(cfg):
    """Dotted paths jsonschema flags (int array indices -> str).

    An `additionalProperties: false` violation is reported at the PARENT path
    with `e.instance` the offending object; expand it to the offending key so it
    lines up with `prune_invalid`, which drops the key itself (`<parent>.<key>`).
    """
    out = set()
    for e in VALIDATOR.iter_errors(cfg):
        segs = list(e.absolute_path)
        if e.validator == "additionalProperties" and isinstance(e.instance, dict):
            props = (e.schema or {}).get("properties", {})
            unknown = [k for k in e.instance if k not in props]
            if unknown:
                for k in unknown:
                    out.add(".".join(str(s) for s in segs + [k]))
                continue
        out.add(".".join(str(s) for s in segs))
    return out


def _parity(cfg):
    """Return (json_paths, prune_paths, fatal) for one config."""
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    json_p = _json_paths(cfg)
    prune_p = set()
    for w in warnings:
        if "config: dropped " in w:
            key = w.split("config: dropped ", 1)[1].split(" (", 1)[0].strip()
            if key:
                prune_p.add(key)
    fatal = (pruned == {} and len(warnings) == 1
             and "schema_version" in warnings[0] and "ignored" in warnings[0])
    if fatal:
        # The whole config is dropped, but the root cause (and jsonschema's
        # flagged path) is schema_version itself.
        prune_p = {"schema_version"}
    return pruned, json_p, prune_p, fatal


def test_parity_base_dev_config_clean():
    pruned, json_p, prune_p, fatal = _parity(_dev())
    assert not fatal
    assert VALIDATOR.is_valid(pruned)  # the pruned config validates under jsonschema
    assert prune_p == json_p == set()


@pytest.mark.parametrize("name,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_parity_prune_agrees_with_jsonschema(name, mutate):
    cfg = _dev()
    mutate(cfg)
    pruned, json_p, prune_p, fatal = _parity(cfg)
    # Non-fatal: a valid key set survives, so the pruned config validates.
    # (The fatal schema_version case returns {} by the fail-closed rule — the
    # "whole config absent" signal, intentionally not a valid config — and is
    # covered by test_parity_fatal_schema_version_flags_the_version_key.)
    if not fatal:
        assert VALIDATOR.is_valid(pruned), (name, "pruned config did not validate:", pruned)
    assert prune_p == json_p, (name, "prune:", prune_p, "jsonschema:", json_p)


def test_parity_fatal_schema_version_flags_the_version_key():
    cfg = _dev()
    cfg["schema_version"] = True
    pruned, json_p, prune_p, fatal = _parity(cfg)
    assert fatal
    assert json_p == prune_p == {"schema_version"}


def test_parity_kept_mutations_drop_nothing():
    for name in ("schema_version-1.0-kept", "base_sync_carry_max_chain-6.0-kept",
                 "ci.gate_command-null-kept",
                 "local_implement.client_timeouts-empty-values-kept",
                 "local_implement.client_timeouts-one-key-kept",
                 "forge-gitea-kept", "forge-web_base-only-kept"):
        _, mutate = next(m for m in MUTATIONS if m[0] == name)
        cfg = _dev()
        mutate(cfg)
        pruned, json_p, prune_p, fatal = _parity(cfg)
        assert not fatal, name
        assert VALIDATOR.is_valid(pruned), name
        assert prune_p == json_p == set(), name
