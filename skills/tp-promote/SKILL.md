---
name: tp-promote
description: Promote a seed (seed.md) to a committed, floor-clearing design.md on the tp/<slug> branch, ready for a design-ready fleet pass. Reads the seed's Open questions, derives a single batched confirm block, collects one operator answer, drafts design.md, validates the floor, and hands off to /tp-run-full-design <slug> --skip-design (Mode B).
argument-hint: "{slug} [--force-takeover]"
---

# /tp-promote \<slug\>

Turn a rich `seed.md` into a committed, floor-clearing `design.md` on the
`tp/<slug>` branch — the cold-start pre-step before a design-ready fleet pass.
Exactly **one human touch**: a single batched confirm block derived from the
seed's `## Open questions`. After the operator answers, this skill drafts
`design.md`, validates the floor, commits, and tells the operator to run
`/tp-run-full-design <slug> --skip-design`.

**No `--auto` mode** — the one batched confirm is the deliberate human gate.

## Arguments

- `{slug}` (required) — kebab-case design name matching `[a-z0-9-]+`, validated
  per `skills/_shared/validate-name.md`. Must match an existing directory under
  `three-pillars-docs/tp-designs/{slug}/` that contains a `seed.md`.
- `--force-takeover` (optional) — claim the lock even when another developer
  holds it. The prior holder is recorded in `previous_owners[]`.

## Steps

1. **Run first-run preflight** per `skills/_shared/first-run.md`.

2. **Validate `<slug>`** per `skills/_shared/validate-name.md`. Reject any
   value containing `/`, `..`, spaces, or characters outside `[a-z0-9-]`.
   After validation, track the design in `.claude/last-design` (MRU update).

3. **Collaboration preflight** per `skills/_shared/collaboration.md`:
   - If on `master`/`main`, offer to create/switch to `tp/<slug>`.
   - Read `three-pillars-docs/tp-designs/<slug>/lock.json`. If `owner` is
     another developer and `--force-takeover` was NOT passed, refuse and
     surface the holder. If `--force-takeover` was passed, record the prior
     owner in `previous_owners[]` and claim the lock. Set `phase: "promote"`.
   - Write `lock.json` back to disk (do NOT commit yet — lock commits with
     `design.md` in Step 8).

4. **Require `seed.md`**: check that
   `three-pillars-docs/tp-designs/<slug>/seed.md` exists and is non-empty.
   If absent, stop:
   > `seed.md` not found for `<slug>`. Author
   > `three-pillars-docs/tp-designs/<slug>/seed.md` (a rich seed with a
   > `## Open questions` section) before promoting.

5. **Derive the batched confirm**: parse `seed.md` for `## Open questions` (and
   any explicit judgment calls in `## Sketch` or `## Problem`). Map each open
   question to one numbered confirm line. Where the seed already states a
   preference or answer, present the drafter's inferred default so the operator
   can accept it wholesale. Produce a single numbered prompt block — the entire
   set of questions at once, not one at a time.

   Example layout (adapt to the actual questions):
   ```
   Batched confirm for <slug>:

   1. [Q from seed — inferred default: X] Accept default, or override:
   2. [Q from seed — no clear default] Your answer:
   ...
   ```

6. **Present the whole block at once and STOP** (one human touch / single
   batched confirm). Wait for the operator's answers before proceeding. Do NOT
   ask individual follow-up questions — collect the full block in one round.

7. **Draft `design.md`** from `seed.md` + operator answers. Populate every
   section that `validate_design_floor.py` marks REQUIRED:
   - `## Problem` — what the design solves (from seed `## Problem` + answers)
   - `## Vision alignment` — how it fits the project vision
   - `## Scope` with `### In scope` (non-empty bullet list)
   - `## Behaviors` — concrete observable behaviors
   - `## Constraints` — hard limits and non-goals
   Optional but recommended: `## Dependencies`, `## Entities`, `## Open Questions`.

   The drafted `design.md` must be substantive enough to pass the floor.
   **Do NOT commit a thin stub** — if you cannot draft a passing design from
   the seed + answers, surface the gaps and ask the operator to flesh them out
   before proceeding.

