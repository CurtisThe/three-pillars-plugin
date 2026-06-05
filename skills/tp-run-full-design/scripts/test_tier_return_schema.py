"""Schema tests for the per-tier return envelopes.

Covers the four schemas the orchestrator validates tier subagent replies
against:
  - tier-return.v1.json   (base: schema/slot/status/summary + optional telemetry)
  - generator-return.v1.json  (allOf base + artifact_paths[])
  - audit-return.v1.json      (allOf base + verdict + findings[])
  - handoff.v1.json           (standalone pre-split/cold-resume envelope)

Derived schemas inherit the base via `allOf` + `$ref` by `$id`; resolution
goes through a `referencing.Registry` built from every schema in the dir,
mirroring how `parse_tier_return` resolves them at runtime.
"""

import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
BASE = SCHEMAS_DIR / "tier-return.v1.json"
GENERATOR = SCHEMAS_DIR / "generator-return.v1.json"
AUDIT = SCHEMAS_DIR / "audit-return.v1.json"
HANDOFF = SCHEMAS_DIR / "handoff.v1.json"
ROUND1 = SCHEMAS_DIR / "council-round1.v1.json"
ROUND2 = SCHEMAS_DIR / "council-round2.v1.json"
ROUND_BUNDLE = SCHEMAS_DIR / "council-round-bundle.v1.json"


def _registry() -> Registry:
    resources = []
    for p in SCHEMAS_DIR.glob("*.json"):
        schema = json.loads(p.read_text())
        if "$id" in schema:
            resources.append(
                (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT7))
            )
    return Registry().with_resources(resources)


def _is_valid(schema_path: Path, instance: dict) -> bool:
    schema = json.loads(schema_path.read_text())
    validator = jsonschema.Draft7Validator(schema, registry=_registry())
    return validator.is_valid(instance)


# --------------------------------------------------------------------------- #
# Task 2.1 — base tier-return schema
# --------------------------------------------------------------------------- #
def _valid_base() -> dict:
    return {
        "schema": "tp-run-full-design/tier-return/v1",
        "slot": "design",
        "status": "pass",
        "summary": "produced design.md",
        # tokens_used is advisory/nullable per spike F4 (self-report undercounts ~50%).
        "telemetry": {"duration_ms": 1200, "tool_calls": 7, "tokens_used": None},
    }


def test_base_valid_passes():
    assert _is_valid(BASE, _valid_base())


def test_base_missing_schema_fails():
    inst = _valid_base()
    del inst["schema"]
    assert not _is_valid(BASE, inst)


def test_base_missing_slot_fails():
    inst = _valid_base()
    del inst["slot"]
    assert not _is_valid(BASE, inst)


def test_base_missing_status_fails():
    inst = _valid_base()
    del inst["status"]
    assert not _is_valid(BASE, inst)


def test_base_missing_summary_fails():
    inst = _valid_base()
    del inst["summary"]
    assert not _is_valid(BASE, inst)


def test_base_status_enum_rejects_unknown():
    inst = _valid_base()
    inst["status"] = "definitely-not-a-status"
    assert not _is_valid(BASE, inst)


def test_base_status_enum_accepts_all_four():
    for status in ("pass", "needs-work", "handoff-pending", "errored"):
        inst = _valid_base()
        inst["status"] = status
        assert _is_valid(BASE, inst), status


def test_base_telemetry_tokens_used_nullable():
    inst = _valid_base()
    inst["telemetry"]["tokens_used"] = None
    assert _is_valid(BASE, inst)
    inst["telemetry"]["tokens_used"] = 4321
    assert _is_valid(BASE, inst)


def test_base_telemetry_optional():
    inst = _valid_base()
    del inst["telemetry"]
    assert _is_valid(BASE, inst)


def test_base_additional_properties_allowed():
    inst = _valid_base()
    inst["extra_unmodeled_field"] = {"anything": True}
    assert _is_valid(BASE, inst)


# --------------------------------------------------------------------------- #
# Task 2.2 — generator-return schema (allOf base + artifact_paths[])
# --------------------------------------------------------------------------- #
def _valid_generator() -> dict:
    return {
        "schema": "tp-run-full-design/generator-return/v1",
        "slot": "design",
        "status": "pass",
        "summary": "wrote design.md",
        "artifact_paths": ["three-pillars-docs/tp-designs/x/design.md"],
    }


def test_generator_valid_passes():
    assert _is_valid(GENERATOR, _valid_generator())


