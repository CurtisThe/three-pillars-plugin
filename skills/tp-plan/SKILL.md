---
name: tp-plan
description: Generate a plan.md from detailed-design.md — a sequenced list of implementation tasks, each with test criteria, ready for /tp-phase-implement.
argument-hint: "{design-name} [--auto] [--patch <findings.json>] [--force-takeover]"
---

# Phase Plan

Turn a detailed design into a concrete, executable task list.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/detailed-design.md` must exist. If not, tell the user to run `/tp-design-detail {design-name}` first and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "plan"`. This verifies the branch and refreshes the lock for this design. Honor `--force-takeover` if passed.
2. **Read both `design.md` and `detailed-design.md`** from the design directory.
3. **Check upstream dependency status**: Read the `## Dependencies` section of `design.md` (or `## Upstream Design Dependencies` in `detailed-design.md`). For each named dependency, look up its status in the Design Inventory table of `three-pillars-docs/product_roadmap.md`. If any dependency has a NO-GO verdict or is still in-progress ("Spiking", "Designed", "Planned"), warn the user with specific context:
   > **Dependency warning**: `{dependency-name}` is currently `{status}`. This design declares it as a dependency. Proceeding with planning may produce a plan that can't be implemented if the dependency doesn't resolve.
   If the dependency's row is not in the live Design Inventory, look it up in `## Design Inventory — completed and superseded rows` of `three-pillars-docs/product_roadmap_archive.md` — completed rows live there, and the same NO-GO / in-progress warnings apply to the archived row.
   If the dependency is "Done — NO-GO", include the spike's verdict reason if available from the roadmap prose. **Do not block** — the user may have good reasons to proceed. If the roadmap doesn't exist or the design has no Dependencies section, skip this step silently.
4. **Read the implementation order** from detailed-design.md. This is your skeleton.
5. **Break each phase into discrete tasks**. Each task must be:
   - **Small enough** to implement in a single red-green-refactor cycle (typically one function or one class method)
   - **Independently testable** — completing the task means tests pass
   - **Ordered** — later tasks can depend on earlier ones, but not vice versa
