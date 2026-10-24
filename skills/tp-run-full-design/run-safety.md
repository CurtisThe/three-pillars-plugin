<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Branch hygiene

- Keep the orchestrator in **one worktree on `tp/{slug}` for the entire run**; a drifted HEAD orphans commits.
1. The candidate branch is **remote-only to the orchestrator**: after Tier 3.5 it lives at `origin/candidate/{slug}/single` and the orchestrator **never checks out** that ref in its own worktree — inspect it read-only (`git show`/`diff`/`log`). Only the Tier 5.6 fold writes: `git merge --no-ff` the candidate *into* the checked-out branch keeps HEAD on `tp/{slug}`.
2. **Any slot needing** the candidate's working tree is isolated from `tp/{slug}`. The read-only audit fan-out (Slots 4/6/8) may share `tp/{slug}`; the regression check (Tier 5 Step 1) opens its checkout with `wt_root.py`. The worker (Tier 3) and the cert-fix `tp-worker` take their isolation from `worker_root.py` (`## Classifier no-verdict`). Exception: generator slots and the Tier 7 **round tail**, the one working-tree writer, are the sanctioned `tp/{slug}` writers on the orchestrator's own checkout (never checks out; orchestrator idle).
3. **Assert before every orchestrator commit.** Before any `git commit`, `git symbolic-ref --short HEAD` equals `tp/{slug}`, else `git checkout tp/{slug}` and log `[tp-run-full-design/branch-hygiene] head-reattached {prev-ref}`. Never commit on a drifted HEAD; after a HEAD-moving op run `index_guard.py check`.
- Orphan recovery: restore via a path-scoped `git checkout <sha> -- <path>` (never `git checkout <ref> -- .` mid-merge), re-commit on `tp/{slug}`.

## Classifier no-verdict

- The auto-mode classifier gives **no verdict** (a hard failure: "retrying this action will get the same answer") on a `Write` or `Edit` whose path sits under a `.claude/` directory. A permission allow rule does not help. The one rule: no framework checkout lives under `.claude/`; every checkout opens through `wt_root.py`, and `wt_layout_hook.py` denies the rest.
- The orchestrator opens the worker's worktree with `python3 "$TP_ROOT"/skills/_shared/worker_root.py open --slug {slug} --phase {N} --base-ref {base-ref} --root .` (under `.tp-scratch/`, never `.claude/`); `check` and `open` refuse a `.claude/` write root with `worker-root-refused`, and `agents/tp-worker.md` tells the worker to stay inside it (a prompt rule and a `verify` start check, not a per-call hook). `worker_root.py assert-unmoved` compares the `tp/{slug}` tip before and after each worker (`tier-2-4-build.md` Tier 3), so a stray commit is caught; an uncommitted stray edit is not.
- A worker that still reports a no-verdict is a **stop**: never retry, never a workaround. Log to `decisions.md` the agent type, model, tool, target path (repo-relative or `portable_path` form, never an absolute host path: the file is committed), content size and the exact message with any host path rewritten the same way (no content, no secrets), then run `SKILL.md` §Cleanup step 0 (finalizer first).
- The stop card offers one ruled option: run Slot 7 **inline** in the orchestrator's own worktree (you implement each task, red then green commits), recorded in `decisions.md`. Under `TP_DESIGN_RUN=1` the stop is no card: put it with `ruling_cli.py ask --kind classifier-denial` (`--option 'inline=Run Slot 7 inline'`, recommended, and `--option 'stop-run=Stop the run'`), so it stays the operator's and the seat never rules it, then `ruling_cli.py wait` (`skills/_shared/escalation.md` §Design run). An inline write that itself gets no verdict stops the run.

## Token budget

- `--max-tokens N` is a **whole-run** cap, not per-tier: usage accumulates across tiers, checked only at tier boundaries (Tiers 2/3/3.5/5/6).

### Tier-boundary check

- Telemetry: [`throughput.md`](throughput.md) §Dispatch logging. Before each tier, sum tokens so far; at or over `--max-tokens`, append `[tp-run-full-design/tier-N] token-cap-abort` (N = the tier about to be entered) with **Usage** / **Cap** / **Skipped** / **Confidence**: High, then exit non-zero cleanly: candidate stays on origin, lock released, no PR opens.

### No mid-tier abort

- A tier in flight finishes first — each phase dispatch is the atomic unit. For a harder cap set `--max-tokens` below the unit cost. `--max-wall-clock SECS`: same boundaries, tagged `wall-clock-abort`; caps independent.

## SIGTERM graceful abort

