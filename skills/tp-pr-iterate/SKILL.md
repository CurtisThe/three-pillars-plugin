---
name: tp-pr-iterate
description: "Autonomous PR-iteration loop driver — poll review comments, classify (heuristic + Sonnet), defer conflicting structural fixes, dispatch to `tp-pr-fix` per round, reply-and-resolve every thread, apply caps + guards, and terminate only at two-stable: both review sources quiet AND zero unresolved actionable threads verified against GitHub. Classifier-flip is necessary but not sufficient."
argument-hint: "{design} [--max-iterations N=8] [--max-wall-clock 4h] [--dry-run]"
---

# tp-pr-iterate — PR-Iteration Loop Driver

A long-running loop over a single open PR. Each iteration polls for new
review comments, classifies them, defers conflicts to a human, calls
`tp-pr-fix.run_round` for the structural subset, and re-enters the wait.
Terminates on:

- **Two-stable** (the one success terminal) — in a single round **both**
  review sources are quiet (`/code-review` returns `[]` AND no new `structural`
  Copilot verdicts) **AND** every actionable thread has been replied-and-resolved,
  verified against GitHub: a fresh `list_review_threads(pr_url)` shows **zero
  unresolved** Copilot / code-review threads. Only then is the PR human-ready.
  A classifier-flip (no `structural` verdicts this round) is a **necessary
  precondition**, **never sufficient on its own** — flipping on a stale snapshot
  while threads sit unresolved is the exact failure that makes a PR look "stable"
  when it isn't.
- **Idle timeout** (yield to human) — no new comments for 30 minutes AND the
  prior round was not `structural-present`. This is a **time-based yield**, not a
  verified-stable claim: `_poll_step` does NOT run the ground-truth
  zero-unresolved re-fetch (only **two-stable** does), so the terminal carries the
  `[idle-timeout]` transition note and leaves `termination_reason` unset —
  consumers must treat only `termination_reason="two-stable"` as reviewed-stable.
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
  `review.expects_copilot` (default true) declares whether Copilot code review is an
  available reviewer here; set it **false** on a repo with no Copilot entitlement so
  the two-stable terminal converges on the `/code-review` arm alone instead of
  spinning to `cap-exhausted` (see step 10b — Copilot-optional terminal).
- The worker `/tp-pr-fix` is installed (built by Phase 4).

## Loop body

