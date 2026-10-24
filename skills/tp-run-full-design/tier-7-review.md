<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Tier 7 — PR-iterate (review loop to reviewed-stable)

- On by default; `--no-iterate` (`--no-review` implies it) skips. Incorporates `/tp-pr-iterate` (fleet emits bare `/tp-run-full-design … --skip-design`).
- Finders run on the cheap engine (`tp-pr-iterate/strata-finders.md`): run its §Context scout first (re-run on `needs-refresh`). Each round also runs `skills/tp-pr-iterate/cheap-tier.md` §Tier 7 in the run's mode; rules skills/tp-pr-iterate/convergence-rules.md; step 1's `round_scratch.py prepare` also passes `--review-weight <W>` and `--rulings <proof_root>/rounds/<pr>/rulings.md`.

### Step 1 — Orchestrator-owned round loop (Slot 11)

- Orchestrator drives run_round at top level (never a Slot 11 subagent); rounds follow `skills/tp-pr-iterate/round-topology.md`:

1. `review_base` is the base-branch tip, re-fetched every round. `round_scratch.py prepare --proof-root <proof_root> ... --review-weight <W> --rulings <proof_root>/rounds/<pr>/rulings.md` → round dir R (manifest = path authority). Fan out `tp-review-confirmer` on the cheap engine (Sonnet in parallel, Strata one at a time), `model=<dispatch_model>`; `opus-check` last, after every finder `reply.md` exists; `reply_path` per manifest.
   - **Round tail.** Opus, no worktree isolation, in the orchestrator's `tp/{slug}` checkout: the one working-tree writer (never checks out). Runs `reproduce.py --round-dir R` (`merge_codereview_angles`); clean (two-stable) → run `python3 "$TP_ROOT"/skills/_shared/scratch_leftovers.py provision --slug {slug}` then `python3 "$TP_ROOT"/skills/_shared/scratch_leftovers.py check --expect --slug {slug}` (`created` → log `[tp-run-full-design/tier-7] scratch-provisioned-late`; exit 1 → no converge, no ping, a stop, finalizer first: `SKILL.md` § Cleanup step 0), then `converge.py --round-dir R`, else `capture_proof` + `proof_post.py` (`github.pr_author_account`).
2. Shell out the round decision: `python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/run_round.py`, JSON on stdin: `state_path`, `head_sha`, `codereview_findings`, `reviewed`, `unresolved_actionable`, `ci_rollup`, `config` (`.three-pillars/config.json`; pass explicitly, else `review.expects_copilot`, `ci.expects_github_checks` default `true`), `review_proof_root` (always pass; missing artifact → `proof_ok=False` → `blocked-no-independent-review`), `review_base`, `pr_url`, `round`, `ordinal`, `class_log_path`, `decisions_path`.
   - The wrapper reads + writes `iterate-state.v1.json`. **Resume is in-worktree, not cross-clone**: no state path in use is tracked and no code path commits it; a genuinely *committed* per-round state is the intended contract, not one any current code performs (`tp-pr-iterate/SKILL.md` §Cold-resume contract).
   - An absent state file is the documented **start condition** (`state_bootstrapped: true`); `state-read-failed` (exit 2) is for content that is not a JSON object, a dangling symlink or a non-regular node — "exists with content" is the wrong test in both directions. A zero-length regular state file counts as absent and is re-seeded.
   - Serial callers only: two bootstraps racing on one `state_path` lose the losing round's state (`transitions`, `last_codereview_*`, `degraded_review_retries` and `iteration`, since the round-budget tick increments it each round); each loop gets its own `state_path`.
