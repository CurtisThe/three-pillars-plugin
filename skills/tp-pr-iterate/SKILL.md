---
name: tp-pr-iterate
description: "Autonomous PR-iteration loop driver — poll review comments, classify (heuristic + Sonnet), defer conflicting structural fixes, dispatch to `tp-pr-fix` per round, reply-and-resolve every thread, apply caps + guards, and terminate only at two-stable: both review sources quiet AND zero unresolved actionable threads verified against GitHub. Classifier-flip is necessary but not sufficient."
argument-hint: "{design} [--max-iterations N=8] [--max-wall-clock 4h] [--dry-run] [--dispose-only]"
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
- **Round budget** (`round_budget.tick`, every round, limits from `pdw.guards.*`) —
  `budget-exhausted` (blocking findings at `round_cap`, default 6; diff growth past 1.5×
  the round-1 baseline; test/code ratio; `budget-error`), `cap-exhausted` (wall clock,
  default 4h) or `convergence-failure` (three consecutive blocking review rounds).
- **All-conflicting deferral** — every comment in a round had an
  overlapping `line_range` with another, so the loop couldn't proceed.

## Arguments

- `{design}` — kebab-case design name, validated per `skills/_shared/validate-name.md`.
  Resolves the worktree on branch `tp/{design}` and the design directory.
- `--max-iterations N` / `--max-wall-clock <duration>` — accepted but informational: the
  enforced limits are `pdw.guards.round_cap` / `wall_clock_sec` in config (Termination matrix).
- `--dry-run` — fetch + classify + log what the loop *would* do, but do
  NOT invoke `tp-pr-fix.run_round`. Use this to verify classifier output
  on a real PR before letting the loop write commits.
- `--dispose-only` — calls `thread_dispose.dispose_threads` once and exits;
  no iteration, no fix dispatch, no backoff/poll loop. Use this to
  reply-and-resolve all open review threads out-of-band (e.g. after a
  manual head-SHA bump or when threads arrive outside a loop run). This is
  a flag, NOT a new skill. See the `--dispose-only mode` section below.

## Prerequisites

- `gh` CLI installed and authenticated.
- A clean `tp/{design}` worktree with an open PR on `origin`.
- `.three-pillars/config.json` — `pdw.guards.*` (`round_cap`, `growth_multiplier`,
  `test_code_ratio`, `ratio_floor_lines`, `k_consecutive`, `wall_clock_sec`,
  `idle_timeout_sec`) override the defaults; `review.angles` overrides the review angles.
  `review.expects_copilot` (default true) declares whether Copilot code review is an
  available reviewer here; set it **false** on a repo with no Copilot entitlement so
  the two-stable terminal converges on the `/code-review` arm alone instead of
  spinning to `cap-exhausted` (see step 10b — Copilot-optional terminal).
- The worker `/tp-pr-fix` is installed (built by Phase 4).

## Loop body

Each round follows **`round-topology.md`** (angles as data, per-round and per-angle scratch,
path authority, round tail, inline-fix contract, log flush, recovery). The round decision is
`loop_driver.run_round` (shelled as `run_round.py`), which calls `round_budget.tick` every round.
Pure helpers, all independently tested in `test_loop_driver.py`:

- `_compute_next_wait(prev) -> int` — doubling backoff (60s → 600s cap).
- `_poll_step(state, new_comments, now, config) -> (state, terminal?)` —
  pre-classification checks: idle-timeout, human-push detection.
- `_detect_conflicts(classified) -> (deferred_ids, kept)` — line-range
  overlap predicate for the structural subset.
- `_apply_conflicts(state, classified, now) -> (state, kept, terminal?)` —
  wraps the detect step with transition + terminal logic.
