# Weight Class — the design depth axis

Every design carries a **weight class** declaring how much ceremony its
pipeline runs: `just-do-it`, `light`, `spike`, or `full`. The class is a
**floor, not a ceiling** — every ambiguity resolves toward more checking.
The executable companion is `skills/_shared/weight_class.py` (`recommend`,
`read`, `check`).

## The four classes

- `just-do-it` — trivial, reversible, well-understood change. A ~10-line
  mini design.md on a normal `tp/{slug}` branch; implement; `/code-review`.
  No council, no plan.md.
- `light` — small but real production work. One `/tp-design` sitting
  produces a **collapsed design.md** (design + detail merged, ~60 lines)
  **and a thin plan.md**; `/tp-design-detail` and `/tp-plan` are skipped.
  Audit is `/tp-plan-audit {name} --light` (script layer + one merged
  council pass). Impl check is `/code-review` + the fidelity checklist.
- `spike` — the approach itself is unknown. Routes to the existing spike
  pipeline, which *is* its ceremony profile; the frontmatter just records
  the choice on the shared axis.
- `full` — the default and the fail-safe. The complete TDD pipeline,
  unchanged: design → detail → design-audit → plan → plan-audit →
  phase-implement → phase-review → implementation-audit.

## Ceremony by check level

| Check level | `just-do-it` | `light` | `spike` | `full` |
|---|---|---|---|---|
| design-level | mini design.md (~10 lines) | collapsed design.md — **all floor-required `##` sections** (must still pass `validate_design_floor.py`) | spike design.md (hypothesis + success criteria) | design.md + detailed-design.md + `/tp-design-audit` |
| plan-level | none | thin plan.md (1 phase) + `--light` merged audit (single round, Round-2 short-circuit rule) | spike plan.md + `/tp-plan-audit --spike` | plan.md + `/tp-plan-audit` (script + full council) |
| impl-level | `/code-review` | `/code-review` + fidelity checklist (see below) | `/tp-spike-implement` + spike-results.md | `/tp-phase-implement` + `/tp-phase-review` + `/tp-implementation-audit` |
| completion-level | PR via `/tp-design-complete` | PR with the fidelity checklist injected into the body | `/tp-spike-results` + `/tp-spike-learn` | `/tp-design-complete` + PR |

## Selection rubric

Score four axes, each `low | medium | high` (**reversibility is inverted:
high reversibility — easy to undo — is good**):

- **risk** — what breaks if this is wrong?
- **blast radius** — how much of the system does it touch?
- **reversibility** — how cheaply can it be backed out?
- **novelty** — is the approach known, or are we guessing?

Mapping (`weight_class.py recommend --risk … --blast-radius …
--reversibility … --novelty …`): all four minimal → `just-do-it`; novelty
high → `spike`; at most one axis medium, none high → `light`; otherwise →
`full`. **Ties and unknown axis values resolve heavier.** The justification
names the deciding axis. The rubric output is a recommendation — the human
confirms or overrides at declaration time.

## Frontmatter schema

The class lives in a flat YAML-ish frontmatter block, the first thing in
the file:

```markdown
---
weight-class: light
---
# my-design — Design
```

- **design.md is authoritative** — consumers read the class from it via
  `weight_class.py read {design_dir}`.
- seed.md carries the scope-time declaration; generators stamp every
  artifact they write (detailed-design.md, plan.md) from design.md's value.
- Absent, malformed, or unknown values read as `("full", "default")` —
  fail-safe toward more checking.
- `weight_class.py check {design_dir}` reports divergent or missing stamps
  on siblings (exit 1). The check gates on design.md's class coming from
  frontmatter, so legacy frontmatter-free dirs pass vacuously.

## Escalation rule

Consumers may **escalate** a design's ceremony above its declared class,
never **de-escalate** below it. Escalation is always allowed and logged
(decisions.md in autonomous runs); a request to run lighter than the
declared class is refused. Autonomous consumption (`tp-run-full-design`):
`just-do-it` escalates to `light` (an unattended run warrants the audit
floor); `spike` is **refused** with BLOCKED guidance to run
`/tp-spike-auto` interactively — its Phase 1 is interactive by design.

## Light fidelity checklist

The light class's impl-level instrument: one `/code-review` pass whose
context includes the collapsed design note **plus this checklist**. It is
phrased for direct inclusion in a code-review prompt or PR body — paste it
verbatim (`/tp-design-complete` injects it into the PR body for `light`
and `just-do-it` designs):

> **Fidelity checklist (light weight class)**
> - [ ] Every in-scope item of the collapsed design note is traced to the
>   diff — name the file/hunk that implements each one.
> - [ ] Nothing in the diff falls outside the note's declared scope; any
>   untraceable change is **drift** — flag it explicitly, don't absorb it.
> - [ ] The thin plan.md's tasks are all accounted for (done, or their
>   absence explained).
> - [ ] Out-of-scope items from the note remain untouched by the diff.
> - [ ] Any drift that survives review is recorded (PR body or
>   known_issues.md), not silently merged.

The checklist is the light class's answer to the full pipeline's
implementation-audit: cheaper, but the in-scope-item-to-diff trace is
non-negotiable.

## Hot-patch lane cross-note

The hot-patch lane sits **below** `just-do-it` and **outside** the four-class set.
The classes above are chosen at scope-time (design → detail → plan); hot-patches
have no scope-time — the patch IS the scope.

Use the hot-patch lane when: an urgent narrow fix cannot wait for a full branch +
design cycle AND it meets eligibility (trailer self-declaration + hard exclusions +
≤150-line diff cap). See `commit-after-work.md` §Hot-patch lane for the full lane
contract, trailer grammar, ledger obligation, and what invariant #37 enforces.

## Composition contract: (weight-class × slice)

The weight class is one of two orthogonal pipeline axes. **Class sets
ceremony depth per check level** (this doc); **slice sets which tiers of
the pipeline run** (the `orchestrator-pipeline-modes` design — seeded, not
yet built — implements the slice axis). The contract for composing them:

1. A slice selects *which* check levels execute; the class selects *how
   deep* each executing level goes.
2. **A slice may never drop a check level below the class floor** — if the
   class mandates a merged audit at plan-level, no slice may skip it while
   claiming the class is honored.
3. Where the two conflict, the heavier interpretation wins (the same
   resolve-heavier rule as the rubric).

This section is interface-only: `orchestrator-pipeline-modes` implements
the slice half against this contract.
