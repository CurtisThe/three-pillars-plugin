---
name: tp-pr-iterate
description: "Autonomous PR-iteration loop driver — poll review comments, classify (heuristic + Sonnet), defer conflicting structural fixes, dispatch to `tp-pr-fix` per round, apply caps + guards, terminate at the classifier-flip from `structural-present` to `minor-only`."
argument-hint: "{design} [--max-iterations N=8] [--max-wall-clock 4h] [--dry-run]"
---

# tp-pr-iterate — PR-Iteration Loop Driver

A long-running loop over a single open PR. Each iteration polls for new
review comments, classifies them, defers conflicts to a human, calls
`tp-pr-fix.run_round` for the structural subset, and re-enters the wait.
Terminates on:

- **Classifier-flip** (success) — the most recent classification round
  produced no `structural` verdicts (all `minor` or `unclear`). The PR
  is now in shape for a human reviewer.
- **Idle timeout** (success-adjacent) — no new comments for 30 minutes
  AND the prior round was not `structural-present`.
- **Mid-loop human push** (yield to human) — a non-`[tp-pr-fix iter-` commit
  appeared on the branch since `last_loop_sha`.
- **Caps** — iteration count exceeded (`max_iterations`, default 8) or
  wall-clock budget exhausted (`max_wall_clock`, default 4h).
- **Convergence failure** — cumulative diff has grown past 3× the
  loop-open baseline, OR three consecutive rounds returned
  `structural-present`.
- **All-conflicting deferral** — every comment in a round had an
  overlapping `line_range` with another, so the loop couldn't proceed.

## Arguments

- `{design}` — kebab-case design name, validated per `skills/_shared/validate-name.md`.
  Resolves the worktree on branch `tp/{design}` and the design directory.
- `--max-iterations N` — round cap (default 8). Triggers `cap-exhausted`.
- `--max-wall-clock <duration>` — total budget (default 4h). Triggers `cap-exhausted`.
- `--dry-run` — fetch + classify + log what the loop *would* do, but do
  NOT invoke `tp-pr-fix.run_round`. Use this to verify classifier output
  on a real PR before letting the loop write commits.

## Prerequisites

- `gh` CLI installed and authenticated.
- A clean `tp/{design}` worktree with an open PR on `origin`.
- `.three-pillars/config.json` — `pdw.guards.idle_timeout_sec`,
  `pdw.guards.k_consecutive`, `pdw.guards.diff_growth_multiplier` override
  the defaults (1800s / 3 / 3×). When absent, the loop uses the defaults.
- The worker `/tp-pr-fix` is installed (built by Phase 4).

## Loop body

The driver decomposes into pure helpers and one orchestration body. The
helpers are independently tested in `test_loop_driver.py`:

- `_compute_next_wait(prev) -> int` — doubling backoff (60s → 600s cap).
- `_poll_step(state, new_comments, now, config) -> (state, terminal?)` —
  pre-classification checks: idle-timeout, human-push detection.
- `_detect_conflicts(classified) -> (deferred_ids, kept)` — line-range
  overlap predicate for the structural subset.
- `_apply_conflicts(state, classified, now) -> (state, kept, terminal?)` —
  wraps the detect step with transition + terminal logic.
- `_check_guards(state, config, now) -> phase | None` — iteration cap,
  wall-clock, diff-growth, k-consecutive-structural.
- `_apply_guards(state, pr_url, config, now) -> (state, terminal?)` —
  wraps the check with transition + the F9 `tp:needs-human-attention`
  label application.
- `_capture_original_diff(pr_url) -> int` — shell `gh pr diff --stat` at
  loop-open; the value is the baseline for the 3× diff-growth guard.

### Single iteration

0. **Run first-run preflight** per `skills/_shared/first-run.md`. (Runs once at
   loop open, before the first iteration.)
1. **Backoff sleep** — `time.sleep(_compute_next_wait(prev_wait))`. First
   pass uses 60s.