- `round_budget.tick(state, ...) -> (state, terminal?, detail)` — round cap, diff
  growth, test/code ratio, k-consecutive, wall clock; a terminal gets the F9 label.

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
   fail-closed. The ANGLES are data (`angles.py` `DEFAULT_ANGLES`, or `review.angles`);
   the round runs the round-dir flow of `round-topology.md`:

   1. `round_scratch.py prepare --effort <_codereview_effort(state)> …` → round dir `R` and
      `R/angles.json`, the path authority (state, loop log, per-angle reply paths, `base`).
   2. Fan out every manifest angle as `Agent(subagent_type="general-purpose", model="opus",
      prompt=<manifest prompt>)` — reviews always Opus. Each writes its reply to its own
      per-angle `reply_path` and returns one line.
   3. Round tail: `reproduce.py --round-dir R --cwd . --head <head>` merges the replies
      (`review_merge.merge_codereview_angles`, fail-closed) and runs each blocking finding's
      reproducer; a non-reproducing finding becomes a non-blocking note.
   4. Clean round: `converge.py --round-dir R`. Otherwise
      `review_merge.post_codereview_comment` (MANDATORY, every invocation, even on `[]`), then
      shell `run_round.py` with stdin `pr_url`, `round`, `ordinal`, `class_log_path` and
      `review_base` (the base-branch tip, re-fetched every round) from the manifest.
   5. On `action == "fix"`: the inline fix (step 9), `paths=` from `tree_scope.derive_fix_paths`.
   6. `round_scratch.py tail-check --round-dir R`; at a terminal `round_scratch.py flush` moves
      the loop log into `decisions.md` (committed only at `two-stable`, never pushed).

   - **Multi-angle, not single-pass.** Dispatch the angle set every round at the
     `--effort` level `_codereview_effort(state)` computes: `max` when the prior round had
     its own code-review structural findings (`consecutive_codereview_structural_rounds
     >= 1`, NOT the Copilot/thread `consecutive_structural_rounds`), else `high`. Fanning
     out at the driver level is the only L23-safe way to get harness-grade coverage
     inside the loop; a single `/code-review` subagent reviewing in one pass
     demonstrably misses real defects.
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
   - **Shell `run_round.py` with the fan-out result** — the same round decision as the
     orchestrator: the tail findings (or the `no-angles` sentinel on failure) via its stdin
     JSON contract. The stdin object **must** include `config` (read from `.three-pillars/config.json`)
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
   `codereview_findings` via `review_merge.normalize_codereview`, then rebind
   `classified = review_merge.dedupe(union)` — the deduped union, with its promoted verdicts, is what steps 7–9 read. Collision = same file AND either an IDENTICAL line range (exact-match short-circuit — two angles word one defect differently but agree on the coordinates; NOT applied to anchorless `(0, 0)` pairs, nor — on the exact OR fuzzy path — to pairs carrying two DISTINCT Copilot `thread_id`s, which are two real threads) or a proximate range with similar summaries. An anchorless pair still collapses on the fuzzy path when the summaries match, but the `(0, 0)` sentinel is proximate only to another sentinel, never to a real line. The fuzzy comparison runs against a cluster's FIRST-SEEN member, so a cluster spans at most a few lines around its anchor; an exact coordinate twin of ANY member joins it, and the greedy single pass means input order decides which finding anchors which cluster.
   Which RECORD survives: the record that actually holds a `thread_id` →
   **Copilot** source → more severe verdict → longer/more specific summary →
   first-seen. The survivor's `verdict` is then promoted to the more severe of
   the collapsed pair — never downgraded. The dropped id lands in `merged_from`.
7. **Conflict-defer** — `state, kept, terminal = _apply_conflicts(state,
   classified, now)` on that deduped union. If every structural comment conflicted,
   terminal `awaiting-human-review` with note `[all-conflicting-deferred-to-human]`.
8. **Compute round verdict** — derive `last_verdict` from the kept set:
   `structural-present` if any kept comment has `verdict="structural"`,
   else `minor-only`. The **classifier-flip** from `structural-present` to
   `minor-only` is a **necessary precondition** for success, **not a terminal
   on its own**. Never transition to `awaiting-human-review` on the flip alone —
   success is decided only by **two-stable** (step 10b), which additionally
   requires zero unresolved actionable threads verified against GitHub. A flip on
   a stale snapshot with threads still open is the convergence bug this rule
   exists to prevent.
9. **Inline fix** — when `--dry-run` is OFF and the round has blocking findings, the round
   tail applies the inline-fix contract of `round-topology.md` (no `/tp-pr-fix` sub-agent,
   no worktree isolation): it asserts the checkout is on `head_ref` at `head_reviewed`,
   edits, derives `paths` mechanically, then calls `fix_round.run_round(design, pr_url,
   iteration, classified=kept, head_ref=head_ref, loop_mode=True, paths=<derived>)`, which
   commits only those paths. `head_ref` is resolved **once at loop-open** via `gh pr view
   <pr_url> --json headRefName` (F1: the fix must land on the actual PR head).
