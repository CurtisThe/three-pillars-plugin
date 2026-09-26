# tp-pr-iterate — Round topology (reference)

design: iterate-convergence-budget (Task 8.1)

How one review round of the `/tp-pr-iterate` loop runs: who writes where, in what order, and how
each failure is recovered. `SKILL.md` §Loop body and `tp-run-full-design/SKILL.md` Tier 7 Step 1
point here instead of repeating it. Scripts live in `skills/tp-pr-iterate/scripts/` unless noted.

**The review bar, verbatim (every angle prompt, `.github/review-instructions.md`):** "Only a
demonstrated shipped-behaviour defect with a reproducer blocks; mutation survivors, test-tightening,
exotic env, lint-guard bypasses, style and perf are non-blocking notes." A lint or heuristic-guard
bypass counts as a defect only when a real call site in the repo shows it.

## Angles as data

The review angles are data, not prose. `angles.py` holds `DEFAULT_ANGLES`: three angles
(`correctness-leak`, `edge-cases`, `test-quality`), each `{name, prompt, role: "confirmer", model:
"opus"}`. A repo can declare its own set under `review.angles` in `.three-pillars/config.json`
(`{name, prompt, role: finder|confirmer, model}`). `load_angles` refuses a bad role, an empty name or
model, a duplicate name, a confirmer that is not on Claude, and any Sonnet or Haiku model: reviews
are **always Opus**, never Sonnet and never an inherited default. Every Claude angle is dispatched
with `model="opus"`.

`build_prompt` embeds the diff range, the `--effort` level, the review bar verbatim, the finding
shape `{file, line_range, summary, class, blocking, reproducer?}` and the angle's reply path. A
finding is **blocking** only when it carries a valid reproducer (a pytest `source`, or a command
`argv` with an `expect`). A clean `[]` round signs the proof only if at least one **confirmer**
angle on Claude left a parseable reply (`confirmer_ran`); a finder-only `[]` never converges.

## Path authority

The orchestrator resolves the loop's paths **once**, in its own pinned `tp/{slug}` checkout, as
absolute paths under `review_proof.default_proof_root()` (gitignored, never `/tmp`):

- the state `iterate-state.<pr>.v1.json`,
- the loop log `iterate-log.<pr>.md`,
- the round tree `rounds/<pr>/`.