6. **Write `three-pillars-docs/tp-designs/{design-name}/plan.md`** using this exact format. The frontmatter carries `plan-schema: 2` beside `weight-class`: if design.md carries a `weight-class` frontmatter block, stamp the same class onto plan.md (via `weight_class.py`'s `write_class` or the `---\nweight-class: <class>\nplan-schema: 2\n---` block directly at the top — the class propagates from design.md to every generated artifact; `plan-schema: 2` is this schema's marker, read by `skills/tp-plan-audit/scripts/audit_oracle.py`'s `plan_schema`):

```markdown
---
weight-class: <class>
plan-schema: 2
---

# <Design Name> — Implementation Plan

## Phase 1: <Phase Name> (~Nk)

### Task 1.1: <Task Title>
**File**: `<path/to/file>` (new), `<path/to/other_file>` (modify)
**Test**: <prose: what the test proves; documentation only, never parsed>
**Targets**: `<path/to/test_file.py>::<test_name>`, `<path/to/new_test.py>` (new)
**Oracle**: example
**Entry point**: `<path/to/target.py>::<symbol>`
**Red**: Write test that <describes what the test asserts>.
**Green**: Implement <describes minimal implementation>.
**Refactor**: <optional — what to clean up, or "None expected">.
**Done when**: <concrete exit criteria — test passes, type checks, etc.>

### Task 1.2: <Task Title>
...

## Phase 2: <Phase Name> (~Nk)
...
```

**Targets field — the task's machine-read oracle.** `**Targets**` is the only field tooling runs (the `--local` eligibility table, `task_verify`, the Tier 3.5 re-run); the **Test** line is prose for humans. The grammar is strict, one parser (`skills/_shared/task_targets.py`), and `/tp-plan-audit` validates it:
- a comma-separated list of backticked pytest targets: `path` (the whole file) or `path::name[::name]` (a node, e.g. `pkg/test_a.py::TestB::test_c`);
- `path` is repo-relative and POSIX (no leading `/`, no `.`/`..` segment) and ends in `.py`; each `name` is a Python identifier (no parametrize ids, no globs);
- append ` (new)` after the closing backtick when this task creates the file; every item of that file carries it, or none does;
- write `none` when the task has no runnable test (a docs-only or shell-verified task): it then starts on Strata and lands only if an Opus diff review accepts it (`accepted-by-review`), reported unverified;
- order never matters, a whole-file item covers that file's nodes, and a duplicate item is an error.

A malformed field is an audit ERROR. A missing field is only a NOTE, but the task is then non-canonical: not runnable, starts on Strata (`local-xhigh`) and lands only if an Opus diff review accepts it, unverified in the re-run.

**Oracle and Entry point fields — the task's test grammars.** `**Oracle**` names the test's oracle style(s) and `**Entry point**` names what the tests reach, both parsed by the one grammar module `skills/_shared/task_oracle.py`:
- `**Oracle**`: `none` or a comma-separated list from `task_oracle.ORACLE_TYPES` (`example`, `property`, `metamorphic`, `schema`, `round-trip`, `differential`); a `property` or `metamorphic` type requires a paired `example`; `none` is valid only when Targets is also `none`.
- `**Entry point**`: `none` or a comma-separated list of backticked items, each a repo-relative path (any extension) with an optional `::qualname`, e.g. `` `skills/_shared/<module>.py::check` ``; `none` is valid only when Targets is also `none`.
- On a `plan-schema: 2` plan, a missing or malformed Oracle or Entry point is an audit ERROR (`/tp-plan-audit`); on a plan without the marker the same gaps are NOTEs only.
- A test task names **spec-derived examples** — the concrete `example` inputs come from the design or detailed-design text, never invented at test-writing time, and never derived from reading the implementation. See `skills/_shared/test-fragility.md` for the fragile-test forms to avoid (open-ended checks, change-detectors, blocklists) and the ordered fixes.

**File field — also parsed.** `**File**` is validated by `skills/tp-plan-audit/scripts/plan_files.py`: a comma-separated list of backticked repo-relative paths (any extension; dotfiles like `.python-version` or `Makefile` are legal, no `::` or leading `/`), each with an optional per-item `(new)` or `(modify)` marker — no marker means "touches". Write `none` when the task changes no files. Non-canonical text gets one NOTE and a lenient parse, never a failure.

**Optional task fields** (omit each when it does not apply):
- `**Kind**: clerical` — a mechanical task (a rename, a registry row, a doc pointer). Under `--local` it starts on the cheaper `*-medium` rung (`ladder_rungs.task_start`).
- `**Split**: <path> | none — <reason>` — for a task whose largest **File** would reach its file-size hard cap: the new file the addition splits into, or `none — <reason>` to opt out. `/tp-plan-audit` (`plan_couplings.py`) flags a task that needs one and has neither.
- `**Growth**: +N` — the lines the task adds to its largest **File** (default `+50`); `+0` or less on a grandfathered file opts out of the split check.

**Task sizing.** These limits target local-model workers; every number lives only in `skills/tp-plan-audit/scripts/sizing_limits.py` — the single source of truth, so this block quotes none — and `/tp-plan-audit` reports each as an advisory WARN.
- **Cap headroom**: the largest **File**'s current lines plus its **Growth** stay under its soft cap minus `SOFT_HEADROOM`; otherwise name a `**Split**` module, add a preceding refactor task, or write `**Split**: none — <reason>` — never "fit it in N lines".
- **One concern**: `MAX_ENTRY_POINTS` entry point at most, and at most `MAX_RED_CLAUSES` Red clauses.
- **Production growth**: **Growth** at most `MAX_GROWTH` lines.
- **Files/Targets closure**: an existing test that imports a modified **File** goes in **Targets**, or is named "must stay green, untouched".
- **Read set**: the files the task reads stay within `MAX_READ_TOKENS`.
- **Environment**: a Red needing a real pytest, a tmp git repo, a worktree or a subprocess names your repo's test helper (list it in `plan_audit.test_helpers`), else add a preceding fixture task; in the framework repo the defaults are `sizing_limits.TEST_HELPERS`, such as `inner_pytest`.
- **Carried inputs**: a task names its exact file and anchor, quotes the current text, and carries the target text or a tight rule; a condense/move task's input arrives pre-sliced to the section it changes.
- **One Targets run**: **Targets** is one node list run once at green, and a fully specified edit may carry `**Kind**: clerical` so it starts on `local-medium`.

**Per-phase budget annotation.** Each phase header carries a `(~Nk)` token-budget annotation — a rough estimate of the tokens implementing that phase will cost. Keep each phase **under the per-phase cap of 200k**: when `/tp-run-full-design` drives the plan it dispatches every plan phase under a single `phase-implement` slot, whose **200k soft budget** comes from that orchestrator's static **budget table** (`skills/tp-run-full-design/SKILL.md` → ## Per-slot budget table). Reference that table value as the authoritative source rather than re-deriving the number here — if the slot budget changes, this annotation target tracks it. A phase whose estimate exceeds 200k should be split into smaller phases so each fits one dispatch. The annotation is a sizing hint (for the human reviewer and for the orchestrator's pre-split decision), not a hard gate this skill enforces.