The driver is assembled as `run_loop` in `loop_driver.py` (Phase 4 of
`pr-iterate-loop-encode`). It decomposes into pure helpers and one
orchestration body; all are independently tested in `test_loop_driver.py`:

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
2.5. **Dual-source — fan out a MULTI-ANGLE `/code-review` ∥ the Copilot poll (Enhancement 1).**
   Concurrently with the GitHub poll, run a local review so the loop never depends on
   Copilot's single signal. **A single `/code-review` subagent cannot fan out into the
   skill's own multi-angle finder/verifier harness (L23 — a subagent can't spawn
   sub-subagents), so a lone dispatch is a single-pass review that misses what the full
   harness catches.** The loop driver runs at the **top level**, so it fans out the
   angles ITSELF — several parallel finder dispatches (each a 1-level fan-out), merged
   fail-closed:

   ```
   ANGLES = [
       ("correctness-leak", "Hunt fail-closed/correctness leaks: any path to a wrong "
                            "result, a non-handled error, an unsafe edge case."),
       ("edge-cases",       "Boundary/degenerate inputs, ordering dependence, off-by-one, "
                            "type-coercion, missing-key, empty-collection behavior."),
       ("test-quality",     "Do the tests actually guard their claims? Untested branch, "
                            "a test that passes even if the code were wrong, missing case."),
   ]
   # `effort` is supplied by the driver: run_loop calls poll_fn(effort) where
   # effort == _codereview_effort(state) ("max" after a stalled code-review round,
   # else "high"). Apply it to each angle's /code-review invocation.
   responses = [
       Agent(subagent_type="general-purpose", description=f"code-review:{name}",
             prompt=f"Review `git diff {base}...{head}` for: {angle}. Run at "
                    f"--effort {effort}. Read .github/review-instructions.md for what "
                    "counts as a real defect here. "
                    "Return ONLY a fenced ```json array of {file, line_range:[start,end], "
                    "summary, verdict} (verdict: structural|minor). [] only if genuinely clean.")
       for (name, angle) in ANGLES
   ]
   codereview_findings = review_merge.merge_codereview_angles(responses)  # fail-closed parse + dedupe
   # MANDATORY, every invocation — post the review summary to the PR so it is
   # never silent (parallel to a Copilot review). Fires even when findings == [].
   review_merge.post_codereview_comment(pr_url, codereview_findings, head_sha=head_sha)
   ```

   - **Multi-angle, not single-pass.** Dispatch the angle set every round at the
     `--effort` level the driver passes in. The driver escalates to `--effort max`
     when the prior round had its own code-review structural findings —
     `state.consecutive_codereview_structural_rounds >= 1`, the code-review-specific
     counter, NOT the Copilot/thread `consecutive_structural_rounds`. The escalation
     is computed by `_codereview_effort(state)` and reaches the poll via
     `poll_fn(effort)` (run_loop passes it whenever poll_fn declares an `effort`
     parameter). Fanning out at the driver level is the only L23-safe way to get
     harness-grade coverage inside the loop; a single `/code-review` subagent
     reviewing in one pass demonstrably misses real defects.
   - **Fail-closed parse — an UNPARSEABLE review is NOT a clean one.**
     `review_merge.merge_codereview_angles` (via `parse_codereview_findings_or_block`)
     parses each angle with `parse_codereview_result`, which distinguishes a genuine
     `[]` (clean) from "no parseable JSON array" (unparseable). An unparseable angle
     contributes a **structural** `_unparseable_finding` sentinel rather than collapsing
     to `[]`, so a silent parse failure can **never** read as clean and false-converge
     the two-stable terminal. Never use the bare `parse_codereview_response` on the
     convergence path.
   - **Posting the summary comment is mandatory on every invocation, including a clean
     (`[]`) result** — `review_merge.post_codereview_comment` renders a Copilot-style
     body grouped by severity and posts it via REST. No silent reviews: each round
     leaves a visible, auditable PR record (a parse failure shows as a structural
     "could not be parsed" finding, not "no findings"). Fail-open (a failed post is
     logged, never crashes the loop) but always attempted.
   - All angles + Copilot are driven by the shared `.github/review-instructions.md` (the
     local angles are handed it in the prompt; Copilot reads the synced
     `.github/copilot-instructions.md`) so "stable" means the same thing on each side
     and known-intentional patterns aren't re-flagged.
   - **Shell `run_round.py` with the fan-out result.** After the ANGLES fan-out and
     `post_codereview_comment`, the standalone path drives the round decision the same
     way as the orchestrator: pass the real fan-out findings (or the `no-angles` sentinel
     on failure) to `run_round.py` via its stdin JSON contract (see `run_round.py`).
     The stdin object **must** include `config` (read from `.three-pillars/config.json`)
     and `ci_rollup` (the most-recent `statusCheckRollup`) so the wrapper resolves
     `review.expects_copilot` and `ci.expects_github_checks` correctly. Omitting `config`
     defaults both to `true`, which blocks code-review-only convergence on repos without
     Copilot. (F-P1)
     Never rely on an in-context self-pass as the review source — a single-context
     `/code-review` that runs in the same LLM context as the loop is not an independent
     review and must never be signed `/code-review` in the convergence path. The honest-
     attribution rule: only a real top-level ANGLES fan-out (or a cached finding from one)
     may satisfy `_independent_review_ran`; a same-context pass does not.
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
   else `minor-only`. The **classifier-flip** from `structural-present` to
   `minor-only` is a **necessary precondition** for success, **not a terminal
   on its own**. Never transition to `awaiting-human-review` on the flip alone —
   success is decided only by **two-stable** (step 10b), which additionally
   requires zero unresolved actionable threads verified against GitHub. A flip on
   a stale snapshot with threads still open is the convergence bug this rule
   exists to prevent.
9. **Dispatch fix round** — when `--dry-run` is OFF and `last_verdict`
   warrants action: `fix_round.run_round(design, pr_url, iteration,
   classified=kept, head_ref=head_ref, loop_mode=True)`. `head_ref` is resolved
   **once at loop-open** via `gh pr view <pr_url> --json headRefName` (F1: the
   fix must land on the actual PR head — an orchestrator PR's head is
   `candidate/{slug}/single`, not `tp/{design}`; `loop_mode=True` auto-checks-out
   the head before committing). Accumulate `envelope.diff_lines_added` into
   `state.cumulative_diff_lines`. Persist the envelope under
   `<worktree>/.three-pillars/run/fix-envelope.iter-N.json`.
9.5. **Re-request Copilot review + Reply-and-resolve every Copilot thread (load-bearing, Enhancement 1).**
    Per-round Copilot re-request is handled by `_request_copilot_review(pr_url)` (fail-open;
    a non-zero return or raised exception returns False and the loop continues). The loop
    sets phase `awaiting-copilot` around the subsequent CI/Copilot wait (see
    `_ci_settled_on_head`). After the wait, the loop proceeds to classify.

    Reply-and-resolve every Copilot thread:
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

    **9.5 is mandatory every round, and disposition is ONLY ever `disposition_for`'s
    output — never a hand-judged "stale".** A finding is `stale` *only* when its
    `thread_id` is already in `resolved_thread_ids` (resolved in a PRIOR round); a
    brand-new thread is `addressed` (fix landed) or `deferred` (stays open for the
    human) — never `stale`. Every observed thread MUST end the round either
    resolved (reply-and-resolve) or explicitly deferred; **a thread left neither
    resolved nor deferred BLOCKS every success terminal.** This is the rule the
    `wave1-0605` #56 run violated — it hand-labeled a brand-new Copilot round as
    "stale re-flags," skipped 9.5, and declared a bare classifier-flip; the
    ground-truth assertion in step 10b now makes that impossible.
10. **Guard checks** — `_apply_guards(state, pr_url, config, now)`. If
    terminal (cap-exhausted | convergence-failure), apply the F9 label
    `tp:needs-human-attention` and persist.
10b. **Two-stable termination (the only success terminal).** The round decision step
    (`run_round.py` / `loop_driver.run_round`) evaluates four conjuncts before converging.
    Only when all hold in the same round do you transition to `awaiting-human-review`:

    1. `last_verdict == "minor-only"` — the classifier-flip (step 8). Necessary but not
       sufficient: a flip on a snapshot taken before CI-settle or a late Copilot round
       cannot be trusted.
    2. `_ci_all_success(ci_rollup, config)` — CI settled on this head and all checks pass.
    3. `unresolved_actionable == 0` — a ground-truth re-fetch (`unresolved_actionable_fn`)
       confirms zero unresolved actionable threads. The in-loop bookkeeping alone is not
       the gate (fail-closed on an unverifiable / missing fn).
    4. **`_independent_review_ran`** (new, M2) — a real, independently-dispatched
       `/code-review` fan-out ran for the current head and its findings are non-degraded
       (`review_available`), OR Copilot has reviewed (`copilot_reviewed_successfully(pr_url)`).
       Computed as:
       `(expects_copilot and reviewed is True) OR review_available`, where
       `review_available = (last_codereview_head_sha == head_sha and head_sha is not None)
       and not is_degraded_review(codereview_findings)`.
       This is the M2 **current-head guarantee**: a real review of a *prior* head does
       NOT satisfy the conjunct. A same-context self-pass is never `review_available` —
       only a real top-level ANGLES fan-out (or a cache of one for the exact current head)
       qualifies.

    When conjuncts 1–3 hold AND conjunct 4 is **False** (no independent review ran for
    this head): transition `blocked-no-independent-review`, apply `tp:needs-human-attention`,
    append the `BLOCKED — no independent review ran` line to `decisions.md`. This is a
    **terminal** — `run_round` returns `terminal="blocked-no-independent-review"` and
    `run_loop` stops. The `tp:needs-human-attention` label signals the review-blocker for
    human follow-up. Never apply `tp:ready-for-human-merge` on this path.

    When all four hold: transition `awaiting-human-review` with `termination_reason="two-stable"`,
    apply `tp:ready-for-human-merge` (via `_ensure_pr_label`), append the
    `[pr-readiness/terminal]` line to `decisions.md`. The loop is **fail-open** on the
    readiness check: a missing/erroring `reviewed_fn` is UNVERIFIABLE → the loop keeps
    iterating to a cap/idle terminal, never false-converges.

    **Copilot-optional terminal (`review.expects_copilot`).** The Copilot conjunct
    (`reviewed is True`) is required **only when Copilot is an available reviewer** —
    `_expects_copilot_review(config)`, reading `review.expects_copilot` from
    `.three-pillars/config.json` (default true). When it is **false** (structural
    entitlement absence), the Copilot disjunct of `_independent_review_ran` is dead, so
    `review_available` alone carries the fourth conjunct — the dual-source `/code-review`
    arm is the load-bearing reviewer. The transition note is `two-stable [code-review-only]`;
    `termination_reason` stays `"two-stable"`. With `review.expects_copilot` true (the
    default), behavior is unchanged.

    **Honest-attribution rule.** A single-context self-pass (a `/code-review` running
    inside the same LLM context as the loop, reading the diff in-context rather than as
    a separate Agent dispatch) is NOT an independent review. It must never be signed as
    `/code-review` on the convergence path. Only a real top-level ANGLES fan-out — or a
    cache of one for the current head — may satisfy `review_available`.
11. **Persist iterate-state** — atomic write to
    `<worktree>/.three-pillars/run/state.json` under the `iterate`
    namespace (including `seen_thread_ids` / `resolved_thread_ids` /
    `termination_reason`). Update `last_loop_sha` from `git rev-parse HEAD`
    after a successful push, so the next iteration's human-push detector reads
    a fresh baseline.

### Termination matrix

| Phase                              | Triggered by                                                 | F9 label? |
| ---------------------------------- | ------------------------------------------------------------ | --------- |
| `awaiting-human-review`            | **two-stable** (success: both sources quiet + GitHub shows zero unresolved actionable threads) / idle-timeout (time-based yield — no ground-truth check) / human-push / all-conflicting | no        |
| `blocked-no-independent-review`    | conjuncts 1–3 hold but no independent review ran for the current head (`_independent_review_ran` False) — terminal, not a keep-looping yield | yes       |
| `cap-exhausted`                    | `iteration > max_iterations` OR wall-clock                    | yes       |
| `convergence-failure`              | diff > 3× original OR `k_consecutive` structural rounds       | yes       |
| `errored`                          | unhandled exception in the loop body                          | yes       |

The `termination_reason` field records which trigger fired. **Two-stable is the
only success terminal** — a round where `/code-review` returns `[]`, every Copilot
thread is freshly resolved, AND a ground-truth `list_review_threads` re-fetch shows
zero unresolved actionable threads. Classifier-flip is a necessary precondition
recorded on the round, never a `termination_reason` by itself. On a repo with
`review.expects_copilot=false`, the same `termination_reason="two-stable"` is reached
via the `/code-review` arm alone (transition note `two-stable [code-review-only]`) —
the Copilot conjunct is dropped, the `/code-review` + zero-unresolved-threads gates are
not (see step 10b).

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
  living docs). **Do NOT hand-merge or hand-resolve** — run **`/tp-merge-from-main
  {design}`** to merge the base in, auto-resolve the mechanical living-doc
  conflict classes behind its zero-drop verifier, defer anything semantic for
  you to finish, re-run tests, and re-push. `/tp-merge-from-main` is the dedicated
  base-sync conflict-resolution skill for exactly this case; a free-hand `git merge` skips
  its zero-drop verifier and risks a silent content-drop. Resume the loop once
  `/tp-merge-from-main` reports the branch green and pushed. (Landing the PR to
  the base is the separate `/tp-merge` land gate, the human's call.)

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
- `skills/_shared/thread_resolver.py` — reply-and-resolve Copilot threads (Enhancement 1; moved to `_shared/` so free modules can import it without a cross-skill boundary).
- `tp-pr-iterate/scripts/loop_driver.py` — helpers + entry point (incl. `_two_stable_terminal`).
- `tp-pr-iterate/schemas/iterate-state.v1.json` — loop-state schema.
- `tp-pr-iterate/schemas/normalized-finding.v1.json` — dual-source finding schema (Enhancement 1).
- `.github/review-instructions.md` — shared review guidance both reviewers consume (Enhancement 1).
- `tp-pr-iterate/schemas/classified-comment.v1.json` — per-comment verdict schema.
- `tp-pr-fix/SKILL.md` — the single-round worker this loop dispatches to.
- `tp-merge-from-main/SKILL.md` — the base-into-branch conflict resolver to invoke when the PR goes `DIRTY`/`BEHIND` mid-loop (never hand-merge). (The `/tp-merge` land gate is separate — landing the PR is the human's.)
- `tp-pr-fix/scripts/fix_round.py` — deterministic identity-gate + commit + push + label helper. (Owns no iterate-state; `last_loop_sha` write-back is the loop driver's job — see above.)