`round_scratch.py prepare` writes them into each round's `angles.json` manifest as `paths:
{proof_root, state_path, log_path}`, together with `pr_url`, `round`, `ordinal`, `base`, `head`,
`effort` and one entry per angle (name, role, model, tier, reply_path, prompt). The manifest is the
**path authority** for the round: `reproduce.py --round-dir` and `converge.py --round-dir` read
paths only from it, never from cwd or `default_proof_root()`. A `--state` that resolves elsewhere
is refused (`state-path-mismatch`, exit 2). When `round > 1` and the state file is absent, both
`converge.py --round-dir` and `run_round.py` exit 2 with `state-bootstrapped-mid-loop`, so a lost
state stops the loop instead of resetting the cap.

## Scratch: per-round and per-angle

Every round gets a fresh **per-round** dir `rounds/<pr>/r<N>/`, with one **per-angle** subdir
(`<angle>/reply.md`) and `tail/`. Each angle writes only its own reply path and touches nothing
else. A missing or empty reply reads as an unparseable sentinel, so a clobbered sibling blocks
(fail-closed) and never reads as clean.

The round number `N` is derived from the dirs on disk (cold-resume safe), never from memory, and a
dir is never reused. When the previous round's tail said `rerun-review`, `prepare` creates `r<N>.1`;
a second re-run of the same round refuses (`rerun-limit`, `needs-human-attention`). `N` is the
dispatch ordinal, not the budget iteration. Only the orchestrator deletes round dirs
(`round_scratch.py remove --target <r<N>> --owner <rounds/<pr>>`, which refuses anything outside
its owner), and only after `two-stable`: kept dirs let a re-run derive a fresh ordinal.

## One round

1. **Orchestrator.** Re-fetch the base every round (`git fetch origin <base-branch>`; `base` is the
   `origin/<base-branch>` tip, so a mid-loop `/tp-merge-from-main` moves the merge-base with it).
   Run `round_scratch.py prepare --root <proof_root> --pr-url <url> --base <base> --head <head>
   --state <state_path> --log <log_path>`; it prints the round dir `R`.
2. **Orchestrator: angle fan-out.** Dispatch every manifest angle in parallel as a top-level
   `general-purpose` sub-agent pinned `model="opus"`, with the manifest `prompt`. Each writes its
   full reply to its `reply_path` and returns one line; the orchestrator keeps only that line.
3. **Round tail.** One sub-agent (Opus), run **without `isolation="worktree"`**, in the
   orchestrator's own `tp/{slug}` checkout, while the orchestrator is idle. The round tail is the
   one working-tree writer of the loop. It never checks out another branch, and it commits only the
   derived fix paths. It:
   1. runs `reproduce.py --round-dir R --cwd . --head <head_reviewed>`. It refuses (exit 2) unless
      `HEAD` equals `head_reviewed` and tracked code is clean (untracked files, `three-pillars-docs/**`
      and `.three-pillars/config.json` are ignored). It writes `R/tail/findings.json` and appends
      downgrade and note lines to the manifest's `log_path`;
   2. on a clean round (`blocking == 0` and `degraded == 0`) runs `converge.py --round-dir R
      --config .three-pillars/config.json --class-log-path <log>`. That captures and posts the proof
      digest, then shells `run_round.py`;
   3. otherwise captures the proof, posts `post_codereview_comment` with `digest_labels`, then shells
      `run_round.py` with stdin `state_path`, `head_sha`, `codereview_findings` (from
      `R/tail/findings.json`), `pr_url`, `round`, `ordinal`, `class_log_path`, `review_base` (the
      manifest `base`), `review_proof_root`, `decisions_path` (the manifest `log_path`) and
      `config`. On `action == "fix"` with blocking findings it applies the inline-fix contract below.
      A degraded-only round gets no fix: its envelope says `action: "rerun-review"`;
   4. writes `R/tail/envelope.json` (`schemas/round-tail.v1.json`) and returns it.
4. **Orchestrator.** `round_scratch.py tail-check --round-dir R`, which exits 2 with
   `tail-failed` when the envelope is missing or invalid. On `rerun-review` it runs the round again
   (step 1 makes `r<N>.1`). On a terminal it flushes the log (below) and stops. Otherwise it starts
   the next round.

Nothing in the loop writes a tracked file except the fix commit. Downgrade, note, class and
readiness lines go to `log_path`, and envelopes go to `R/tail/`.

## Reproducer outcomes

`reproduce.py` runs the reproducer of each blocking finding against the reviewed head:

- **reproduced**: pytest exits 1, or the command violates its `expect`. The finding stays
  blocking.
- **not-reproduced**: the reproducer ran and passed. The finding is downgraded to a non-blocking
  note (`downgrade.reason = "not-reproduced"`).
- **inconclusive**: pytest exits 2–5, a timeout, or an `OSError`. The finding stays blocking and is
  noted. The runner never fails open.
- A blocking finding with no valid reproducer (the legacy shape) is downgraded with
  `schema_note = "legacy-no-reproducer"`.

Sentinels (unparseable or missing angles) are never touched. A reproducer that dirties tracked
code makes the CLI exit 2, and the round is reported degraded.

## Inline-fix contract

A round tail cannot spawn sub-agents, so it runs a reduced form of `/tp-pr-fix`:

- **Steps 3 and 4 are skipped** (the Sonnet classifier and structured extraction). The findings are
  already classified and reproducer-filtered, and they already carry `source="code-review"`,
  `verdict="structural"` and `comment_id=None`, the shape that `fix_round`'s identity gate passes.
- **Step 5 is the tail itself** (the Opus fix generator). Before editing, it asserts the current
  branch is the PR head branch and its tip equals `head_reviewed`, so `fix_round` never checks
  out. It snapshots the untracked set (`tree_scope.untracked_snapshot`), edits files directly
  (never `three-pillars-docs/**`) and does not commit.
- **`paths` is derived mechanically**: `tree_scope.derive_fix_paths(cwd, before)` returns modified
  tracked files plus untracked files new since the snapshot. Both loop excludes apply:
  `three-pillars-docs/**` and `.three-pillars/config.json`. If that set differs from the tail's own
  edited list (`tree_scope.check_fix_paths`), it commits nothing and returns terminal
  `needs-human-attention` with reason `fix-paths-mismatch`.
- It then calls `fix_round.run_round(design, pr_url, iteration, classified=<blocking findings>,
  head_ref=<PR head branch>, loop_mode=True, paths=<derived paths>)`. That runs the identity gate,
  commits `[tp-pr-fix iter-N]` staging **only** those paths (never `git add -A` in the shared tree),
  pushes, and sets the labels.

## Log flush

At every loop terminal the orchestrator runs `round_scratch.py flush --log <log_path> --decisions
<design>/decisions.md`. That appends the loop log (class, downgrade and `[tp-pr-iterate/note]`
lines) plus its own outcome line to `decisions.md` and truncates the log.

- At `two-stable` the flush is **committed only at `two-stable`**, staging only `decisions.md`,
  and **not pushed**: a push would move the PR head off the reviewed, converged SHA. This is an
  exception to commit-then-push.
- At every other terminal, `decisions.md` is left **modified and uncommitted**, and the terminal
  report says so. `HEAD` stays the PR head, so a re-run starts from the reviewed SHA
  (`reproduce.py` ignores `three-pillars-docs`, and fix commits stage only their own paths).

## Budget terminals and recovery

`run_round` calls `round_budget.tick` every round. A counted round with blocking findings at
`iteration >= round_cap` stops as `budget-exhausted` / `round-cap`. The cap stops **fix** rounds,
never a verify round. The other signals are `growth-lines`, `test-code-ratio` (`budget-exhausted`),
`wall-clock` (`cap-exhausted`), `k-consecutive` (`convergence-failure`) and `budget-error`. The
envelope `budget.holding` lists every signal firing now, so the operator can raise every limit in
one pass. The Tier-7 outcome is `pr-iterate-budget-exhausted`.

- **Raise the limit.** There is no grant command. Edit `pdw.guards.round_cap` (or the named limit)
  in `.three-pillars/config.json`, leave it uncommitted (the loop ignores the config for its
  tracked-code checks and never stages it), and re-run. The terminal is sticky: `tick` re-evaluates
  it against the current config, lifts it with a `[budget-lifted]` transition, and the same-head
  re-review counts as a completion, so its blocking findings get exactly one fix.
- **`budget-error`** is fail-closed. Repair the input and re-run. A corrupt or naive `started_at`
  is deleted from the state. A numstat failure clears once the base is fetchable. A missing
  `started_at` (legacy state) is set to `now`, which restarts the wall clock.
- **`tail-failed`.** `git restore` the tracked edits the tail left (a pushed fix commit stays and
  is the next counted head), remove the failed dir with `round_scratch.py remove`, and re-run.
- **`fix-paths-mismatch`.** Nothing was committed. Inspect the working tree, `git restore` the
  stray edits, and re-run.
