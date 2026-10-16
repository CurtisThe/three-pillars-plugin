# tp-pr-iterate cheap-tier protocol

design: cheap-tier-review-prep. `SKILL.md` points here from ## Arguments, step 2.5 and step 5, and `round-topology.md` §One round and §Inline-fix contract point here too. Every stub runs the site loop in [`skills/_shared/cheap-dispatch.md`](../_shared/cheap-dispatch.md); the slots are `REVIEW_PREP_SLOTS` in `skills/_shared/cheap_tier.py`. `W` is the prep work dir, `R` the round dir, `<mode>` is `on` (the stubs pass `--cheap-tier <mode>`; the flag is deprecated), `<head>` the PR head sha. The CLI is `"$TP_ROOT"/skills/tp-pr-iterate/scripts/review_prep_cli.py`: every subcommand prints one JSON line and exits 0 on every verdict path.

## When

- Only in the top-level loop driver (`/tp-pr-iterate` at top level, or the Tier 7 orchestrator), so every drafter is depth 1.
- The cheap tier is always on here: a slot runs when it is configured (shipped rung, or `models.<slot>`; only `"off"` opts out). One `spec` per slot per round (the stubs below). With all four prep slots null nothing here runs, no work dir is made, and the round is today's, byte for byte.
- Prep only adds labelled context. Every finding, severity, confirmation and convergence call stays on the Opus angles and the Opus round tail.

## Pre-round

Runs before step 2.5's sub-step 1 (`round_scratch.py prepare`).

1. **Spec.** The three stubs below, one `spec` each.
2. **Begin.** `python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/review_prep_cli.py begin --root <proof_root> --pr-url <url> --base <base> --head <head> --repo . --log <log_path>` prints `{work, bucket}` (`work` is `W`). A `{"skip": "head-mismatch"}` goes straight to step 6 with no `--prep-dir`, so a stale work dir is never rendered. When `ci_log_triage` is non-null, `review_prep_cli.py ci-logs --work W --pr-url <url>` fetches the failed checks' logs (fail-open; at most 3).
3. **Open.** `review_prep_cli.py open --work W --head <head> --slot <slot> --unit <unit>` per unit: `review_refs` once (unit `_`), `review_slice` per non-skipped angle in `W/meta.json` `angles` (unit = the angle name), `ci_log_triage` per `check` that `ci-logs` printed. `hit` is used at once; `skip` (budget, or a `.tp-scratch/` that is not gitignored) is logged by the CLI; `spawn` prints `facts_path`, `out_path` and `loop_id`. Every drafter path (facts, the diff or log it quotes, `out_path`) is staged in-tree under the gitignored `.tp-scratch/prep-io-<pr>/<slot>/<unit>/` (`review_prep_io.py`; `cheap-dispatch.md` Scratch), never under `W`: a drafter is project-scoped and `W` sits under the proof root.
4. **Batch.** `review_prep_cli.py batch --work W` runs immediately before each spawn batch (a fresh live-tree snapshot, D10). Then spawn every `spawn` unit in one parallel batch as `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, prompt=<read facts_path; write only out_path>)`.
5. **Settle.** When the batch returns: `review_prep_cli.py batch-end --work W --head <head> --loop-ids <id,id,…>` (every unit's budget clock stops at one instant, D4), then `review_prep_cli.py settle --work W --head <head> --slot <slot> --unit <unit> --loop-id <id>` per unit (it first copies the staged draft into `W` and removes the staged unit dir; then the live-tree guard against the batch snapshot, then `over-budget`, then an unreadable draft, then the slot oracle; `accept` lands in `W/accepted/` and the per-head cache). `dispatch_log` rows are written only after every unit of the batch has settled: one `dispatch_log.py record` row per attempt (`cheap-dispatch.md` step 4), so no telemetry row ever lands inside a snapshot-to-settle window.
6. **Prepare.** Step 2.5's `round_scratch.py prepare …` takes `--prep-dir W` only when steps 2–5 ran. It moves `W` to `R/prep/work`, renders `R/prep/<angle>.md` and adds one labelled line to each angle's prompt. The hook is fail-open (D11): a bad prep dir means today's prompts and one log line.

<!-- cheap-tier:review_refs -->
**Refs (`review_refs`; the loop is `skills/_shared/cheap-dispatch.md`).** Run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot review_refs --root . --cheap-tier <mode>`. A null rung means no refs unit; otherwise one unit `_` in steps 3–5, spawned as `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)`.
<!-- /cheap-tier -->

<!-- cheap-tier:review_slice -->
**Angle slices (`review_slice`; the loop is `skills/_shared/cheap-dispatch.md`).** Run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot review_slice --root . --cheap-tier <mode>`. A null rung means no slices; otherwise one unit per non-skipped angle in steps 3–5, spawned as `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)`.
<!-- /cheap-tier -->

