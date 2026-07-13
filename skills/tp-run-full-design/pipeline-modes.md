# tp-run-full-design — Pipeline Mode Axis (`--mode`)

This document specifies the `--mode {full|design|plan|build}` slot-range axis
for the `tp-run-full-design` autonomous orchestrator.  The predicate
implementation lives in
`skills/tp-run-full-design/scripts/pipeline_modes.py`.

---

## Overview

`tp-run-full-design` always walked all 11 slots to completion.  The `--mode`
flag selects a **contiguous sub-range** of the fixed slot list and the
orchestrator **stops after the range's last slot** instead of running to
Slot 11.  The default is `full` — byte-for-byte the existing whole-pipeline
behavior (backward-compatible, B1).

Each non-`full` mode still runs the audit slot for the artifacts it produces
(design→`design-audit`, plan→`plan-audit`, build→`impl-audit`), so a sliced
run is still a gated run.

---

## Mode → slot-range table

| `--mode`         | Slots run                                 | Stops after          |
|------------------|-------------------------------------------|----------------------|
| `full` (default) | 1–11 (today's whole pipeline)             | `pr-iterate` (Slot 11) |
| `design`         | `design`, `detail`, `design-audit` + PR   | scoped PR            |
| `plan`           | `plan`, `plan-audit` + PR                 | scoped PR            |
| `build`          | `phase-implement`, `impl-audit`, `design-learn`, (Tier 5.6), `PR`, `pr-iterate` | `pr-iterate` (Slot 11) |

Slot 1 (`pickup`) + lock + weight-class read always run first regardless of
mode — they resolve the branch the range operates on.

---

## Mode resolution (B7)

Resolution happens **once at arg-parse, before Slot 1**.  Precedence:

```
mode = CLI --mode  OR  pickup_contract.pipeline_mode  OR  "full"
```

- CLI `--mode` **always wins** over a pickup-contract `pipeline_mode` field.
- If CLI is valid, the pickup value is ignored — even if the pickup value is
  invalid.  This is the short-circuit rule (no raise when CLI is valid).
- If CLI is absent and the pickup value is invalid → `InvalidModeError` is
  raised immediately (fail-closed on a corrupted pickup contract).
- If both are absent → `"full"` (backward-compatible default).

When CLI overrides pickup, the orchestrator appends:

```
[tp-run-full-design/tier-1] mode-cli-overrides-pickup <cli> over <pickup>
```

to `decisions.md` (Confidence: Medium).

After mode is resolved, the chosen slot range is logged:

```
[tp-run-full-design/tier-1] mode-resolved <mode> slots=<start>…<stop>
```

---

## Invalid mode value (B10)

A value outside `{full,design,plan,build}` exits non-zero **before pickup**
and appends:

```
[tp-run-full-design/tier-0] invalid-mode <value>
```

to `decisions.md`.  No slot is dispatched; no `subagent_tokens` are spent.

---

## Slot-0 precondition gate (B5)

After Tier 1 pickup/lock but **before dispatching any Slot 2+**, the
orchestrator verifies that the required artifacts exist under the design
directory.

| `--mode` | Required artifacts present |
|----------|---------------------------|
| `full`   | none                      |
| `design` | none (Slot 2 authors them)|
| `plan`   | `design.md`, `detailed-design.md` |
| `build`  | `design.md`, `detailed-design.md`, `plan.md` |

On a missing artifact the orchestrator appends:

```
[tp-run-full-design/tier-0] mode-precondition-failed <mode> <missing-artifact>
```

and exits non-zero.  No slot subagent is dispatched; no `subagent_tokens` are
spent (fail cheap, B5).

The gate is implemented as pure `os.path.isfile` checks in
`pipeline_modes.check_preconditions()` — no subprocess, no I/O beyond stat
calls.

---

## Per-mode PR shape (B6)

The terminal PR slot titles and bodies its scope so a reviewer never expects
downstream artifacts.

| `--mode`         | PR title                | Key "NOT in this PR" note          |
|------------------|-------------------------|------------------------------------|
| `design`         | `{slug}: design only`   | `NOT in this PR: plan.md, implementation` |
| `plan`           | `{slug}: plan only`     | `NOT in this PR: implementation`   |
| `build` / `full` | `{slug}: {task_title}`  | (completion PR — all artifacts)    |

A single `pr_shape(mode, slug)` function in `pipeline_modes.py` emits all
shapes (one function, not four templates). Each mode's In/NOT-in lists are the
artifacts that mode *produces*, written as literals — deliberately distinct
from `required_artifacts()`, which returns a mode's *precondition* inputs (e.g.
`plan`'s preconditions are `design.md` + `detailed-design.md`, but its produced
artifact is `plan.md`). The scope body is therefore **not** single-sourced from
the precondition table.

---

## Tier 5.6 closeout scoping (B9)

The fold/learn-verify/`tp-design-complete` archive sequence (Tier 5.6) runs
**only when the slot range includes the worker** (`build`/`full`).

`design`/`plan` modes have no candidate code to fold: they skip Tier 5.6
and open their scoped PR directly from `tp/{slug}`.  `runs_closeout(mode)`
is the predicate (`pipeline_modes.py`).

---

## Orthogonality with `--skip-design` (B8)

`--mode` and `--skip-design` compose independently:

- **`--skip-design`** is the *entry* axis: skip Tier 1.5's interactive
  `/tp-design` front-end and read a pre-seeded `design.md` (Mode B).
- **`--mode`** is the *range* axis: where the run stops.

`--mode build --skip-design` reads the seeded `design.md`, skips Tier 1.5,
then jumps to Slot 7 (`phase-implement`).  The two flags do not interact;
both are resolved independently at arg-parse.

---

## Decisions.md token reference (B11)

All mode-resolution events are logged to `decisions.md` per
`skills/_shared/auto-mode.md`.  The four canonical token literals:

| Token                                                              | When emitted                                |
|--------------------------------------------------------------------|---------------------------------------------|
| `[tp-run-full-design/tier-0] invalid-mode`                        | Unrecognised `--mode` value at arg-parse    |
| `[tp-run-full-design/tier-0] mode-precondition-failed`            | Missing required artifact at Slot-0 gate    |
| `[tp-run-full-design/tier-1] mode-cli-overrides-pickup`           | CLI `--mode` wins over pickup `pipeline_mode` |
| `[tp-run-full-design/tier-1] mode-resolved`                       | Mode and slot range confirmed after resolution |

---

## Implementation reference

All predicates (`VALID_MODES`, `validate_mode`, `require_mode`,
`resolve_mode`, `resolve_mode_verbose`, `slot_range`, `ModeRange`,
`required_artifacts`, `check_preconditions`, `runs_closeout`, `pr_shape`)
live in `skills/tp-run-full-design/scripts/pipeline_modes.py`.

Tests: `skills/tp-run-full-design/scripts/test_pipeline_modes.py`.
