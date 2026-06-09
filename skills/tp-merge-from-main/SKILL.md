---
name: tp-merge-from-main
description: "Sync a base branch INTO a design's worktree (base-sync) and auto-resolve the safe living-doc conflict classes behind a zero-drop verifier, deferring everything semantic to the human. Re-runs tests, re-pushes only when green, updates the PR. This is the reversible base-into-branch operation — landing the PR is the separate /tp-merge land gate."
argument-hint: "{design-name} [--base <branch>] [--dry-run] [--no-push] [--force-takeover]"
---

# tp-merge-from-main — worktree-aware base-sync + living-doc conflict resolution

When parallel designs run in their own worktrees, the base branch moves under them and a
merge conflict on the shared living docs (`known_issues.md`, `product_roadmap.md`,
`architecture.md`, `vision.md`) is the *expected* case at `/tp-design-complete` time. Manual
resolution is slow and — as the parent spike proved on real PR-#28 history — a silent
**content-drop** risk: a careful human merge dropped a known-issue entry outright.

`/tp-merge-from-main` merges the base into the design's worktree branch and auto-resolves only the
**provably-mechanical** living-doc conflict classes behind an independent zero-drop verifier.
Everything semantic is left as conflict markers for the human. It is the conflict-handling
step the merge-back flow never had; it composes with `/tp-pr-iterate` for the post-merge
re-review loop.

> **Base-sync, not land.** `/tp-merge-from-main` is the *reversible* base-into-branch
> operation (it merges `{base}` into the design branch and re-pushes the branch). It is
> **not** the irreversible `gh pr merge` that lands the PR to `{default}` — that is the
> separate `/tp-merge` land skill, which enforces the deterministic merge gate (including
> the human-approval predicate) before crossing the boundary. Keep them distinct: this
> skill syncs the base in; `/tp-merge` lands the PR out.

**The boundary** (from the `worktree-merge-conflict-flow` spike, verdict GO):
- **AUTO-SAFE** (auto-resolved + verified): `design-inventory-row-merge`, `id-renumber-collision`.
- **ALWAYS-HUMAN** (deferred): `preamble`/`Last updated`, `current-focus-reprioritization`, `generic-prose`.
- **GATED** (treated as human until a fixture exists): `append-only-log`.

## Arguments

- `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/` and an active `tp/{design-name}` worktree branch.
- `--base <branch>` (optional, default `master`) — the base branch to merge in (uses `origin/<branch>`).
- `--dry-run` (optional) — run the merge + resolution, print the report, then `git merge --abort`. Changes nothing, pushes nothing.
- `--no-push` (optional) — resolve and re-run tests, but stop before pushing (human pushes).
- `--force-takeover` (optional) — claim the design lock per `skills/_shared/collaboration.md`.

## Prerequisites

- `gh` CLI installed and authenticated (PR update + re-review).
- The project test command must run from the repo root.
- You are inside the design's worktree (the merge happens here, never in a sibling worktree).

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

0a. **Run cwd preflight** per `skills/_shared/cwd-preflight.md`: `python3 skills/_shared/cwd_preflight.py {design-name}`. Exit 3 → stop and show the `cd` fix. Exit 0 → continue.

