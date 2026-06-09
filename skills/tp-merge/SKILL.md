---
name: tp-merge
description: "Land a reviewed PR at the irreversible boundary: enforce the deterministic merge gate (require_merge_gate_pass — five predicates incl. a current human approval) and run the irreversible gh pr merge ONLY on PASS. Refuse on a blocked gate, printing the blocking predicate(s) and how to authorize. The base-into-branch base-sync operation is the separate /tp-merge-from-main skill."
argument-hint: "{pr-url|design-name}"
---

# tp-merge — the land gate (irreversible `gh pr merge`)

`/tp-merge` is the **land** skill: it crosses the one irreversible boundary in the
framework — running `gh pr merge` to land a reviewed PR onto its base. It is the sole
code site where the "the framework never crosses the irreversible boundary without an
explicit, current human approval" guarantee is enforced in code.

It does **not** sync the base into the branch, resolve living-doc conflicts, or rewrite
tracked files — that reversible base-into-branch operation is the separate
`/tp-merge-from-main` skill. `/tp-merge` only gates and lands.

> **Two distinct skills, one former name.** Before the human-approval-merge-gate design
> (D7), `/tp-merge` was the base-sync conflict resolver. That half is now
> `/tp-merge-from-main`. The `/tp-merge` name is retained for this **land** half, because
> operator and orchestrator references to "`/tp-merge`" mean *land/merge*. Keep them
> distinct: `/tp-merge-from-main` syncs the base in (reversible, below the gate);
> `/tp-merge` lands the PR out (irreversible, behind the gate).

## Arguments

- `{pr-url|design-name}` (required) — the PR to land. A PR URL is used directly; a design
  name resolves to its open completion PR.

## Prerequisites

- `gh` CLI installed and authenticated (the merge runs `gh pr merge`).
- The PR has been reviewed and is reviewed-stable (the autonomous loop pauses here — this
  step is the human's).

## The gate (load-bearing)

The land is gated by `require_merge_gate_pass(pr_url)` from
`skills/tp-merge-from-main/scripts/merge_gate.py` — the **fail-closed enforcing** form of
the deterministic merge gate. It evaluates the gate's predicates over the PR head SHA and
**raises `MergeGateBlocked` on any non-PASS verdict**, so a caller that ignores the return
value still cannot proceed. The gate now carries **five** head-SHA-keyed predicates:

- **threads_resolved** — all review threads resolved.
- **mergeable** — PR is in MERGEABLE state.
- **checks_success** — all required CI checks settled and concluded SUCCESS.
- **copilot_on_head** — Copilot has reviewed the current head SHA.
- **human_approved** — a **current human approval** (`tp:human-approved`, applied by a
  human out-of-band, on the head SHA) is present. Absent / stale (predates the head) /
  automation-applied → INDETERMINATE. This is the predicate the autonomous path can never
  satisfy: it never applies the label out-of-band, the push-time auto-strip clears a stale
  one, and the gate re-derives currency from the timeline-event-vs-head-commit time.

The emitted label is always *"mechanical predicates hold — semantics UNVERIFIED — your
review is the only semantic check"* — shown even on PASS. The gate never asserts the PR is
ready-to-merge-without-caveats; the operator's review is the only semantic check.

## Steps

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

1. **Resolve the PR.** If a PR URL was passed, use it. If a design name was passed,
   resolve it to the design's open completion PR (`gh pr view`). Validate `{design-name}`
   per `skills/_shared/validate-name.md` when a name (not a URL) is passed.

2. **Gate, then land.** Run the land driver:
   ```bash
   python3 skills/tp-merge/scripts/land.py <pr_url>
   ```
   The driver calls `require_merge_gate_pass(pr_url)`:
   - **On PASS** — it runs `gh pr merge <pr_url> --merge` exactly once and exits **0**.
   - **On `MergeGateBlocked`** (any non-PASS verdict) — it **REFUSES**: it does **NOT**
     run `gh pr merge`, prints the blocking predicate(s), and exits **2**.

3. **On refusal, remediate and re-run.** The refusal prints which predicate(s) blocked.
   When `human_approved` is the blocker, follow `skills/_shared/human-approval-howto.md`:
   a human applies `tp:human-approved` on the **current head** out-of-band, then re-run
   `/tp-merge`. (Re-pushing a new commit auto-strips the label — re-approve the new head.)
   When the blocker is a base-moved conflict (`mergeable`), run `/tp-merge-from-main` to
   sync the base in first, then re-run `/tp-merge`.

## Rules

- **Refuse on a blocked gate — never cross the irreversible boundary without PASS.**
  `gh pr merge` is reached ONLY after `require_merge_gate_pass` returns; a `MergeGateBlocked`
  exit is **2** with the blockers printed and `gh pr merge` NOT invoked. This is the code
  enforcement of the human-approval guarantee; it is not advisory.
- **Human approval is the human's, applied out-of-band.** The framework never applies
  `tp:human-approved` for itself (the autonomous path cannot satisfy `human_approved`).
  See `skills/_shared/human-approval-howto.md`.
- **`/tp-merge` does not sync or rewrite files.** Base-sync / living-doc conflict
  resolution is `/tp-merge-from-main`. This skill only gates and lands.
- **Honest GitHub-UI bypass note**: a merge clicked in the GitHub UI outside the tooling
  **bypasses** this gate. The branch-protection required-check backstop is deferred to the
  `self-hosted-ci-runner` design. Until that ships, the tooling-path land gate is the only
  enforcement — land via `/tp-merge`, not the GitHub UI, on guarded branches. The gate's
  on-head currency re-check still treats a stale/absent approval as unauthorized regardless
  of how the head advanced, so the approve-then-push bypass is closed even on a UI push.
- **Never bypass hooks**: if a `git`/`gh` step is blocked, surface the output and stop —
  do not retry with `--no-verify`.
