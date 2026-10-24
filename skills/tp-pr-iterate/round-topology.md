# tp-pr-iterate — Round topology (reference)

design: iterate-convergence-budget (Task 8.1)

How one review round of the `/tp-pr-iterate` loop runs: who writes where, in what order, and how
each failure is recovered. `SKILL.md` §Loop body and `tp-run-full-design/tier-7-review.md` Tier 7 Step 1
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
model, a duplicate name, a confirmer that is not on Claude, and any Claude angle below the review
floor (`models.review`, else `opus`) — never an inherited default. Every Claude angle is dispatched
with its manifest `dispatch_model` (Opus by default; `models.review` to change; see
`model_policy.py`); a local finder with no backend is skipped (`[skipped: no local backend]` in
the digest).

`build_prompt` embeds the diff range, the `--effort` level, the review bar verbatim, the finding
shape `{file, line_range, summary, class, blocking, reproducer?}` and the angle's reply path. A
finding is **blocking** only when it carries a valid reproducer (a pytest `source`, or a command
`argv` with an `expect`). A clean `[]` round signs the proof only if at least one **confirmer**
angle on Claude left a parseable reply (`confirmer_ran`); a finder-only `[]` never converges.

A finding is **admissible** only with a failing input and the spec clause it breaks — except a
fragile test or check the PR itself adds, which is a structural finding on its own (see
`../_shared/test-fragility.md`). Each finding also carries `origin` and `fragility_class`
(the enums live in `../_shared/finding_fields.py`'s `ORIGINS` / `FRAGILITY_CLASSES`), normalized
via `finding_fields.normalize` so an unrecognized or absent value reads as `unclassified`, never
a guess.

## Classifier judge

Step 5 of `SKILL.md` invokes the borderline-comment classifier via `Agent()` in prose rather than
inside `classifier_judge.py`, because `classifier_judge` is a C1 helper: it constructs the prompt
and validates the response against `classified-comment.v1.json`, and **has no `import anthropic`**
(asserted by Task 5.8's `ast.parse` invariant test). The model invocation is the one step that
must live outside a helper — in this prose — never in `classifier_judge.py` itself.

## Path authority

The orchestrator resolves the loop's paths **once**, in its own pinned `tp/{slug}` checkout, as
absolute paths under the proof root that `python3 <scripts>/proof_root.py` prints
(`proof_root.default_proof_root()`, which `review_proof.default_proof_root()` delegates to):
`<absolute git-dir>/three-pillars/review-proof`, the worktree's own git-dir, so the root sits
**outside the working tree** (a linked worktree's git-dir is `<main>/.git/worktrees/<name>`) and
never under `/tmp`. `review.proof_dir` (relative to the worktree root) or the uncommitted
`TP_REVIEW_PROOF_DIR` (absolute) overrides it, and the first call moves a legacy in-tree
`.three-pillars/review-proof/` there once (a symlink's target is copied and kept). Scripts do all
proof-root I/O: nobody uses a file tool (Read/Write/Edit) on a proof-root path. The orchestrator
reads `R/angles.json` and the tail reads `R/tail/findings.json` through Bash (`cat`, or the
script that consumes the file), never the Read tool. A round that spans the upgrade still points
at the old location, so its `tail-check` fails closed and the next round prepares again. The
root holds:

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
(`<angle>/reply.md`) and `tail/`. Each angle delivers only its own reply, by piping it through
Bash into the quoted-heredoc `round_scratch.py put --round-dir R --slot <angle>` command its
prompt names (never the Write tool), and touches nothing else. `put` computes the target itself
and refuses an unlisted or skipped slot, a symlink and any escape from `R`. A missing or empty
reply reads as an unparseable sentinel, so a clobbered sibling blocks (fail-closed) and never
reads as clean.

Each angle also gets a per-angle `exec_dir`, a temp dir outside the proof root and the checkout.
`reproduce.py` deletes it once the replies are merged, before the clean-round scratch check;
`tail-check` deletes any that is left.

The round number `N` is derived from the dirs on disk (cold-resume safe), never from memory, and a
dir is never reused. When the previous round's tail said `rerun-review`, `prepare` creates `r<N>.1`;
a second re-run of the same round refuses (`rerun-limit`, `needs-human-attention`). `N` is the
dispatch ordinal, not the budget iteration. Only the orchestrator deletes round dirs
(`round_scratch.py remove --target <r<N>> --owner <rounds/<pr>>`, which refuses anything outside
its owner), and only after `two-stable`: kept dirs let a re-run derive a fresh ordinal.

## One round

0. **Context scout** (before round 1; re-run when `context_scout.py needs-refresh` exits 0): `strata-finders.md` §Context scout leaves `rulings.md` in `<proof_root>/rounds/<pr>/`.
1. **Orchestrator.** Re-fetch the base every round (`git fetch origin <base-branch>`; `base` is the
   `origin/<base-branch>` tip, so a mid-loop `/tp-merge-from-main` moves the merge-base with it).
   Run `round_scratch.py prepare --proof-root <proof_root> --pr-url <url> --base <base> --head <head>
   --review-weight <W> --state <state_path> --log <log_path> --rulings <proof_root>/rounds/<pr>/rulings.md`; it prints the round dir `R`. `<W>` is `weight_class.py review-weight <design_dir>` (`convergence-rules.md` §D5).
   `cheap-tier.md` §Pre-round runs first (then `prepare` takes `--prep-dir W`), §Scaffold runs after step 2, and §Tail lines adds its lines to the step 3 prompt.
2. **Orchestrator: angle fan-out.** Dispatch every manifest angle as a top-level
   review sub-agent spawned as `subagent_type=<agent_ref>` (round 1 `tp-review-confirmer-deep`,
   later rounds `tp-review-confirmer`: `angles.review_agent`; on a `local` angle `angles.entry_agent`
   gives `tp-review-confirmer-medium`) with `model=<dispatch_model>` from the manifest, with the
   manifest `prompt`. A local finder angle dispatches that `agent_ref` directly, with no
   `dispatch_select.py floor` step: the review floor would swap the `-medium` agent back to the
   base at `high`. Skipped angles are
   not dispatched. Angles test and mutate only in their manifest `tree_dir` copy, never the shared worktree. Each pipes exactly one `{"findings": [...]}` JSON object into its prompt's
   `put` command (it lands at its
   `reply_path`; `strict_json_reply`: anything else reads as the unparseable sentinel) and
   returns one line; the orchestrator keeps only that line. The angle set comes from
   `finder_round.round_angles`. On the cheap engine the finders run Sonnet in parallel, Strata one at a time
   (`strata-finders.md`); dispatch the `opus-check` angle last, after every finder `reply.md` exists.
3. **Round tail.** One sub-agent (Opus), run **without worktree isolation**, in the
   orchestrator's own `tp/{slug}` checkout, while the orchestrator is idle. The round tail is the
   one working-tree writer of the loop. It never checks out another branch, and it commits only the
   derived fix paths. On the cheap engine the `opus-check` (Opus check) angle runs last,
   before this tail (`strata-finders.md`). It:
   1. runs `reproduce.py --round-dir R --cwd . --head <head_reviewed>`, adding
      `--dispositions <design_dir>/audit-dispositions.json` when that file exists
      (`convergence-rules.md` §D4). It refuses (exit 2) unless
      `HEAD` equals `head_reviewed` and tracked code is clean (untracked files, `three-pillars-docs/**`
      and `.three-pillars/config.json` are ignored). `reproduce.py` writes `R/tail/findings.json` and
      appends downgrade and note lines to the manifest's `log_path`;
   2. on a clean round (`blocking == 0` and `degraded == 0`) runs `converge.py --round-dir R
      --config .three-pillars/config.json --class-log-path <log>`. That captures and posts the proof
      digest, then shells `run_round.py`. On exit 3 with reason `proof-author-untrusted` or
      `bot-auth-unavailable` no `run_round.py` runs: that reason becomes the terminal in the tail
      envelope (a PR already carrying a human-authored digest must re-run `converge`).
      `converge.py --round-dir` (`converge_rounddir.run`) exits 3, never 4, when its output carries a
      `finalizer_stop`; an exit 4 never carries one. The tail copies that stop into the envelope
      (the review stop: `terminal` null, `action: "rerun-review"`, so the fix gets `r<N>.1`; `noop`
      when R is already `r<N>.1`). On `exit 4` (`"terminal": "evidence-complete"`,
      `convergence-rules.md` §D8) no `run_round.py` runs: the envelope is `action: "noop"`,
      `fix_commit: null`, `terminal: "evidence-complete"`, `converged: false`, `head_after` =
      `head_reviewed`, `budget` read from `iterate-state` (`state_path`; zeros, `signal: null`,
      `holding: []` when absent), `finalizer_stop: null`, and `summary` carrying the `accept_hint`
      line verbatim;
   3. otherwise captures the proof, posts through `proof_post.py --config` with `digest_labels`, then shells
      `run_round.py` with stdin `state_path`, `head_sha`, `codereview_findings` (from
      `R/tail/findings.json`), `pr_url`, `round`, `ordinal`, `class_log_path`, `review_base` (the
      manifest `base`), `review_proof_root`, `decisions_path` (the manifest `log_path`) and
      `config`. On `action == "fix"` with blocking findings it applies the inline-fix contract below.
      A degraded-only round gets no fix: its envelope says `action: "rerun-review"`.
      A non-ok `proof_post.py` status (exit 3) is logged in the tail envelope `summary` and the
      round continues (that round cannot converge);
   4. delivers `R/tail/envelope.json` (`schemas/round-tail.v1.json`) by piping it into
      `round_scratch.py put --slot tail --round-dir R` (a quoted heredoc, never the Write tool)
      and returns it, copying `finalizer_stop` verbatim from the `run_round` / `converge` output
      (`null` when absent).
4. **Orchestrator.** `round_scratch.py tail-check --round-dir R`, which exits 2 with
   `tail-failed` when the envelope is missing or invalid. A **terminal-null** `finalizer_stop` with
   `source: question` (the review stop) goes to §Review stop and never starts the next round.
   On `rerun-review` it runs the round again
   (step 1 makes `r<N>.1`). A `round-cap` stop is first piped through
   `python3 <scripts>/round_mix.py attach --stop-file <stop> --rounds-dir <proof_root>/rounds/<pr>`
   (adds `mix` when the last two rounds share a regression/class-in-area signal), and the output stop
   is what `finalizer_cli.py prepare --stop` receives. On a terminal with a non-null `finalizer_stop` (a newly fired budget
   terminal, which `run_round` did not label) it runs the finalizer first: `finalizer_cli.py prepare
   --stop <that object>` → `tp-finalizer` → `apply` (`skills/_shared/finalizer-first.md`). `resolved`
   records one grant and the round re-runs; `escalate` posts the diagnosis, then the
   `tp:needs-human-attention` label. On `evidence-complete` it posts the envelope's `accept_hint`
   line (from `summary`) as **one PR comment** (`forge.comment_post`), then flushes the log (below)
   and stops; it never starts another round. On any other terminal it flushes the log (below) and
   stops. Otherwise it starts the next round.

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
  head_ref=<PR head branch>, loop_mode=True, paths=<derived paths>, frozen=<frozen>)`. `<frozen>` is
  `True` when `round_freeze.py is-frozen --state-path <state_path>` exits 0, else `False`. That runs the identity gate,
  commits `[tp-pr-fix iter-N]` staging **only** those paths (never `git add -A` in the shared tree),
  pushes, and sets the labels.
- **Under a `CHEAP_TIER:` line** (`cheap-tier.md` §Tail lines) the tail may adopt listed scaffolds, and, because it cannot spawn, it runs today's step 5 and appends `[cheap-tier] pr_fix_reproducer: round tail cannot spawn; today's generation` to `log_path` once per fix round, only when that `CHEAP_TIER:` line is present.

## Log flush

At every loop terminal (`two-stable`, `budget-exhausted`, `cap-exhausted`, `needs-human-attention`,
and the operator stop) the orchestrator runs `round_scratch.py flush --log <log_path> --decisions
<design>/decisions.md --root <proof_root> --pr-url <url>`. That appends the loop log (class,
downgrade and `[tp-pr-iterate/note]` lines) plus its own outcome line to `decisions.md`, truncates
the log, closes the latest round (`tail/closed.json`) and prunes `rounds/<pr>` to the proof files, keeping the latest round's `tail/findings.json` (a scoped next-round prepare reads it).
At `two-stable` the `--decisions` path is the archived log,
`three-pillars-docs/completed-tp-designs/<slug>/decisions.md` (the Tier 5.6 archive).
The operator stop runs `round_scratch.py stop --log <log_path> --decisions <design>/decisions.md
--pr-url <url>` (root defaulting to what `python3 <scripts>/proof_root.py` prints). A round is open
until its terminal (read from the tail envelope's `terminal` or the `closed.json` marker, never
mtime), and no reap (strip, prune, size-check) touches an open round. A round manifest that still
names a pre-migration root is repointed to the root it lives in before any reap.

- At `two-stable` the flush is **committed and pushed only at `two-stable`**, staging only the
  round-log paths: `decisions.md` and, when they changed, the archived design's
  `dispatch-telemetry.ndjson` and `escape-ledger.ndjson` (rows the dispatcher logged after the
  Tier 5.6 archive: `dispatch_log.py` follows `tp-designs/<slug>` to `completed-tp-designs/<slug>`) and the run's ruling files (`three-pillars-docs/escalations/rulings/`, `escalation.md` §Commit points).
  First run `python3 "$TP_ROOT"/skills/_shared/pr_push_check.py --repo . --pr-url <url>`; exit 1 leaves the commit local and the terminal report names its SHA for the seat.
  The orchestrator pushes only when both checks exit 0, the second being `python3 "$TP_ROOT"/skills/_shared/round_log_carry.py check
  --repo .` (the `is_round_log_commit` verdict on `HEAD`) exits 0; 1 is rejected, 2 an error, and
  both leave the commit unpushed (fail-open: one line on a push failure). Otherwise it leaves the commit local and unpushed, as
  before, with one line saying so. The merge gate carries the review proof and the ci-local stamp
  across that commit (`skills/_shared/round_log_carry.py`), and the Copilot check treats the log
  delta as review-exempt, so the push does not stale the converged review.
- At every other terminal, `decisions.md` is left **modified and uncommitted**, and the terminal
  report says so. `HEAD` stays the PR head, so a re-run starts from the reviewed SHA
  (`reproduce.py` ignores `three-pillars-docs`, and fix commits stage only their own paths).

## Base-sync carry check

A mid-loop `/tp-merge-from-main` push moves the base under the reviewed head. Before anything else
the loop runs `python3 "$TP_ROOT"/skills/_shared/carry_check.py --repo . --pr-url <url>` — that is
**before the next round is prepared** and **before any `round_scratch.py flush` commit**, so a
log-flush commit is never stacked on the sync merge ahead of the check.

- Exit 0 (**carried**): no re-review. The loop goes straight to the converge oracle on the synced
  head. A docs-only sync is carried (`merge_carry.py`); one that hand-resolves code or skill text
  is not.
- Exit 1 (**not carried**): the next round is a delta round from the pre-sync reviewed head
  (`convergence-rules.md` §D3), never a full re-review.
- Exit 2 is an error, not a verdict: the loop stops and reports it.

## Budget terminals and recovery

`run_round` calls `round_budget.tick` every round. A counted round with blocking findings at
`iteration >= round_cap` stops as `budget-exhausted` / `round-cap`. The cap stops **fix** rounds,
never a verify round. The other signals are `growth-lines`, `test-code-ratio` (`budget-exhausted`),
`wall-clock` (`cap-exhausted`), `k-consecutive` (`convergence-failure`) and `budget-error`. The
envelope `budget.holding` lists every signal firing now, so the operator can raise every limit in
one pass. The Tier-7 outcome is `pr-iterate-budget-exhausted`.

- **Raise the limit.** A newly fired terminal goes to the finalizer first (step 4 above), whose
  `resolved` records one grant (`budget_extensions`). Past that, edit `pdw.guards.round_cap` (or the named limit)
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

## Review stop

design: seat-escalate-first. A two-stable converge with non-blocking notes left returns one terminal-null
`question`/`decision` `finalizer_stop` ("stop here, or fix these notes first?") before any label. The
decision is per PR and per set of notes: there is no blanket policy (no config key, no brief line).
At top level, route it through `skills/_shared/escalation.md` §Run with `--scope <slug>`:
`finalizer_cli prepare/apply --scope <slug> --entry run`. Then settle the ruling it wrote (`<rid>` is its id):

```bash
python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/review_stop.py settle --id <rid> --state <state_path> \
  --decisions <decisions.md> --config .three-pillars/config.json
```

- **`label`**: re-run `converge.py` on the same head and ordinal (a re-shell, no round spent). Its second proof digest is accepted: `post_proof_checked` has no dedupe.
- **`fix`**: `round_scratch.py prepare` (step 1, with its `--rulings`) makes the fix's own sub-round `r<N>.1` (dirs are never reused; `r<N+1>` when R is already one). Its tail runs only the inline-fix contract with `classified=<settle notes>` (structural-tagged: committed whatever `frozen` reads) and `fix_round` iteration = `review_stop.iteration` (the `[tp-pr-fix iter-N]` tag), envelope in its own tail slot. The delta round follows within the cap, and its leftover notes go through `review_stop.due()` again.
- **`card`**: `AskUserQuestion` with settle's `question`/`options` (its `ruling: <id>` line passes the hook), then `ruling_cli.py answer --id <rid> --choice <label>`, then `settle` again. A `TP_DESIGN_RUN=1` run opens no card: it takes the `escalation.md` §3 wait path (`ruling_cli.py wait`), then runs `settle` again with the waited label (for `answer-in-text`, with the text on the second line).
- **`escalate`**: `finalizer_cli.py escalate --reason unmappable-choice --scope <slug>`, then `settle --id <the `ruling_id` it printed>` (a NEW ruling; it returns the `card`).
- **`halt`**: flush the log, label `tp:needs-human-attention`, stop.

`prepare` refused `already-finalized` (the same notes recurring): `finalizer_cli.py escalate --reason already-finalized --scope <slug>`, then `settle --id <the `ruling_id` it printed>`.