1. **Validate `{design-name}`** per `skills/_shared/validate-name.md` (must match `[a-z0-9-]+`; reject `/`, `..`, spaces). Then run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "implement"` (the merge-back rewrites tracked files like an implementation step; `phase` is constrained to the schema's fixed set, which has no `merge` value). `/tp-merge-from-main` rewrites tracked files and pushes, so the lock must be held by the rightful owner. Honor `--force-takeover` if passed.

2. **Fetch the base**: `git fetch origin <base>` (default `master`). The base ref being fetched here is synced from the **seat** — the base checkout / worktree host that hosts the design worktrees. If you are unsure which checkout is the seat, run `seat_resolve.sh --where` from the repo root; this skill already runs inside the design's own worktree, so the seat is the sibling base checkout. See `skills/_shared/topology.md` for the canonical seat and worktree layout definitions.

3. **Run the merge driver** from the repo root of the design worktree:
   ```bash
   python3 skills/tp-merge-from-main/scripts/merge_driver.py "$(git rev-parse --show-toplevel)" "origin/<base>"
   ```
   (If the skill is installed at `~/.claude/skills/`, use that path.) The driver:
   - runs `git merge --no-commit --no-ff origin/<base>` inside the worktree;
   - for each conflicted **living-doc** file, reconstructs `(base, ours, theirs)` from the index stages, then runs `classify → resolve → verify` **per hunk**;
   - applies the staging policy and prints a JSON report with three per-file outcomes:
     - **auto-resolved** — every hunk mechanical, verifier zero-drop, no markers → written + `git add`ed.
     - **partially-resolved** — mechanical hunks pre-resolved in place, semantic hunks left as markers (file *not* staged). This is the common case: every real living-doc conflict also conflicts on the `*Last updated:*` preamble, which is semantic.
     - **deferred** — all-semantic, a verifier-flagged drop, an add/delete conflict, or any non-living-doc (code) conflict → left untouched.
   - exit `0` = fully resolved/clean; exit `2` = human attention needed.

4. **Surface what the human must finish.** From the report's `partially_resolved` + `deferred` lists, tell the user exactly which files still carry conflict markers and which semantic classes remain (e.g. "`product_roadmap.md`: preamble + current-focus need you"). **Never stage or commit a file that still contains conflict markers** — the driver enforces this; do not work around it. Wait for the human to finish the deferred hunks before continuing (in `--dry-run`, stop here and `git merge --abort`).

5. **Re-run the project test suite** in the worktree once all conflicts are resolved (auto + human). If tests fail, stop and surface the failure — do not push.

6. **Commit the merge** once the tree is conflict-free and green: `git commit --no-edit` (preserves the merge message). With `--dry-run` or `--no-push`, stop before this.

6.5. **Closeout check (warn, never block)**: before pushing, run `python3 skills/_shared/detect_unarchived.py --repo . --slugs-only` and check whether `{design-name}` appears — i.e., its `three-pillars-docs/tp-designs/{design-name}/` dir carries implementation evidence (`implementation-audit.md` / `spike-results.md`) but has **not** been archived to `completed-tp-designs/`. If it does, **warn** (do not block): the design has shipped but is not closed out — run `/tp-design-learn {design-name}` (or `/tp-spike-learn`) **then** `/tp-design-complete {design-name}` before the human merges, or `framework-check` invariant **#27** will hard-fail once the dir lands on `{default}` unarchived (known-issue M10). `/tp-merge-from-main` is a conflict resolver, **not** a closeout gate — it surfaces the gap and proceeds; the #27 invariant is the hard backstop, this is only the soft in-context nudge. **Fail-open**: a detector error is ignored (the helper always exits 0).

6.6. **Readiness advisory (warn-never-block)**: call `merge_gate.merge_readiness_warning(pr_url)` (from `skills/tp-merge-from-main/scripts/merge_gate.py`). If the return value is non-None, **print it as a WARNING** and **proceed** — never block. This mirrors the step-6.5 `detect_unarchived` warn-never-block contract: `/tp-merge-from-main` is a conflict resolver, not a readiness gate. The warning names the failing readiness sub-state from `classify_readiness` (`copilot-errored`, `review-stale`, `awaiting-copilot`, `unreviewed`) so the human can decide whether to remediate before merging. **Fail-open**: a detector error (fail to fetch, network issue) returns `None` and is silently ignored — a failing readiness check must never nag or block.

6.7. **Mandatory blocking pre-merge gate (fail-closed)**: before pushing the merge, run the deterministic gate. The operator runs:
   ```bash
   python3 skills/tp-merge-from-main/scripts/gate_cli.py <pr_url>
   ```
   or equivalently calls `merge_gate.merge_gate_blocking(pr_url)` from `skills/tp-merge-from-main/scripts/merge_gate.py`. **Exit 0 (PASS) is required before proceeding**; any non-zero exit (1 = FAIL, 2 = INDETERMINATE) means merge is refused. The gate output always shows the label `mechanical predicates hold — semantics UNVERIFIED — your review is the only semantic check`. The label is shown even on PASS — the gate never asserts the branch is ready-to-merge without caveats.

   Predicates checked:
   - **threads_resolved**: all review threads resolved (fail-closed: fetch failure → INDETERMINATE, not PASS)
   - **mergeable**: PR is in MERGEABLE state (CONFLICTING → FAIL; UNKNOWN → INDETERMINATE)
   - **checks_success**: all CI checks settled and concluded SUCCESS (empty rollup → INDETERMINATE, not PASS; INFRA_BLOCK → INDETERMINATE)
   - **copilot_on_head**: Copilot has reviewed the current head SHA (not reviewed → INDETERMINATE, not PASS)
   - **human_approved**: a current human approval (`tp:human-approved`, applied by a human out-of-band, on the head SHA) is present — enforced transparently via `evaluate_gate`'s `pred_human_approved` (no code edit here: `evaluate_gate` carries the fifth predicate when `review.require_human_approval` is true, the strict default). Absent/stale/automation-applied approval → INDETERMINATE (never FAIL). See `skills/_shared/human-approval-howto.md` for how to authorize. The irreversible `gh pr merge` land step lives in the separate `/tp-merge` skill, which enforces the same gate at the boundary.

   This step is **DISTINCT** from the advisory step 6.6 (`merge_readiness_warning`, warn-never-block). That step proceeds regardless. This step 6.7 **refuses** on non-zero exit.

   **Honest GitHub-UI bypass note**: A merge performed via the GitHub UI (clicking "Merge pull request") outside the tooling **bypasses** this gate. The branch-protection backstop (requiring a CI status check from `gate_cli.py` in a required workflow) is deferred to the `self-hosted-ci-runner` design (council verdict #6: branch-protection setup is deferred). Until that ships, the tooling-path gate is the only enforcement; operators should use `/tp-merge-from-main` to sync and the `/tp-merge` land skill to land the PR (not the GitHub UI) for merge operations on guarded branches.


7. **Push only when green**, then **update the PR**: push the branch, refresh the PR body with a short merge note (base SHA merged, which classes auto-resolved, which the human finished), and **re-request review** so branch protection re-triggers — compose with `/tp-pr-iterate` / `pr-fix-targeting-and-auto-review` for the Copilot loop. Pushing happens only here, at the irreversible boundary, and only on a green suite.

   **Auto-strip stale approval after the push lands (D2, fail-open).** A push that advances the PR head invalidates any prior `tp:human-approved` label (it was approving the OLD head). Immediately AFTER the push lands, call the strip hook with the new head OID:
   ```bash
   python3 - <<'PY'
   import sys; sys.path.insert(0, "skills/tp-merge-from-main/scripts")
   import auto_strip_hook
   auto_strip_hook.run("<pr_url>", "<new_head_oid>")  # new_head_oid = git rev-parse HEAD after push
   PY
   ```
   `auto_strip_hook.run(pr_url, new_head_oid)` (from `skills/tp-merge-from-main/scripts/auto_strip_hook.py`) calls `strip_stale_approval`, which REST-DELETEs `tp:human-approved` when the present label is not current on the new head — keeping the GitHub UI honest about what is authorized. It is **FAIL-OPEN**: any error is swallowed and returns False, so a strip failure can NEVER block the push. This is convenience only; the gate-time currency re-check in step 6.7 / the `/tp-merge` land gate is the always-on fail-closed backstop, so a missed strip never defeats correctness — the stale label is simply treated as absent at gate time.

8. **Post-merge auto-chain** (fires only when the design's completion PR has actually landed on `{base}`): after the step-7 push, check whether the archive is now present on `{base}` — guard: run `python3 skills/tp-post-merge/scripts/verify_merged.py --repo . --design {design-name} --base {base} --json`; `merged == true` confirms the completion PR was merged to base. **`/tp-merge-from-main` itself does not land the completion PR** — it merges `{base}` *into* the design branch and updates the PR; the human (via the `/tp-merge` land skill, or a later `gh pr merge`) lands it. So in the ordinary base-sync invocation this guard is **false** and the step silently skips (see the last bullet). Only when `verify_merged.py` reports `merged == true` does this chain `/tp-post-merge {design-name}`.

   - **Fail-open**: a teardown error from `/tp-post-merge` **never** undoes the merge. If `/tp-post-merge` fails, log the error and report it to the user — do not roll back anything. The merge already landed; cleanup can be retried manually with `/tp-post-merge {design-name}`.
   - **Skip under `--dry-run` or `--no-push`**: if either flag was passed, skip the auto-chain entirely (the merge did not actually happen or was not pushed).
   - **Additive and silent on non-completion merges**: if `verify_merged.py` reports `merged == false` (offline, unfetched refs, or this was just a base-sync merge, not a completion-PR merge), skip this step silently with no error.

## Rules

- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — `/tp-merge-from-main` rewrites tracked files and pushes.
- **Zero content drops is the hard gate.** The verifier is the backstop for *mechanical* drops; it is **necessary but not sufficient** (a semantic mis-merge can survive it), so semantic safety is carried by **deferral**, never by the verifier. Auto-resolution fires only when **mechanical-class ∧ classifier-confident ∧ verifier-passes**.
- **Merge, not rebase.** Rebase force-pushes the branch and strands parallel worktree agents that forked from the old HEAD. `/tp-merge-from-main` always merges.
- **Never disturb sibling worktrees.** The merge runs inside the design's own worktree.
- **Never auto-resolve code or prose.** Only the structured living-doc classes are touched; everything else is surfaced untouched.
- **Optimize for zero-drop over reproducing past hand-merges** — the ground-truth human merge can itself be lossy (the spike's L4 case); a union+renumber that *diverges* from a lossy human result by preserving content is the correct answer.
- Use `mktemp` for any scratch files; the driver uses Python `tempfile` internally.