9.5. **Re-request Copilot review + Reply-and-resolve every Copilot thread (load-bearing, Enhancement 1).**
    Per-round Copilot re-request is handled by `_request_copilot_review(pr_url)` (fail-open;
    a non-zero return or raised exception returns False and the loop continues). The loop
    sets phase `awaiting-copilot` around the subsequent CI/Copilot wait (see
    `_ci_settled_on_head`). After the wait, the loop proceeds to classify.

    Reply-and-resolve every Copilot thread:
    The reply ALWAYS precedes the resolve — the loop never resolves a thread
    without first leaving the evidence reply. Call the shared helper:
    ```python
    # thread_dispose resolved via sys.path.insert(0, "$TP_ROOT/skills/_shared")
    result = thread_dispose.dispose_threads(
        pr_url,
        envelope,
        resolved_ids=state.resolved_thread_ids,
        author=pr_author,
    )
    state.resolved_thread_ids.update(result["resolved"])
    ```

    `thread_dispose.dispose_threads` (from `skills/_shared/thread_dispose.py`)
    owns the single source of truth for the reply-and-resolve sequence: it
    calls `thread_resolver.disposition_for` for every open thread (never
    hand-judges), signs replies with the worker identity
    (`🤖 three-pillars-worker (on behalf of @{author})`), calls
    `reply_to_thread` before `resolve_thread` for each thread, and is
    idempotent (skip already-resolved; skip already-replied). The same
    helper is called by `--dispose-only` mode out-of-band.

    Disposition is `addressed` (links the fixing commit), `stale` (cites the
    prior-round resolution as evidence), or `deferred` (reason). Copilot
    re-posts comments anchored to unchanged diff lines every round; without
    reply-and-resolve the loop re-litigates already-fixed items forever and
    the new-vs-stale signal is unusable. Resolve uses GraphQL
    `resolveReviewThread` — never `gh pr edit` (broken on this repo). Track
    every observed `thread_id` in `state.seen_thread_ids` and every resolved
    one in `state.resolved_thread_ids`.

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
10. **Round budget** — `run_round` calls `round_budget.tick` before two-stable. A terminal
    (`budget-exhausted` | `cap-exhausted` | `convergence-failure`) gets the F9 label.
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
    this head): transition `blocked-no-independent-review`, apply `tp:needs-human-attention`
    **and remove any stale `tp:ready-for-human-merge`** (terminal label hygiene — a prior
    convergence's label must not mask a later blocked head), append the
    `BLOCKED — NEEDS REVIEW — no proof (no independent review ran)` line to `decisions.md`. This is a
    **terminal** — `run_round` returns `terminal="blocked-no-independent-review"` and
    the loop stops; `tp:needs-human-attention` escalates for human follow-up (never apply
    `tp:ready-for-human-merge` here). Bounded re-run / not-converged: see `proof-of-review.md`.

    When all four hold: transition `awaiting-human-review` with `termination_reason="two-stable"`,
    apply `tp:ready-for-human-merge` (via `_ensure_pr_label`) **and remove the sticky
    `tp:needs-human-attention`** (`label_manager.remove_pr_label`, probe-first REST — it is
    also applied on recoverable paths and nothing else clears it; without this a
    recovered-then-converged run reads as fleet trouble), append the `[pr-readiness/terminal]`
    line to `decisions.md`. The loop is **fail-open** on the readiness check: a
    missing/erroring `reviewed_fn` is UNVERIFIABLE → keep iterating to a cap/idle terminal.

    **Copilot-optional terminal (`review.expects_copilot`).** The Copilot conjunct
    (`reviewed is True`) is required **only when Copilot is an available reviewer** —
    `_expects_copilot_review(config)`, reading `review.expects_copilot` from
    `.three-pillars/config.json` (default true). When it is **false** (structural
    entitlement absence), the Copilot disjunct of `_independent_review_ran` is dead, so
    `review_available` alone carries the fourth conjunct — the dual-source `/code-review`
    arm is the load-bearing reviewer. The transition note is `two-stable [code-review-only]`;
    `termination_reason` stays `"two-stable"`; the canonical clean-round finish is
    `scripts/converge.py` (ordered: post proof digest → shell `run_round.py`). expects_copilot true is unchanged.

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

### Cold-resume contract — iterate-state.v1.json

The state is written at **every round boundary**, but calling it a resume record overstates what the shipped callers do with it: it is closer to a **per-round scratchpad plus a converge-time handoff**. `converge.py::_seed_state` **re-seeds** the same path on every clean-round finish, keeping only the budget fields (`iteration`, `started_at`, `original_diff_lines`, `budget_*`), so `transitions`, `resolved_thread_ids` and `seen_thread_ids` are dropped rather than resumed. (**Not** `reviewed_head_shas`: nothing on the shipped `run_round` path writes it, so it is always empty and the re-seed drops nothing.) A resumed loop does read the file back, which is what makes a crash *between* rounds recoverable on the Tier-7 path — but do not assume history accumulates across a converge.
**Round 0 bootstraps on absence** (`scripts/iterate_state.py::load_or_bootstrap`, called from `run_round.py`): an absent state file is the documented
**start condition**, not an error — the round writes a schema-valid round-0 state, reports `state_bootstrapped: true`, and exits 0. So no round boundary is
ever un-resumable and no operator hand-seeds a schema-valid file. The bootstrap **never overwrites** an existing file that has **content** it refuses — those
bytes are the forensic record and are left byte-identical (but see the limit of that promise below). A **zero-length** file is the sole exception: it counts as *absent* and is re-seeded, because it is what a crash between the seed's
exclusive-create and its `os.replace` leaves behind, it has no bytes worth preserving, and refusing it would wedge every later round with nothing able to repair it. A **non-regular** node at `state_path` (FIFO, socket, directory, `/dev/null`) is **refused**, never replaced: `state-read-failed` / exit 2 — the zero-length carve-out is confined to regular files precisely so it cannot clobber one. The refusal is **unqualified because the guard resolves symlinks — the whole chain, not one hop**: a link to a FIFO used to reach `read_text()` and block the round forever (no envelope, no exit code), so `_reject_non_regular` checks what `state_path` *resolves to*, not just the link. `link → link → FIFO` is refused exactly like `link → FIFO`; do not narrow the guard to a single `readlink` to match a "one level" description, or the chain case reopens the hang. The per-round write-back goes through `os.replace`, which rebinds the name to a fresh inode: the state file's **mode, ownership and ACLs are not preserved and its hardlinks are broken**. A `0444` state file used to make the round exit 2 and now comes back `0664` — a read-only state is **not** a write barrier, which is the price of crash-atomicity (a failed truncating write left a short file, wedging every later round against never-overwrite). All of this assumes a **serial** caller — `run_round.py` is shelled out one round at a time — and two bootstraps racing on ONE `state_path` are **not supported**: a claim still in flight is also 0 bytes, so a racing round cannot tell it from crash residue, re-seeds it, and the last `os.replace` wins. What is silently lost is the losing round's accumulated state — `transitions`, `last_codereview_head_sha` / `last_codereview_findings` (the currency fields `_independent_review_ran` reads) and `degraded_review_retries`. So is `iteration`, since the budget tick increments it every counted round: `round_budget.tick` enforces `round_cap` from it (`budget-exhausted`), so a lost race also loses rounds from the cap. Give each parallel loop its own `state_path`.
**`state-read-failed` (exit 2) is the *unreadable* refusal**: content that is not a JSON object, a **dangling symlink** (`Path.exists()` says absent, but the seed still refuses to write through the link), or a **non-regular** node (including one reached through a symlink). "Exists with content" is the wrong test in both directions — a FIFO, socket, directory and `/dev/null` all exist with *no* content and still exit 2. It
deliberately does **not** cover schema-invalidity: `loop_driver.py` writes `consecutive_codereview_structural_rounds`, a key the shipped schema's
`additionalProperties: false` rejects, so a real round-2 state is already schema-invalid and read-path validation would refuse every round after the first. **What a schema-invalid-but-parseable state does instead is *run*** — measured: the round proceeds to a normal `status: "ok"` envelope at exit 0 and the write-back overwrites the file. It does not escalate under some other token; it is not refused at all. Correspondingly, the never-overwrite promise is a property of the **refusal**, not of the file: what `load_or_bootstrap` rejects it leaves byte-identical, and what it accepts the round overwrites.

**Where the state lives — and the honest limit.** `run_round.py`'s `state_path` is a **flat** iterate-state.v1 document; its only home is `.three-pillars/review-proof/iterate-state.v1.json`, the untracked convergence seed (`converge.py::_seed_state`, also `converge.py`'s default).
**Never point `state_path` at `<worktree>/.three-pillars/run/state.json`** — that is the **merged-namespace** worktree-state document (step 11) owned by `state_io.py::write_state_atomic`, where iterate state nests under an `iterate` key beside `supervisor` and `state.v1.json` requires `schema_version` + `supervisor` with `additionalProperties: false`. Neither direction errors: absent, the bootstrap seeds a flat round-0 doc with no `supervisor`; present, the merged doc passes the read's `isinstance(dict)` check and the write-back replaces it with flat keys the schema forbids. A wrong `state_path` is a silent wrong result, not a refusal.
Both paths are **gitignored** (the `.gitignore` patterns `.three-pillars/run/` and `.three-pillars/review-proof/`) and **no code path commits** either — resume survives a process crash **inside a live worktree** but **not** a **fresh clone**, which starts cold and bootstraps round 0 again. A *committed* per-round state is the **intended** contract, **not** one any current code path performs.