def test_generator_missing_artifact_paths_fails():
    inst = _valid_generator()
    del inst["artifact_paths"]
    assert not _is_valid(GENERATOR, inst)


def test_generator_empty_artifact_paths_fails():
    inst = _valid_generator()
    inst["artifact_paths"] = []
    assert not _is_valid(GENERATOR, inst)


def test_generator_artifact_paths_must_be_strings():
    inst = _valid_generator()
    inst["artifact_paths"] = [123]
    assert not _is_valid(GENERATOR, inst)


def test_generator_inherits_base_missing_status_fails():
    # Proves allOf inheritance: dropping a base-required field invalidates.
    inst = _valid_generator()
    del inst["status"]
    assert not _is_valid(GENERATOR, inst)


def test_generator_inherits_base_status_enum():
    inst = _valid_generator()
    inst["status"] = "not-a-status"
    assert not _is_valid(GENERATOR, inst)


# --------------------------------------------------------------------------- #
# Task 2.3 — audit-return schema (allOf base + verdict + findings[])
# --------------------------------------------------------------------------- #
def _valid_audit() -> dict:
    return {
        "schema": "tp-run-full-design/audit-return/v1",
        "slot": "design-audit",
        "status": "pass",
        "summary": "audited design.md",
        "verdict": "pass-with-notes",
        "findings": [
            {
                "confidence": "high",
                "category": "INCONSISTENT",
                "description": "field X drifts from interface",
                "suggested_fix": "rename field X to Y",
            }
        ],
    }


def test_audit_valid_passes():
    assert _is_valid(AUDIT, _valid_audit())


def test_audit_empty_findings_allowed():
    # pass / pass-with-notes may carry an empty findings array (a clean pass has
    # nothing to report). Only needs-work requires findings — see below.
    inst = _valid_audit()  # verdict = pass-with-notes
    inst["findings"] = []
    assert _is_valid(AUDIT, inst)


def test_audit_needs_work_requires_findings():
    # needs-work + no findings gives retry-with-advice nothing to relay, so the
    # schema rejects it (audit-return.v1.json if/then on verdict == needs-work).
    inst = _valid_audit()
    inst["verdict"] = "needs-work"
    inst["findings"] = []
    assert not _is_valid(AUDIT, inst)


def test_audit_needs_work_with_findings_passes():
    inst = _valid_audit()
    inst["verdict"] = "needs-work"  # _valid_audit() already carries one finding
    assert _is_valid(AUDIT, inst)


def test_audit_missing_verdict_fails():
    inst = _valid_audit()
    del inst["verdict"]
    assert not _is_valid(AUDIT, inst)


def test_audit_bad_verdict_enum_fails():
    inst = _valid_audit()
    inst["verdict"] = "looks-fine-ship-it"
    assert not _is_valid(AUDIT, inst)


def test_audit_verdict_enum_accepts_all_three():
    for verdict in ("pass", "pass-with-notes", "needs-work"):
        inst = _valid_audit()
        inst["verdict"] = verdict
        assert _is_valid(AUDIT, inst), verdict


def test_audit_missing_findings_fails():
    inst = _valid_audit()
    del inst["findings"]
    assert not _is_valid(AUDIT, inst)


def test_audit_finding_missing_confidence_fails():
    inst = _valid_audit()
    del inst["findings"][0]["confidence"]
    assert not _is_valid(AUDIT, inst)


def test_audit_finding_bad_confidence_enum_fails():
    inst = _valid_audit()
    inst["findings"][0]["confidence"] = "maybe"
    assert not _is_valid(AUDIT, inst)


def test_audit_inherits_base_missing_slot_fails():
    inst = _valid_audit()
    del inst["slot"]
    assert not _is_valid(AUDIT, inst)


# --------------------------------------------------------------------------- #
# Task 2.4 — handoff schema (standalone pre-split / cold-resume envelope)
# --------------------------------------------------------------------------- #
def _valid_handoff() -> dict:
    return {
        "schema": "tp-run-full-design/handoff/v1",
        "slot": "plan-audit",
        "attempt": 2,
        "partial_state": "rounds 1-2 of council complete; round 3 pending",
        "next_action": "resume council round 3 for ada and feynman",
        "files_to_continue_with": ["three-pillars-docs/tp-designs/x/plan.md"],
        "remaining_budget_estimate": 120000,
    }


REQUIRED_HANDOFF_FIELDS = [
    "schema",
    "slot",
    "attempt",
    "partial_state",
    "next_action",
    "files_to_continue_with",
    "remaining_budget_estimate",
]


