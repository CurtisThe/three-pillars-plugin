---
name: tp-escalate
description: Escalate a stuck design run from the seat to a Fable agent, or record feedback on a past escalation ruling. Use when the seat is unsure how to rule on a gate and needs a second opinion.
argument-hint: "<slug|seat> [--question <text>|--stop <json>] | feedback <id> agree|disagree <reason>"
---

# /tp-escalate

The seat's half of the escalation protocol in `skills/_shared/escalation.md`: hand a question or
a stop report to a Fable agent (`tp-finalizer`), get a pillar-grounded ruling, and either relay
it to the run or put the one unresolved question to the operator. Feedback on a past ruling
records itself and can propose a lesson.

Read `skills/_shared/escalation.md` first — it is the whole protocol (principles, the run's
half, commit points, the card, the hook, the lesson layers). This skill is the seat's procedure
on top of it; it never restates the rules, only the commands.

## Steps

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

1. **Refuse in a design worktree.** If the current branch is `tp/*`, stop: `/tp-escalate` runs in
   the **base checkout only** — a run's rulings live on its own branch and the seat must not
   write them. Tell the user to run this from the base checkout (or route the question through
   the run itself per `skills/_shared/escalation.md`).

2. **Parse the argument.** Either an escalation: `{slug|seat}` with `--question <text>` or
   `--stop <json>` (a run's finalizer stop JSON); or feedback: `feedback <ruling-id>
   agree|disagree <reason>`. `{slug}` is validated `[a-z0-9-]` per
   `skills/_shared/validate-name.md`; `seat` means a question with no design of its own.

3. **Feedback path** — `python3 "$TP_ROOT"/skills/_shared/ruling_cli.py feedback --id <ruling-id>
   agree|disagree --reason <reason>`, then step 8 (one lesson round) when the feedback disagrees
   with the ruling or the user asks for one. Otherwise commit (step 9) and stop.

4. **Build the stop** — the seat stop carries the fleet context (in-flight registry,
   orchestration handoff, the run's newest ruling, read from the run's worktree or `tp/<slug>`,
   never this checkout):

   ```bash
   python3 "$TP_ROOT"/skills/tp-escalate/scripts/seat_brief.py build --scope {slug|seat} \
     --question-file <f> --kind decision --out stop.json
   ```

   A run's own finalizer stop JSON goes in with `--stop <f>` instead. A fleet `trouble` verdict
   enters as `--question-file` (the verdict summary) with `--kind decision`. A deferred
   base-sync hunk uses `--kind base-sync-hunk` and a code conflict `--kind scope-growth`
   (`scope-growth` operator-only; `base-sync-hunk` Fable-first; a pillar-doc hunk skips Fable: `finalizer_cli.py escalate --reason pillar-doc`), never `decision`.

5. **Ask Fable** — per `skills/_shared/escalation.md` §Run, with the seat's ledger and decisions:

   ```bash
   python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py prepare --stop stop.json \
     --ledger "<git-common-dir>/three-pillars/escalations/seat-ledger.json" \
     --decisions three-pillars-docs/escalations/seat-decisions.md --entry seat
   ```

   Spawn `tp-finalizer` from the returned `agent_ref` with `model=fable`. On a Fable error or
   no Fable access, re-spawn once with the returned `fallback` (Opus, xhigh) and add
   `--model-used opus --fallback-reason <why>` to `apply`. Save the reply verbatim to a file and check it is non-empty (`test -s`); `apply`
   refuses a missing or empty file (exit 2, nothing written). Then:

   ```bash
   python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py apply --stop stop.json \
     --ledger "<git-common-dir>/three-pillars/escalations/seat-ledger.json" \
     --reply <R> --decisions three-pillars-docs/escalations/seat-decisions.md \
     --scope {slug|seat} --entry seat
   ```

6. **`resolved` with a slug** — relay the ruling to the run and let it continue:

   ```bash
   python3 "$TP_ROOT"/skills/tp-escalate/scripts/seat_brief.py relay --id <ruling-id>
   python3 "$TP_ROOT"/skills/_shared/design_run_send.py <slug> "<relay line>"
   ```

   With no tmux session for the run, `design_run_send.py` fails: print the relay line for the
   operator to paste instead. Then `skills/_shared/explainer/explain_cli.py ruling-append --slug
   <slug>` with
   the ruling envelope, so it lands in the shared late ledger (per
   `skills/_shared/escalation.md` §Seat). A `resolved` seat-scoped ruling (scope `seat`) is
   reported to the operator directly — nothing to relay to.

7. **`escalate`** — the card path of `skills/_shared/escalation.md` §Run step 3, from the seat:
   the explainer `human-escalation` loop (seat drafters run on `opus`, never a local engine) to
   the HTML page, then `ruling_cli.py card --id <ruling-id> --html <page.html>`, then exactly one
   `AskUserQuestion` carrying that one question with its trailing `ruling: <id>` line — the
   operator card, so the hook accepts it. Record the answer with `ruling_cli.py answer`. Relay
   the operator's answer to the run (when there is one) as
   `Operator ruling (answered by the operator in the seat session, relayed by the seat): …` via
   `design_run_send.py` (print when there is no tmux session). If the answer differs from
   Fable's recommendation, continue to step 8.

8. **Lesson round** — on `feedback` disagreement or an answer that differs from the
   recommendation, one more Fable round of kind `lesson` (same build/prepare/apply flow, stop
   kind `lesson`). A `resolved` `lesson_proposal` goes through the lessons CLI:
   `python3 "$TP_ROOT"/skills/_shared/lessons.py add --proposal-file <lesson_proposal.json>
   --source <ruling-id> --today <YYYY-MM-DD>` — or `remove --id <L-id> --source <ruling-id>`
   (`--path <file>` picks the layer file; default the repo layer under cwd). A contradiction
   prints `refused-contradiction` with a `/tp-docs-update` proposal, never forced in.

9. **Commit and push** — one scoped add of everything this run of the skill wrote:

   ```bash
   git add three-pillars-docs/escalations/rulings/<ruling-files> \
     three-pillars-docs/escalations/seat-decisions.md \
     three-pillars-docs/escalations/lessons.md
   ```

   Commit (no `git add -A`), then push fail-open: on push failure print one line and keep the
   commit local.

## Rules

- **Base checkout only** (step 1). A seat ruling is never carried by a run's log flush unless its
  scope is that run's slug.
- **Every question routes through `skills/_shared/escalation.md` first** — a card without a
  ruling file cannot exist, and in a design run the hook denies an untagged question outright.
- **Never pass `--pr-url`** for a question stop: a question posts nothing, labels nothing.
- **Seat explainer drafters run on `opus`** — never a local engine (seat rule).
- The seat ledger lives in the git common dir, out of the tree, at
  `<git-common-dir>/three-pillars/escalations/seat-ledger.json`; `seat-decisions.md` and the
  ruling files are committed.
- A missing run ruling, an empty registry or an explainer failure never blocks the ruling —
  they degrade to `null` / one line per `skills/_shared/escalation.md`.