### Termination matrix

| Phase                              | Triggered by                                                 | F9 label? |
| ---------------------------------- | ------------------------------------------------------------ | --------- |
| `awaiting-human-review`            | **two-stable** (success: both sources quiet + GitHub shows zero unresolved actionable threads) / idle-timeout (time-based yield — no ground-truth check) / human-push / all-conflicting | no        |
| `blocked-no-independent-review`    | conjuncts 1–3 hold but no independent review ran for the current head (`_independent_review_ran` False) — terminal, not a keep-looping yield | yes       |
| `budget-exhausted`                 | `round-cap` (blocking findings at `iteration >= round_cap`) / `growth-lines` / `test-code-ratio` / `budget-error` — raise the limit in config and re-run (`round-topology.md`) | yes |
| `cap-exhausted`                    | `wall-clock` (`now - started_at > wall_clock_sec`)            | yes       |
| `convergence-failure`              | `k-consecutive` blocking review rounds                         | yes       |
| `errored`                          | unhandled exception in the loop body                          | yes       |

The `termination_reason` field records which trigger fired. **Two-stable is the
only success terminal** — a round where `/code-review` returns `[]`, every Copilot
thread is freshly resolved, AND a ground-truth `list_review_threads` re-fetch shows
zero unresolved actionable threads. One clean round converges: a second clean round is not
required. Classifier-flip is a necessary precondition
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