3. Inline fix (in the round tail), `action == "fix"`: `fix_round.run_round(…, loop_mode=True, paths=…)`, `paths` from `tree_scope.derive_fix_paths`, push to `tp/{slug}`; `put --slot tail`; `round_scratch.py tail-check`, re-fan-out.
4. Loop until the envelope reports a `terminal` phase:
   - `"two-stable"` / `"two-stable [code-review-only]"` → reviewed-stable (`converge.py` posts the proof digest LAST); with `review.expects_copilot=false` the `/code-review` arm converges, never skip Tier 7.
   - `"blocked-no-independent-review"` → apply `tp:needs-human-attention`.
   - A terminal-null `question` `finalizer_stop` (the review stop) is no terminal: handle it per `skills/tp-pr-iterate/round-topology.md` §Review stop, then continue the loop.
   - `"evidence-complete"` (`convergence-rules.md` §D8) → post `accept_hint` once, flush.
   - Budget: `run_round` calls `round_budget.tick` every round — blocking findings at `iteration >= round_cap` stop as `budget-exhausted` (also growth, test/code ratio, `budget-error`; wall clock → `cap-exhausted`; k-consecutive → `convergence-failure`); a newly fired one's envelope `finalizer_stop` → `python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py prepare --stop <json|file> --ledger L` (`SKILL.md` § Cleanup step 0). Report every `holding` signal; to recover, raise `pdw.guards.round_cap` (or the named limit) in the repo config, uncommitted, and re-run. Outcome `pr-iterate-budget-exhausted`.
   - Terminal explainer (`skills/_shared/explainer.md` §Refresh), pre-flush: `if python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py refresh-needed --slug {slug} --pr {n}; then` (0 = stale) → re-run; then on a checkout of the PR head `…/explain_cli.py post --slug {slug} --pr {n} --context autonomous --envelope <final.json> || true`, `…/explain_cli.py rulings-fold --slug {slug} || true`. `two-stable` flush stages `completed-tp-designs/{slug}/rulings.ndjson` and `completed-tp-designs/{slug}/decisions.md`; `rulings.ndjson` is no `round_log_carry.ROUND_LOG_NAMES` file: that commit stays unpushed.
   - Flush: `round_scratch.py flush` appends the loop log to `decisions.md`; `two-stable`: committed and pushed (log-only); else `decisions.md` as modified and uncommitted.
   - Proof-neutral head move: after a converged head moves only by `proof_neutral_carry` commits (living-doc and comment-only edits, or a base-sync merge whose hand-resolved paths are all living docs), run `carry_check.py --repo . --pr-url <url>`; exit 0 means no new round and no new proof, so a docs-only base-sync is carried and never re-reviewed, and the head still needs a fresh ci-local stamp. A sync that hand-resolves code or skill text is a delta round.

- State is persisted by `run_round.py` each round, so a crash between rounds is resumable from the written state file (in-worktree, untracked; see the resume caveat).

### Step 2 — Clip + log

- Clip the envelope (`SKILL.md` ## Return clipping); log `[tp-run-full-design/tier-7] pr-iterate-{converged|budget-exhausted|cap-reached} {pr-url}`.
- **Ping.** When the converge terminal JSON carries `ready_ping.status == "sent"`, append its `decisions_line` to `decisions.md` and, when the `PushNotification` tool is available (`ToolSearch select:PushNotification`), call it with the `message`. The marked line is already printed, so an unavailable tool changes nothing; `duplicate` and `skipped` do nothing.
- Base moved mid-loop: run `/tp-merge-from-main`, never a free-hand `git merge`.

### Just-do-it round

- When `python3 "$TP_ROOT"/skills/_shared/weight_class.py review-weight <design_dir>` prints `just-do-it`, the loop is one round: round 1 is the light round (one combined finder + opus-check, `security` only on a gate or trust-boundary path, per `light_round.py`). Clean → the same scratch check, then `converge.py` as usual. Blocking → one inline tail fix, then one confirm round scoped to the fix delta (the round cap the text above relies on is 2 for `just-do-it`). Still blocking at the cap → `budget-exhausted` → the finalizer path (`SKILL.md` § Cleanup step 0). Never skip Tier 7 for a just-do-it run. A run escalated to `light` by Tier 1 uses the light round instead.

### The merge-only gate

- Tier 7 pushes fix commits, never merges: a human reviews the reviewed-stable PR, runs `/tp-merge`. Never hand-merge or auto-merge: autonomous through push + PR + review-response, paused before `/tp-merge`. Never escalate a non-converged loop past the gate.

### Tier 7 outcomes

- Converged → decisions.md `pr-iterate-converged`; exit 0.
- Blocked — no independent review → `tp:needs-human-attention`, report `pr-iterate-cap-reached`. Byproduct-only + proof-bound (review-integrity-enforcement): `run_round.py` emits `converged=true` only from a two-stable terminal bound to `convergence_proof.non_degraded_proof_on_head`; degraded/absent proof or unparseable/NO-ANGLES → `not_converged_reason`, bump `degraded_review_retries` (bound 1), re-`capture_proof`/`post_codereview_comment`, re-shell; at the bound: not-converged + escalate (`tp-pr-iterate/proof-of-review.md` §Convergence action contract).
- Budget exhausted (`budget-exhausted` / `cap-exhausted` / `convergence-failure`) → finalizer first (`SKILL.md` § Cleanup step 0); on escalate `[tp-run-full-design/tier-7] pr-iterate-budget-exhausted {pr-url}`; exit 0. Reported with every `holding` signal and `decisions.md` as modified and uncommitted; not escalated.
- Loop non-start → `pr-iterate-noop`; exit 0. A Copilot review that never attaches isn't one.
- **Every terminal outcome above** shells `python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/sweep_orphan_branches.py --slug {slug}` once (`SKILL.md` ## Cleanup).