7. **Confirm the plan with the user**. Walk through it briefly. Adjust if they want to reorder, split, or drop tasks.
8. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `three-pillars-docs/tp-designs/{design-name}/plan.md`
   - `three-pillars-docs/tp-designs/{design-name}/lock.json` (rolled into the same commit)
   Commit message: `Plan: {design-name}`.
9. **Tell the user** the next step is `/tp-phase-implement {design-name}`.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design.
- Every task MUST have a test. No "write boilerplate" or "create empty file" tasks.
- Every task carries a **Targets** line (`none` if nothing is runnable) naming exactly the tests its Red writes.
- **Cap per-file test size at planning time** (caps: `skills/_shared/file-size-caps.md`): a task whose test additions would push a test file past the soft-warn names a split — tests distributed across files by unit/scenario. The plan emits split files, never monoliths.
- Tasks within a phase can run in parallel (no interdependencies). Tasks across phases are sequential.
- Keep task count realistic — a phase of 3-7 tasks is healthy. More than 10 suggests the phase should split.
- Each phase header carries a `(~Nk)` budget annotation and should stay under the **200k** per-phase cap — the `phase-implement` slot budget from tp-run-full-design's static budget table. Split any phase whose estimate exceeds it.
- The plan is the contract for `/tp-phase-implement`. Be precise enough that an agent can execute each task without ambiguity.
- Check for existing `plan.md` and ask before overwriting.
- Don't start implementing — stop after writing the plan.

## Auto Mode

This skill is a **Shape B (Generator)** per `skills/_shared/auto-mode.md`. In `--auto` it derives the task breakdown from `detailed-design.md` without prompting the user.

Differences from interactive mode:
- **Skip step 7** (the user-confirmation walk-through). Self-review the plan against `detailed-design.md`: every Implementation Order item should map to at least one task; phases should match (or merge/split) the design's implementation order; each task should remain implementable in a single red-green-refactor cycle. No external approval.
- **Overwrite an existing `plan.md` without asking** (the rule above defers to `--auto`; under `--patch`, edit it instead: ## Patch mode). Prior content is replaced; git history is the rollback path.
- **Lock conflict ⇒ BLOCKED**, never `--force-takeover` prompt. Follow Rule 5 in `auto-mode.md`: append a BLOCKED entry to `decisions.md` and exit non-zero. The orchestrator escalates.

Log derivation choices to `three-pillars-docs/tp-designs/{design-name}/decisions.md` using the canonical init/append snippet in `skills/_shared/auto-mode.md` (Initialization + append section). One Decision Entry per non-trivial choice, prefixed `[tp-plan]`:

- **Which Implementation Order items map to which phases/tasks** — note the mapping when it's anything other than 1:1.
- **Any merges or splits** — when two design items collapse into one task, or one design item expands into several tasks, log both the choice and the rationale.
- **Confidence**: High when the design's Implementation Order section is explicit and the mapping is mechanical; Medium when a judgment call (e.g., grouping two related items into one phase) is required; Low when the design under-specifies and you had to invent structure (flag for human review).

**In `--auto`, the plan is committed without user confirmation; `decisions.md` is the audit trail and the rollback signal — every derivation choice must be logged before the commit step.**

## Patch mode

`--patch <findings.json>` is the audit-retry path: after a plan-audit `needs-work`,
`/tp-run-full-design` re-dispatches this skill (as `tp-generator`, with `--auto`) and this flag.
`<findings.json>` is the clipped audit `findings[]` (`.handoffs/<slot>-findings-<n>.json`).

- **Edit, never Write.** Fix each finding in the existing `plan.md` with one or more Edit calls
  scoped to the task or phase it names. Never rewrite the file with Write and never regenerate it
  from `detailed-design.md`; untouched tasks stay byte-identical.
- **One Decision Entry per finding**, appended to `decisions.md`:
  `[tp-plan] patch finding <k> → <section>` (`<k>` = the finding's index in the file), saying
  what changed, or why nothing needed to.
- **No artifact → BLOCKED.** With no `plan.md`, `--patch` refuses: append a BLOCKED entry and exit
  non-zero. It never falls back to regeneration.
- Steps 3-5 are skipped (the artifact and the findings are the input); step 8 commits `plan.md`
  and `decisions.md`.