def test_handoff_valid_passes():
    assert _is_valid(HANDOFF, _valid_handoff())


def test_handoff_each_required_field_enforced():
    for field in REQUIRED_HANDOFF_FIELDS:
        inst = _valid_handoff()
        del inst[field]
        assert not _is_valid(HANDOFF, inst), f"missing {field} should fail"


def test_handoff_missing_next_action_fails():
    inst = _valid_handoff()
    del inst["next_action"]
    assert not _is_valid(HANDOFF, inst)


def test_handoff_files_to_continue_with_must_be_array():
    inst = _valid_handoff()
    inst["files_to_continue_with"] = "three-pillars-docs/tp-designs/x/plan.md"
    assert not _is_valid(HANDOFF, inst)


def test_handoff_schema_const_pinned():
    inst = _valid_handoff()
    inst["schema"] = "tp-run-full-design/handoff/v999"
    assert not _is_valid(HANDOFF, inst)


# --------------------------------------------------------------------------- #
# Task 1.1 — council-round1 schema (Round-1 verdict envelope)
# --------------------------------------------------------------------------- #
def _valid_round1() -> dict:
    return {
        "schema": "tp-run-full-design/council-round1/v1",
        "member": "council-torvalds",
        "verdict": "pass-with-notes",
        "confidence": "high",
        "findings": [
            {
                "confidence": "high",
                "category": "INCONSISTENT",
                "description": "plan task 2 drifts from detailed-design §3",
                "suggested_fix": "align field name to the design",
                "where": "plan.md:42",
            }
        ],
        "argument_summary": "The plan is coherent but task 2 names a field the design renamed.",
    }


ROUND1_REQUIRED_ENVELOPE = [
    "schema",
    "member",
    "verdict",
    "confidence",
    "findings",
    "argument_summary",
]


def test_council_round1_valid_passes():
    assert _is_valid(ROUND1, _valid_round1())


def test_council_round1_each_required_field_enforced():
    for field in ROUND1_REQUIRED_ENVELOPE:
        inst = _valid_round1()
        del inst[field]
        assert not _is_valid(ROUND1, inst), f"missing {field} should fail"


def test_council_round1_verdict_enum_accepts_all_three():
    for verdict in ("pass", "pass-with-notes", "needs-work"):
        inst = _valid_round1()
        inst["verdict"] = verdict
        assert _is_valid(ROUND1, inst), verdict


def test_council_round1_verdict_enum_rejects_unknown():
    inst = _valid_round1()
    inst["verdict"] = "ship-it"
    assert not _is_valid(ROUND1, inst)


def test_council_round1_confidence_enum_accepts_all_three():
    for conf in ("high", "medium", "low"):
        inst = _valid_round1()
        inst["confidence"] = conf
        assert _is_valid(ROUND1, inst), conf


def test_council_round1_confidence_enum_rejects_unknown():
    inst = _valid_round1()
    inst["confidence"] = "maybe"
    assert not _is_valid(ROUND1, inst)


def test_council_round1_finding_missing_confidence_fails():
    # F3 — per-finding confidence mirrors audit-return.v1 finding shape.
    inst = _valid_round1()
    del inst["findings"][0]["confidence"]
    assert not _is_valid(ROUND1, inst)


def test_council_round1_finding_requires_audit_return_shape():
    for field in ("confidence", "category", "description", "suggested_fix"):
        inst = _valid_round1()
        del inst["findings"][0][field]
        assert not _is_valid(ROUND1, inst), f"finding missing {field} should fail"


def test_council_round1_finding_where_optional():
    inst = _valid_round1()
    del inst["findings"][0]["where"]
    assert _is_valid(ROUND1, inst)


def test_council_round1_empty_findings_allowed():
    inst = _valid_round1()
    inst["findings"] = []
    assert _is_valid(ROUND1, inst)


def test_council_round1_schema_const_pinned():
    inst = _valid_round1()
    inst["schema"] = "tp-run-full-design/council-round1/v999"
    assert not _is_valid(ROUND1, inst)


def test_council_round1_id_is_urn():
    schema = json.loads(ROUND1.read_text())
    assert schema["$id"] == "urn:tp-run-full-design:council-round1:v1"


# --------------------------------------------------------------------------- #
# Task 1.2 — council-round2 schema (Round-2 rebuttal envelope)
# --------------------------------------------------------------------------- #
def _valid_round2() -> dict:
    return {
        "schema": "tp-run-full-design/council-round2/v1",
        "member": "council-ada",
        "position_held": "held",
        "counter_argument": "I disagree with torvalds's finding 0; the field rename is intentional.",
        "challenged_finding_indices": [0, 2],
    }