<!-- cheap-tier:ci_log_triage -->
**Failed CI logs (`ci_log_triage`; the loop is `skills/_shared/cheap-dispatch.md`).** Run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot ci_log_triage --root . --cheap-tier <mode>`. A null rung also skips `ci-logs`; otherwise one unit per fetched check in steps 3–5, spawned as `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)`.
<!-- /cheap-tier -->

## Scaffold

Step 7, between step 2.5's sub-steps 2 (angle fan-out) and 3 (round tail). It runs only when `R/prep/work/meta.json` exists (the pre-round ran and `prepare` moved `W`); otherwise skip it.

Run `review_prep_cli.py scaffold-targets --round-dir R` (the findings an angle claimed blocking with no valid reproducer, at most 5); `open --work R/prep/work --head <head> --slot repro_scaffold --unit <key> --round-dir R` per target (its facts carry only the finding's `file`, `line_range`, `summary` and `class`); then the same cycle as steps 4–5 with `--work R/prep/work` and the same budget: `batch` runs immediately before the spawn batch, then `batch-end`, then `settle` per unit, and `dispatch_log` rows are written only after every unit of the batch has settled. An `accept` is a scaffold the `observed_red` oracle saw fail on head by an assertion; `settle` writes its note to `R/prep/scaffolds/<key>.json` and `index.json`.

<!-- cheap-tier:repro_scaffold -->
**Reproducer scaffolds (`repro_scaffold`; the loop is `skills/_shared/cheap-dispatch.md`).** Run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot repro_scaffold --root . --cheap-tier <mode>`. A null rung means no scaffold; otherwise one unit per target key, spawned as `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)`.
<!-- /cheap-tier -->

## Tail lines

Added to the round tail's prompt only when the `repro_scaffold` or the `pr_fix_reproducer` spec is non-null (the same spec command, with `--slot pr_fix_reproducer` for the latter). The tail is byte-identical only when both `repro_scaffold` and `pr_fix_reproducer` are set to `"off"`. These two lines, verbatim:

- `CHEAP_TIER: <mode>`
- in mode `on`, with at least one accepted note: `Labelled cheap-tier reproducer scaffolds (drafted cheap, red on head by an assertion; adopt one only after your own check): R/prep/scaffolds/index.json`

To adopt, the tail writes `R/tail/adopted.json` (`[{"key": …}]`) and runs `reproduce.py … --adopted R/tail/adopted.json`; an adopted scaffold still has to reproduce, so code never adopts on its own. Under `ab` a scaffold is checked and recorded, never listed. The tail cannot spawn, so under a `CHEAP_TIER:` line it runs today's fix generation and logs `[cheap-tier] pr_fix_reproducer: round tail cannot spawn; today's generation` once per fix round (`round-topology.md` §Inline-fix contract).

## Classifier

Before step 5's `model_policy.model_for("classifier", config)` call (`SKILL.md` step 5 points here).

<!-- cheap-tier:classifier_judge -->
**Cheap-tier classifier (always on; the loop is `skills/_shared/cheap-dispatch.md`).** Run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot classifier_judge --root . --cheap-tier <mode>`. A null rung means today's call; today every run gets one, because the rung also needs a matching verdict file and a route (`skills/tp-run-full-design/cheap-tier.md` §Reach). Otherwise spawn `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)` with the same `build_prompt` text, to write one scratch file: its raw response.
<!-- /cheap-tier -->

