---
name: tp-spec
description: Manage living spec deltas — scaffold, validate, and merge spec-delta.md files into domain base specs.
argument-hint: "{add|validate|merge} <design-name> [--domain <domain>]"
---

# /tp-spec

Manage living spec deltas for a design: scaffold, validate, and merge
spec-delta.md files into their domain base spec.

**Argument**: `<design-name>` (required) — must match an existing directory
under `three-pillars-docs/tp-designs/`. Design names use only `[a-z0-9-]`
characters; reject anything else before proceeding (see `skills/_shared/validate-name.md`).

## Steps

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

1. Dispatch to the subcommand — see §Subcommands below.

## Subcommands

### `add <design>`

Scaffold a `spec-delta.md` in the design directory from the template.

**Refuse-to-clobber**: if `spec-delta.md` already exists it is left untouched
and the command exits 0 with a notice.  In `--auto` mode this is a silent no-op.

```
/tp-spec add <design-name>
```

Creates: `three-pillars-docs/tp-designs/<design>/spec-delta.md`
Template: `skills/tp-spec/templates/spec-delta.template.md`

### `validate <design>`

Validate the design's `spec-delta.md` structurally, then run the drift scan
over the matching domain spec tree.

```
/tp-spec validate <design-name> [--domain <domain>]
```

**Validator API (exact signature)**:
```python
from validate_artifact import validate_artifact
from pathlib import Path

verdict = validate_artifact("spec", Path(delta_path))   # type-first, Path arg
```

On BLOCKED: JSON verdict is printed to stderr and the command exits 1.
On PASS: runs `spec_drift.py scan` over `three-pillars-docs/specs/` and exits
with its exit code (0 clean / 1 DRIFT).

The nonexistent `.validate(text, type)` signature is never used.

### `merge <design>`

Merge the design's `spec-delta.md` into the domain base spec via the engine.

```
/tp-spec merge <design-name> [--domain <domain>]
```

**Engine call (exact signature)**:
```python
from spec_delta import merge, MergeConflict, SpecParseError

merged_text = merge(base_text, [delta_text])   # base_text: str, list of delta str
```

- On `MergeConflict` or `SpecParseError`: base is **not** written; JSON verdict
  is printed to stderr; exits 1 (refuse-on-conflict).
- When no `spec-delta.md` exists: no-op skip, exits 0.
- Domain defaults to `<design-name>` when `--domain` is omitted.

Reads: `three-pillars-docs/tp-designs/<design>/spec-delta.md`
Writes: `three-pillars-docs/specs/<domain>/spec.md`

## Exit Codes

| Code | Meaning |
|------|---------|
| 0    | Success or no-op skip |
| 1    | BLOCKED / DRIFT / MergeConflict |
| 2    | Usage error |

## Implementation

Backend: `skills/tp-spec/tp_spec.py`
Template: `skills/tp-spec/templates/spec-delta.template.md`
Tests: `skills/tp-spec/test_tp_spec.py`

Depends on:
- `skills/_shared/validate_artifact.py` — `validate_artifact(type, path)`
- `skills/_shared/spec_delta.py` — `merge(base_text, deltas)`
- `skills/_shared/spec_drift.py` — `main(["scan", specs_dir, ...])`