ROUND2_REQUIRED = ["schema", "member", "position_held", "counter_argument"]


def test_council_round2_valid_passes():
    assert _is_valid(ROUND2, _valid_round2())


def test_council_round2_each_required_field_enforced():
    for field in ROUND2_REQUIRED:
        inst = _valid_round2()
        del inst[field]
        assert not _is_valid(ROUND2, inst), f"missing {field} should fail"


def test_council_round2_position_held_enum_accepts_both():
    for pos in ("held", "revised"):
        inst = _valid_round2()
        inst["position_held"] = pos
        assert _is_valid(ROUND2, inst), pos


def test_council_round2_position_held_enum_rejects_unknown():
    inst = _valid_round2()
    inst["position_held"] = "abstained"
    assert not _is_valid(ROUND2, inst)


def test_council_round2_challenged_indices_optional():
    # F4 — challenged_finding_indices is optional.
    inst = _valid_round2()
    del inst["challenged_finding_indices"]
    assert _is_valid(ROUND2, inst)


def test_council_round2_challenged_indices_accepts_integer_array():
    inst = _valid_round2()
    inst["challenged_finding_indices"] = [0, 1, 5]
    assert _is_valid(ROUND2, inst)


def test_council_round2_challenged_indices_rejects_non_integer():
    inst = _valid_round2()
    inst["challenged_finding_indices"] = ["zero", 1]
    assert not _is_valid(ROUND2, inst)


def test_council_round2_schema_const_pinned():
    inst = _valid_round2()
    inst["schema"] = "tp-run-full-design/council-round2/v999"
    assert not _is_valid(ROUND2, inst)


def test_council_round2_id_is_urn():
    schema = json.loads(ROUND2.read_text())
    assert schema["$id"] == "urn:tp-run-full-design:council-round2:v1"


# --------------------------------------------------------------------------- #
# Task 1.3 — council-round-bundle schema (the wrapper /council --orchestrator emits)
# --------------------------------------------------------------------------- #
def _valid_bundle() -> dict:
    return {
        "schema": "tp-run-full-design/council-round-bundle/v1",
        "round": 1,
        "members": ["council-torvalds", "council-ada", "council-feynman"],
        "outputs": [_valid_round1(), _valid_round1(), _valid_round1()],
    }


BUNDLE_REQUIRED = ["schema", "round", "members", "outputs"]


def test_council_round_bundle_valid_passes():
    assert _is_valid(ROUND_BUNDLE, _valid_bundle())


def test_council_round_bundle_each_required_field_enforced():
    for field in BUNDLE_REQUIRED:
        inst = _valid_bundle()
        del inst[field]
        assert not _is_valid(ROUND_BUNDLE, inst), f"missing {field} should fail"


def test_council_round_bundle_round_accepts_1_and_2():
    for rnd in (1, 2):
        inst = _valid_bundle()
        inst["round"] = rnd
        assert _is_valid(ROUND_BUNDLE, inst), rnd


def test_council_round_bundle_round_rejects_3():
    inst = _valid_bundle()
    inst["round"] = 3
    assert not _is_valid(ROUND_BUNDLE, inst)


def test_council_round_bundle_outputs_typed_loosely():
    # Per §6 the bundle schema types outputs[] loosely as object — a minimal
    # {} output item does not fail the BUNDLE schema (per-member validation is
    # the second step).
    inst = _valid_bundle()
    inst["outputs"] = [{}]
    assert _is_valid(ROUND_BUNDLE, inst)


def test_council_round_bundle_schema_const_pinned():
    inst = _valid_bundle()
    inst["schema"] = "tp-run-full-design/council-round-bundle/v999"
    assert not _is_valid(ROUND_BUNDLE, inst)


def test_council_round_bundle_id_is_urn():
    schema = json.loads(ROUND_BUNDLE.read_text())
    assert schema["$id"] == "urn:tp-run-full-design:council-round-bundle:v1"


def test_all_three_new_schemas_load_without_id_collision():
    # All three new schemas register into the same Registry glob without
    # $id collision (Task 1.3 Done-when).
    reg = _registry()
    for urn in (
        "urn:tp-run-full-design:council-round1:v1",
        "urn:tp-run-full-design:council-round2:v1",
        "urn:tp-run-full-design:council-round-bundle:v1",
    ):
        assert reg.get_or_retrieve(urn) is not None