## Budget

- `PREP_BUDGET_SEC = 300` per round, the union of prep-loop intervals (D4), so fan-out time between pre-round and scaffold never counts and a parallel batch counts once; the pre-round and the scaffold draw on the same `W/budget.json` (it moves with `W`).
- A spent budget makes `open` print `skip` and log `[cheap-tier] prep budget spent (<n>s of 300s): skipped <slot>/<unit>`.
- `batch-end` stops every unit of a batch at one instant before any oracle runs, so one unit's oracle time never lands in another's interval; a draft whose batch returned past the budget drops as `over-budget`.
- The cache is per head (`rounds/<pr>/prep-cache`, D3): a hit is re-verified by its oracle and costs no budget; `begin` prunes other heads.

## A/B

Under `--cheap-tier=ab` the drafters still run, but the real round never sees their work (D8). Both arms that review are Opus angles.

1. **Pre-round.** Steps 1–5 of §Pre-round run as in `on`. Each drafter row is recorded with `--ab-pair` `rp-draft:<pr>:<ordinal>`, so `cheap_ab.py budget` charges it, and `cheap_ab.py report` counts it as unpaired and never rates it.
2. **Budget.** `python3 "$TP_ROOT"/skills/_shared/cheap_ab.py budget --root .`. If it prints `"exhausted": true`, the round runs as `on` and logs `[cheap-tier] ab budget exhausted: review prep ships opt-in`. `budget` skips `ab_arm: base` rows (the real angle runs anyway), so only the drafters and the shadow arm draw on the 8M cap.
3. **Prepare.** Step 2.5's `prepare` (`round_scratch.py prepare …`) runs without `--prep-dir`: the real round is today's, byte for byte.
4. **Shadow.** `python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/review_prep_cli.py shadow --round-dir R --work W --specs <S.json>` (`S.json` maps each prep slot to its `spec` output) moves `W` to `R/prep/work` and writes `R/prep/shadow/angles.json`. Per non-skipped angle it renders one slot's prep (the slot with the fewest complete `rp:` pairs for that angle, ties in `REVIEW_PREP_SLOTS` order, never `repro_scaffold`), takes the real prompt with its delivery re-pointed at `R/prep/shadow` (the `put` line, `TP_SCRATCH` and reply path; `put` computes its target from `--round-dir`/`--slot`, so the real angle's reply is never written) plus one prep line, and keeps the real entry's `agent_ref` and `dispatch_model` (Opus).
5. **Fan-out.** `review_prep_cli.py batch --work R/prep/work`, then spawn the real and the shadow angles in one parallel batch on the same head, and write each spawn's agentId to `R/prep/shadow/ids.json` (`{angle: {"real": id, "shadow": id}}`).
6. **Record.** `python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/review_prep_cli.py ab-record --round-dir R --design-dir <design_dir>` writes two rows per angle under `rp:<pr>:<ordinal>:<angle>`, `ab_arm: base` for the real angle and `ab_arm: prep` for the shadow, both `--oracle pass` and `--rung opus`, with their `findings` and `shape`. An unparseable side logs `ab-unparseable: <angle>` and writes no row. Shadow findings are never merged, posted or counted by the loop: only `cheap_ab.review_prep_verdict` reads them (exact equality, fewer tokens, at least two PRs and two shapes; D12). Nothing flips automatically.
7. **Scaffold.** Under `ab` an accepted scaffold is checked and recorded, never listed to the tail.

## Never

- Nothing here commits, pushes or posts. Drafts live only under the gitignored proof root and `.tp-scratch/`.
- `digest_post` stays excluded, and the review comment post stays today's.
- Every finding, severity, confirmation and convergence call stays on Opus; a drafter only adds labelled context.
- The drafter's cwd is the live worktree, so every batch is snapshotted before it spawns and guarded at `settle`: a change there is `drafter-wrote-live-tree`, and only those paths are undone.