- A mid-run `SIGTERM` aborts on the boundary-only discipline of the token-cap and wall-clock aborts (## Token budget): no mid-tier / mid-slot kill (## No mid-tier abort).
1. Set an abort flag, stop scheduling new dispatches; the in-flight slot finishes at its boundary.
2. Leave durable state — committed artifacts, the pushed candidate branch, the `.handoffs/` worklist (`SKILL.md` ## Handoff protocol — pre-split (M2)) — so `/tp-run-full-design {slug}` cold-resumes.
3. Append `[tp-run-full-design/tier-N] sigterm-abort` to `decisions.md` tagging the pending slot; run `SKILL.md` ## Cleanup — never `git reset --hard`/drop a remote ref.
4. Exit cleanly: interrupted-but-resumable, not a crash.

## Retry & max-attempts

- `--max-attempts N` (default `3`) is the worker retry budget for Tier 3 + 3.5 on a malformed structured response; not Tier 6's `gh pr create`; no audit use (## Retry-with-advice counter). A retry re-dispatches `tp-worker` with `model="opus"` — `[tp-run-full-design/tier-3] phase-dispatch-escalated: opus`.
- Only (c) `SchemaValidationError` is retryable (≤ `--max-attempts`). Escalate at once: (a) no-op (`worktreePath` absent), (b) `NoCandidateBlockError`/`UnknownSchemaVersionError`, (e) sha-mismatch, (f) rerun-failed.
- Per-phase loop; exhaustion → `[tp-run-full-design/tier-3.5] retry-exhausted`, escalate, exit non-zero.

### Distinguishing case (e) from retries under the same tier prefix

- The event-type token after the `[tp-run-full-design/tier-3.5]` prefix disambiguates, stable across versions: only `retry attempt N/M` (case c) is retryable; `retry-exhausted`, `sha-mismatch`, `no-candidate-block`, `worker-noop`, `rerun-failed`, `task-env-error` are not. Informational, never a case: `worktree-cleanup-locked`, `rerun-skipped`, `rerun-phase-unverified`, `rerun-unverified <n>`, `files-escape-logged`.

### Counter-reset rule

- The worker counter resets to 1 per phase dispatch, never shared with the audit counters, Tier 6, or across runs: `--max-attempts 3` is per phase dispatch. Crossing `--max-tokens` mid-loop → the token-cap-abort wins.

## Retry-with-advice (audits)

See [`throughput.md`](throughput.md) §Retry with advice (audits): Slot 4/6 `needs-work` → `tp-generator` patch (`--patch`), then `audit_retry_rules.py recheck` — one patch plus at most one re-check; Slot 8 re-runs the flagged phases (**Map-check exemption:** escalates instead).

## Retry-with-advice counter

- Each audit slot runs its own per-audit-cycle counter, reset to 1 when that slot (`design-audit`, `plan-audit`, `impl-audit`) is first dispatched; never shared across audits, with the worker counter, or across runs.
- Bounded by one patch plus at most one re-check, which supersedes `--max-attempts` for audits (worker-only). Still `needs-work` → escalate (## Retry-with-advice escalation); each attempt appends `[orchestrator/<audit-slot>] retry-with-advice attempt N/M`.

## Retry-with-advice escalation

- The terminal fallback: self-heal first; all confidences are retried — confidence is advice, never a gate.
- Map-check: any `category: "map-check"` finding, any verdict, escalates at once — append `[orchestrator/<audit-slot>] map-check-escalated`, leave lock + branch as-is.
- Budget exhausted — one patch + one re-check spent, still `needs-work`: finalizer first (`SKILL.md` §Cleanup step 0; a second `needs-work` after a `resolved` finalizer follows `skills/_shared/escalation.md` §Run "Second budget stop"), append `[orchestrator/<audit-slot>] retry-exhausted` with the findings, exit per `SKILL.md` ## Cleanup.
- **`certification-unverified`** — a Slot 4/8 `python3 "$CERT" route` of `escalate` (`tree_mutated`, `claimant-records`, `records-handoff`, an unmatched phrase) or a certify.py exit ≠ 0 / incomplete `--out` (a lint exit 2 included) (`tier-5-closeout.md` #### Step 2c). An `unverified` claim still `unverified` after its one retry is a `cert-gap`, never this escalation; `false-red` is a cert-fix, as `not-binding` is. Append `[orchestrator/<audit-slot>] certification-unverified`, add `tp:needs-human-attention` where a PR exists, exit per `SKILL.md` ## Cleanup; **never** re-spawn advice. Order per audit return: map-check → `certification-unverified` → `status`.
- The audit gate stays a true floor: never advance on `needs-work`, never auto-merge, exhaust automated repairs.

## Operator pings

- At any stop the finalizer escalates, and at a classifier block, run `python3 "$TP_ROOT"/skills/_shared/ready_ping.py stop --slug {slug} --summary "<cause>" --decisions three-pillars-docs/tp-designs/{slug}/decisions.md` (the finalizer CLI already does this itself on `escalate`), then `PushNotification` the printed message when the tool is available.
- After a base-sync push of a converged PR, run `python3 "$TP_ROOT"/skills/_shared/ready_ping_rearm.py --pr-url <pr_url> --head <sync head>` (the ping is recorded in the ping ledger), and `PushNotification` the `ready_ping.message` when `ready_ping.status` is `sent`. A skipped ping is recorded as owed; the fleet churn watcher emits `pr-ready` once the PR is MERGEABLE.

## Lock ownership

- Write `owner: "orchestrator:<git-email>"` at lock creation; a mid-run `--force-takeover` aborts at the next lock-refresh.
- `seat_commit_guard` refuses a hand-started run's conflicted merge commit (a clean merge passes); launch with `TP_DESIGN_RUN=1` (the design-run launcher sets it).