2. **Poll** — `gh pr view <pr_url> --json comments,reviews` (and
   `gh api .../pulls/.../comments` for line-anchored review comments). Also
   fetch the review threads via `thread_resolver.list_review_threads(pr_url)`
   (GraphQL — carries each thread's `thread_id` + first-comment `comment_id`).
2.5. **Dual-source — dispatch `/code-review` ∥ the Copilot poll (Enhancement 1).**
   Concurrently with the GitHub poll, dispatch a local reviewer sub-agent so the
   loop never depends on Copilot's single signal (Copilot under-reports on this
   repo's prose-heavy diffs):

   ```
   review = Agent(
       subagent_type="general-purpose",
       prompt="Run /code-review --effort {high|max} on the PR diff. Read "
              ".github/review-instructions.md for what counts as a real defect "
              "here. Return ONLY a fenced ```json array of "
              "{file, line_range:[start,end], summary, verdict}.",
       description="dual-source-code-review",
   )
   codereview_findings = review_merge.parse_codereview_response(review)
   ```

   Effort is `high` by default; escalate to `max` only when the prior round
   stalled (`state.consecutive_structural_rounds >= 1`). Subagents cannot nest,
   so this `/code-review` dispatch is a **1-level fan-out** from the loop. Both
   reviewers are driven by the shared `.github/review-instructions.md` (the local
   reviewer is handed it in the prompt; Copilot reads the synced
   `.github/copilot-instructions.md`) so "stable" means the same thing on each
   side and known-intentional patterns aren't re-flagged.
3. **Pre-classification checks** — call `_poll_step(state, new_comments,
   now, config)`. If terminal, persist + return.
4. **Heuristic prefilter** — for each comment, call
   `from skills._shared.classifier_heuristic import classify` directly
   (no Agent — this is pure deterministic Python). Split into `decided`
   and `borderline`.
5. **Sonnet judge on borderlines** — invoke the model via SKILL prose:

   ```
   prompt   = classifier_judge.build_prompt(borderline, diff_context)
   response = Agent(
       subagent_type="general-purpose",
       model="claude-sonnet-4-6",
       prompt=prompt,
       description="classify-borderline-pr-comments",
   )
   classified_borderline = classifier_judge.parse_response(response)
   ```

   `classifier_judge` only constructs the prompt and validates the
   response against `classified-comment.v1.json` — **it has no
   `import anthropic`** (asserted by Task 5.8's `ast.parse` invariant
   test). The model invocation is the only step that lives in this
   prose, not in the helper.

6. **Merge** — `classified = decided + classified_borderline`.
6b. **Normalize + dedupe both sources (Enhancement 1).** Map the classified
   Copilot comments via `review_merge.normalize_copilot` and the
   `codereview_findings` via `review_merge.normalize_codereview`, then
   `review_merge.dedupe(union)`. On a file + line-proximity + summary-similarity
   collision the **Copilot finding wins** (it carries the `thread_id`
   reply-and-resolve needs) and the dropped twin's id is recorded in
   `merged_from`. The deduped union is the `kept` set handed to the fix round —
   each iteration deals with both reviews at once.
7. **Conflict-defer** — `_apply_conflicts(state, classified, now)`. If
   every structural comment conflicted, terminal `awaiting-human-review`
   with note `[all-conflicting-deferred-to-human]`.
8. **Compute round verdict** — derive `last_verdict` from the kept set:
   `structural-present` if any kept comment has `verdict="structural"`,
   else `minor-only`. The **classifier-flip** from `structural-present`
   to `minor-only` is the loop's success signal — the round that flips
   is the one whose result transitions the phase to `awaiting-human-review`.
9. **Dispatch fix round** — when `--dry-run` is OFF and `last_verdict`
   warrants action: `fix_round.run_round(design, pr_url, iteration,
   classified=kept, head_ref=head_ref, loop_mode=True)`. `head_ref` is resolved
   **once at loop-open** via `gh pr view <pr_url> --json headRefName` (F1: the
   fix must land on the actual PR head — an orchestrator PR's head is
   `candidate/{slug}/single`, not `tp/{design}`; `loop_mode=True` auto-checks-out
   the head before committing). Accumulate `envelope.diff_lines_added` into
   `state.cumulative_diff_lines`. Persist the envelope under
   `<worktree>/.three-pillars/run/fix-envelope.iter-N.json`.
9.5. **Reply-and-resolve every Copilot thread (load-bearing, Enhancement 1).**
    For each Copilot finding this round, post a worker-signed disposition reply
    and **then** resolve the thread — the reply ALWAYS precedes the resolve, and
    the loop never resolves a thread without first leaving the evidence reply:

    ```
    for f in copilot_findings:
        disp = thread_resolver.disposition_for(f, envelope, resolved_thread_ids)
        body = thread_resolver.sign_reply(_disposition_text(disp, f, envelope), pr_author)
        if thread_resolver.reply_to_thread(pr_url, f["comment_id"], body):
            if thread_resolver.resolve_thread(f["thread_id"]):
                resolved_thread_ids.add(f["thread_id"])
                resolved_this_round.add(f["thread_id"])
    ```

    The reply is signed `🤖 three-pillars-worker (on behalf of @{author})` — the
    worker identity, paralleling `fix_round`'s `GIT_COMMITTER_EMAIL` override, so a
    reader tells worker actions from the human author. Disposition is `addressed`
    (links the fixing commit), `stale` (cites the prior-round resolution as
    evidence), or `deferred` (reason). Copilot re-posts comments anchored to
    unchanged diff lines every round; without reply-and-resolve the loop
    re-litigates already-fixed items forever and the new-vs-stale signal is
    unusable. Resolve uses GraphQL `resolveReviewThread` — never `gh pr edit`
    (broken on this repo). Track every observed `thread_id` in
    `state.seen_thread_ids` and every resolved one in `state.resolved_thread_ids`.
10. **Guard checks** — `_apply_guards(state, pr_url, config, now)`. If
    terminal (cap-exhausted | convergence-failure), apply the F9 label
    `tp:needs-human-attention` and persist.
10b. **Two-stable termination (Enhancement 1).** Call
    `_two_stable_terminal(state, codereview_findings, copilot_threads,
    resolved_this_round)`. It returns True only when, in this single round,
    `/code-review` returned `[]` **AND** every Copilot thread is a known,
    freshly-resolved stale re-post (zero NEW unresolved threads). On True,
    transition to `awaiting-human-review` with `termination_reason="two-stable"`.
    This is the dual-source success signal: the single-source classifier-flip
    (step 8) is necessary but **no longer sufficient** — terminating on the
    GitHub review alone going `minor-only` could declare a PR stable while real
    cross-file defects the local `/code-review` would catch sit unflagged.
    Terminate only when **both** sources are stable in the same round.
11. **Persist iterate-state** — atomic write to
    `<worktree>/.three-pillars/run/state.json` under the `iterate`
    namespace (including `seen_thread_ids` / `resolved_thread_ids` /
    `termination_reason`). Update `last_loop_sha` from `git rev-parse HEAD`
    after a successful push, so the next iteration's human-push detector reads
    a fresh baseline.

### Termination matrix

| Phase                     | Triggered by                                                 | F9 label? |
| ------------------------- | ------------------------------------------------------------ | --------- |
| `awaiting-human-review`   | two-stable (dual-source) / classifier-flip / idle-timeout / human-push / all-conflicting | no        |
| `cap-exhausted`           | `iteration > max_iterations` OR wall-clock                    | yes       |
| `convergence-failure`     | diff > 3× original OR `k_consecutive` structural rounds       | yes       |
| `errored`                 | unhandled exception in the loop body                          | yes       |

The `termination_reason` field records which trigger fired. In the dual-source
loop (Enhancement 1) the **two-stable** reason is the primary success signal —
a round where `/code-review` returns `[]` and the only Copilot threads are
freshly-resolved stale re-posts.

## --dry-run mode

Steps 1–8 run normally; step 9 is replaced with a stdout log of what
`fix_round.run_round` *would* have committed. The state.json is still
persisted so the dashboard reflects the loop's view. Use this to verify
classifier behavior on a real PR before opting in to automated commits.

## Architectural constraints (C1)

- **No `import anthropic` in `classifier_judge.py`.** Asserted by Task 5.8's
  `ast.parse` walk. The Sonnet invocation lives in this prose via `Agent()`.
- **No `subprocess.run(["claude", ...])` in helpers.** Same rule, same
  reason. If the loop body needs the model, the call is made here and
  the result is parsed by `parse_response`.
- **One commit per round at most.** Owned by `fix_round.run_round`, not
  this driver. The loop driver never calls `git commit` itself.
- **`last_loop_sha` write-back is mandatory.** Without it, the human-push
  detector cannot distinguish loop commits from human commits, and the
  loop will silently no-op on its own commits as if they were human
  intervention. **The loop driver owns this write** — after `fix_round`
  returns successfully (the worker has committed and pushed), the driver
  captures the new HEAD via `git rev-parse HEAD` and persists it under
  the `iterate.last_loop_sha` namespace of `state.json` before the next
  iteration's `_poll_step`. `fix_round` itself touches no iterate-state;
  the worker contract is one round of commit + push + label + envelope
  return, nothing more.

## Failure modes worth knowing

- **`gh` auth missing.** First `gh pr view` exits non-zero with `auth
  required` in stderr. The loop logs and retries with backoff; if the
  failure persists past the wall-clock cap, the loop terminates as
  `cap-exhausted`.
- **PR closed mid-loop.** `gh pr view` reports `state: CLOSED`. The
  loop transitions to `awaiting-human-review` with note `"[pr-closed]"`
  and exits.
- **Classifier prompt rejected by Sonnet.** `parse_response` raises
  `jsonschema.ValidationError`. The driver logs the raw response,
  treats the round as `unclear` for every borderline comment, and
  continues. Three consecutive `unclear` rounds count toward
  `k_consecutive` and may trigger `convergence-failure`.
- **Base moved under the PR (`mergeStateStatus: DIRTY`/`BEHIND`).** Another
  PR merged to the base and the branch now conflicts (commonly on the shared
  living docs). **Do NOT hand-merge or hand-resolve** — run **`/tp-merge
  {design}`** to merge the base in, auto-resolve the mechanical living-doc
  conflict classes behind its zero-drop verifier, defer anything semantic for
  you to finish, re-run tests, and re-push. `/tp-merge` is the dedicated
  conflict-resolution skill for exactly this case; a free-hand `git merge` skips
  its zero-drop verifier and risks a silent content-drop. Resume the loop once
  `/tp-merge` reports the branch green and pushed.

## Copilot review gotchas (observed)

The loop polls, classifies, reply-resolves, and re-requests Copilot (steps 2 / 2.5 / 9.5 /
the per-round re-request). Three GitHub-side quirks bite that flow — all observed 2026-06-04
across PRs #45/#46. Get any of them wrong and a round silently misreads Copilot's signal.

- **The Copilot login differs by surface — a single hard-coded filter yields false zeros.**
  The bot's `login` is **not** consistent across the APIs the loop reads:
  - `requested_reviewers[].login` → **`Copilot`**
  - the **review** object author (REST `pulls/<PR>/reviews`) → **`copilot-pull-request-reviewer[bot]`**
  - each **inline finding comment** (REST `pulls/<PR>/comments`) → **`Copilot`**
  - GraphQL `reviewThreads…author.login` → **`copilot-pull-request-reviewer`**

  Filtering reviews by `Copilot`, or comments by `copilot-pull-request-reviewer[bot]`,
  matches nothing — so a *successful* review reads as "0 findings" (a **false zero**) and the
  loop wrongly flips to `minor-only`. Match the **right** login per surface. For the
  trusted-bot identity check, don't re-list logins here — defer to the canonical allowlist
  `_TRUSTED_REVIEWER_BOTS` in `tp-pr-fix/scripts/fix_round.py` (`copilot`,
  `copilot-pull-request-reviewer[bot]`, `copilot[bot]`, `github-copilot[bot]`; lowercase-matched,
  extend per-repo via `TP_PR_FIX_TRUSTED_BOTS`). Treat any such set as **a superset to match
  against, never exhaustive** — and note GraphQL adds a fourth spelling,
  `copilot-pull-request-reviewer` (no `[bot]`), that the identity allowlist omits because
  GraphQL strips the suffix. The review body's "generated N comment(s)" is the cross-check:
  if it says N>0 but your comment filter returns 0, the filter login is wrong.

- **"Copilot encountered an error" is usually a transient GitHub-side build crash, not your
  diff — never classify it, never terminate on it.** Copilot can post a `COMMENTED` review
  whose body is *"Copilot encountered an error and was unable to review this pull request"*
  with **zero** comments. Observed root cause: `ERR_MODULE_NOT_FOUND: detect-libc` in
  GitHub's `@github/copilot` CLI (the npm optional-dependency bug on their runner) — it
  crashes at **startup, before reading the diff**, so it fails *identically on every PR/SHA*
  and is **content-independent** (do **not** edit your diff to appease it; read the review
  job log first). It is **transient** and clears server-side. Treat an error-body review as
  **no signal**: skip it in classification, lean on the dual-source `/code-review` arm for
  the round (precisely why the loop is dual-source — single-source Copilot is not load-bearing),
  and re-request only on the next pushed SHA or once it clears server-side — a *same-SHA* retry
  is deduped (next bullet) and won't restart Copilot.

- **A re-request only re-fires on a NEW head SHA.** Re-POSTing `requested_reviewers` with the
  Copilot bot on an **unchanged** head SHA that already carries a Copilot review (even an
  error one) is **deduped** by GitHub — no new run. A genuine re-review fires on a **new
  commit** (new head SHA) or once a transient error clears. Consequence for the loop: the
  per-round re-request *after a `tp-pr-fix` commit* works (the fix advanced the SHA); a
  re-request to retry a transient *error* on the same SHA usually will not — wait for recovery
  or push a commit.

## See also

- `_shared/classifier_heuristic.py` — pure-deterministic prefilter (Phase 4).
- `tp-pr-iterate/scripts/classifier_judge.py` — prompt + parse helper.
- `tp-pr-iterate/scripts/review_merge.py` — normalize + dedupe the dual review sources (Enhancement 1).
- `tp-pr-iterate/scripts/thread_resolver.py` — reply-and-resolve Copilot threads (Enhancement 1).
- `tp-pr-iterate/scripts/loop_driver.py` — helpers + entry point (incl. `_two_stable_terminal`).
- `tp-pr-iterate/schemas/iterate-state.v1.json` — loop-state schema.
- `tp-pr-iterate/schemas/normalized-finding.v1.json` — dual-source finding schema (Enhancement 1).
- `.github/review-instructions.md` — shared review guidance both reviewers consume (Enhancement 1).
- `tp-pr-iterate/schemas/classified-comment.v1.json` — per-comment verdict schema.
- `tp-pr-fix/SKILL.md` — the single-round worker this loop dispatches to.
- `tp-merge/SKILL.md` — the base-into-branch conflict resolver to invoke when the PR goes `DIRTY`/`BEHIND` mid-loop (never hand-merge).
- `tp-pr-fix/scripts/fix_round.py` — deterministic identity-gate + commit + push + label helper. (Owns no iterate-state; `last_loop_sha` write-back is the loop driver's job — see above.)