## --dispose-only mode

Calls `thread_dispose.dispose_threads` **once** and exits immediately — no
backoff, no poll loop, no fix-round dispatch, no iteration. The result
(replied / resolved / skipped thread ids) is emitted as a JSON envelope on
stdout and the process exits 0 on success, 2 on error.

Wire via `dispose_only=true` in the `run_round.py` stdin JSON payload:

```json
{
  "dispose_only": true,
  "pr_url": "https://github.com/owner/repo/pull/N",
  "state": {...}
}
```

Use this for out-of-band disposition — e.g. after a manual head-SHA bump,
after Copilot re-fires outside a loop run, or when review threads arrive
between loop iterations. The in-loop path (step 9.5) and the out-of-band
path both call the same `thread_dispose.dispose_threads` primitive (single
source of truth).

## Architectural constraints (C1)

- **No `import anthropic` in `classifier_judge.py`.** Asserted by Task 5.8's
  `ast.parse` walk. The Sonnet invocation lives in this prose via `Agent()`.
- **No `subprocess.run(["claude", ...])` in helpers.** Same rule, same
  reason. If the loop body needs the model, the call is made here and
  the result is parsed by `parse_response`.
- **One commit per round at most.** Owned by `fix_round.run_round`, not
  this driver. The loop driver never calls `git commit` itself (the `two-stable`
  `decisions.md` flush commit is the orchestrator's; `round-topology.md`).
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

Three GitHub-side quirks bite the loop's poll / classify / reply-resolve / re-request flow (steps 2 / 2.5 / 9.5 + the per-round re-request), all
observed 2026-06-04 across PRs #45/#46. Get one wrong and the round silently misreads Copilot's signal.

- **The Copilot login differs by surface — a single hard-coded filter yields false zeros.** `requested_reviewers[].login` and each inline finding
  comment (REST `pulls/<PR>/comments`) → **`Copilot`**; the **review** object author (REST `pulls/<PR>/reviews`) → **`copilot-pull-request-reviewer[bot]`**;
  GraphQL `reviewThreads…author.login` → **`copilot-pull-request-reviewer`** (suffix-less). So filtering reviews by `Copilot`, or comments by
  `copilot-pull-request-reviewer[bot]`, **matches nothing** — a *successful* review reads as "0 findings" (a **false zero**) and the loop wrongly flips to
  `minor-only`. Match the **right** login per surface. For the trusted-bot identity check don't re-list logins here: defer to the canonical allowlist
  `_TRUSTED_REVIEWER_BOTS` in `tp-pr-fix/scripts/fix_round.py` (lowercase-matched; extend per-repo via `TP_PR_FIX_TRUSTED_BOTS`) — treat any such set as
  **a superset to match against, never exhaustive**; it omits the suffix-less GraphQL spelling. Cross-check the review body's "generated N comment(s)"
  against your comment filter: N>0 with zero matches means the filter login is wrong.

- **"Copilot encountered an error" is usually a GitHub-side build crash, not your diff — never classify it, never terminate on it.** Copilot can post a
  `COMMENTED` review whose body is *"Copilot encountered an error and was unable to review this pull request"* with **zero** comments. Observed root cause:
  `ERR_MODULE_NOT_FOUND: detect-libc` in GitHub's `@github/copilot` CLI (the npm optional-dependency bug on their runner) — it crashes at **startup, before
  reading the diff**, so it fails *identically on every PR/SHA* and is content-independent (do **not** edit your diff to appease it; read the review job log
  first). It is **transient** and clears server-side. Treat an error-body review as **no signal**: skip it in classification, lean on the dual-source
  `/code-review` arm for the round (precisely why the loop is dual-source — single-source Copilot is not load-bearing), and re-request only on the next
  pushed SHA or once it clears (a *same-SHA* retry is deduped — next bullet).

- **A re-request only re-fires on a NEW head SHA.** Re-POSTing `requested_reviewers` with the Copilot bot on an **unchanged** head SHA that already carries
  a Copilot review (even an error one) is **deduped** by GitHub — no new run. A genuine re-review fires on a **new commit** (new head SHA) or once a
  transient error clears. Consequence: the per-round re-request *after a `tp-pr-fix` commit* works (the fix advanced the SHA); a same-SHA retry of a
  transient *error* usually will not — wait for recovery or push a commit.

## See also

- `_shared/classifier_heuristic.py` — pure-deterministic prefilter (Phase 4).
- `tp-pr-iterate/scripts/classifier_judge.py` — prompt + parse helper.
- `tp-pr-iterate/scripts/review_merge.py` (+ sibling `review_merge_dedupe.py`, re-exported) — normalize + dedupe the dual review sources (Enhancement 1).
- `skills/_shared/thread_resolver.py` — reply-and-resolve Copilot threads (Enhancement 1; moved to `_shared/` so free modules can import it without a cross-skill boundary).
- `tp-pr-iterate/scripts/loop_driver.py` — helpers + entry point (incl. `_two_stable_terminal`).
- `tp-pr-iterate/schemas/iterate-state.v1.json` — loop-state schema.
- `tp-pr-iterate/schemas/normalized-finding.v1.json` — dual-source finding schema (Enhancement 1).
- `.github/review-instructions.md` — shared review guidance both reviewers consume (Enhancement 1).
- `tp-pr-iterate/schemas/classified-comment.v1.json` — per-comment verdict schema.
- `tp-pr-fix/SKILL.md` — the single-round worker this loop dispatches to.
- `tp-merge-from-main/SKILL.md` — the base-into-branch conflict resolver to invoke when the PR goes `DIRTY`/`BEHIND` mid-loop (never hand-merge). (The `/tp-merge` land gate is separate — landing the PR is the human's.)
- `tp-pr-fix/scripts/fix_round.py` — deterministic identity-gate + commit + push + label helper. (Owns no iterate-state; `last_loop_sha` write-back is the loop driver's job — see above.)
- Proof-of-review per-round contract: see `tp-pr-iterate/proof-of-review.md`.