8. **Validate the floor**: run:
   ```
   python3 skills/_shared/validate_design_floor.py three-pillars-docs/tp-designs/<slug>
   ```
   - **Exit 0 (PASS)**: proceed to commit.
   - **Exit 1 (BLOCKED)**: surface the JSON verdict on stderr, do NOT commit.
     Tell the operator which sections are missing/empty and ask them to fill
     the named sections. Only retry after the operator updates `design.md`.

9. **Log to `decisions.md`** (append, using the `[tp-promote]` prefix per
   `skills/_shared/auto-mode.md` decisions.md format):
   ```markdown
   ### [tp-promote] <slug> — batched confirm + answers

   **Prompt presented:**
   <paste the numbered confirm block from Step 6>

   **Operator answers:**
   <paste the operator's answers verbatim>

   **Floor validation:** PASS (exit 0)
   ```

10. **Commit** on `tp/<slug>` (or the current branch if already on it):
    Stage only:
    - `three-pillars-docs/tp-designs/<slug>/design.md`
    - `three-pillars-docs/tp-designs/<slug>/lock.json`
    - `three-pillars-docs/tp-designs/<slug>/decisions.md`

    Commit message: `Design: <slug> high-level`

    (This message is byte-compatible with what `/tp-design` would produce, so
    downstream tools — `fleet-precheck-designready`'s `design-only` verdict and
    Mode B's design-floor gate — treat a promoted design identically to a
    hand-authored one.)

11. **Hand off**: tell the operator:
    > `design.md` committed. Next step:
    > `/tp-run-full-design <slug> --skip-design`
    >
    > This runs Mode B: skips the design step and begins from `tp-design-detail`.
    > You can also re-stage the slug as `design-ready` in your fleet backlog for
    > a zero-touch run.

## Edge cases

- **Missing `seed.md`** (Step 4): stop with the message above. Do not create a
  placeholder — a thin seed produces a thin design that will fail the floor.

- **Floor not cleared after draft** (Step 8 exit 1): surface the blocked
  sections. Ask the operator to flesh them out rather than commit a stub.
  Retry validation after the operator updates the file. If the floor cannot be
  cleared from the seed + answers, the seed may need enrichment first.

- **Lock held by another** (Step 3): refuse unless `--force-takeover` is
  passed. Record the prior holder in `previous_owners[]`. Never silently steal
  a lock.

- **`design.md` already exists**: warn the operator:
  > `design.md` already exists for `<slug>`. Promote is for the cold-start
  > case. Options:
  > - **Revise**: replace the existing `design.md` by continuing (you will
  >   draft over it).
  > - **Abort**: stop here and use `/tp-run-full-design <slug> --skip-design`
  >   directly if the design is already acceptable.
  Wait for an explicit operator choice before proceeding.

## Rules

- **Validate `<slug>`** per `skills/_shared/validate-name.md` (the `[a-z0-9-]+`
  pattern) — all paths interpolate this value.
- **One human touch**: the single batched confirm (Step 6) is the only
  interactive stop. Do not add follow-up confirmation rounds.
- **No `--auto`**: this skill has no autonomous mode. The human confirm is the
  intentional gate.
- **Floor-validate before committing**: never commit a `design.md` that fails
  `validate_design_floor.py` — surface the verdict and ask the operator to fix.
- **Commit scope**: only `design.md`, `lock.json`, and `decisions.md`. Do not
  stage other files.
- **Commit message**: always `Design: <slug> high-level` (exact form, for
  downstream compatibility).
- **Log every decision** to `decisions.md` per `skills/_shared/auto-mode.md`
  format (even though this is not an `--auto` skill — the decisions.md format
  is the canonical log).
