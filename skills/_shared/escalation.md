# Escalation — the one protocol for every question

design: fable-escalation. One place says how a design run or the seat turns a question into a
ruling: a Fable agent (`agents/tp-finalizer.md`) rules on it from the project pillars, one file
records the ruling, the operator sees only what the pillars did not settle, already analysed.
The run skills (`skills/tp-run-full-design/SKILL.md`, `skills/tp-pr-iterate/SKILL.md`,
`skills/tp-merge-from-main/SKILL.md`) and the seat skill (`skills/tp-escalate/SKILL.md`) point
here rather than restating it. Code: `skills/_shared/finalizer_ruling.py` (the pillar rules),
`skills/_shared/ruling_file.py` and `skills/_shared/ruling_cli.py` (one file per ruling),
`skills/_shared/escalate_first_hook.py` (the hook), `skills/_shared/lessons.py` (the memory).

Every command below runs at **top level** and is prefixed `python3 "$TP_ROOT"/`, where
`$TP_ROOT` is this repo — the skill dir of the running plugin.

## Principles

Escalation to a human is the **terminal fallback**, not the first response.

The floor is **never removed** — self-healing changes only *who tries first*: the audit must
still PASS to advance and the orchestrator never auto-merges.

Three more rules follow from those two:

- **Fable first.** A question — a stuck gate, an env error the finalizer refused, an operator
  decision — goes to `tp-finalizer` before it reaches a human. The operator sees a ruling that
  is already analysed, with the pillar that settles it quoted.
- **Top level only.** A subagent never asks the operator anything. It returns its question in
  its envelope and its caller routes it through this protocol.
- **One file per ruling.** Every ruling — resolved or escalated — is one committed file under
  `three-pillars-docs/escalations/rulings/`, so a card can never lose the analysis behind it.

A question stop is `{"source": "question", "signal": <kind>, "target": <slug>, "detail":
{"question": <text>, "options"?: [...], "context"?: <text>}}`. `signal` is one kind:
`decision`, `lesson`, `merge`, `force-push`, `remote-delete`, `classifier-denial`,
`standing-order`, `scope-growth`, `base-sync-hunk`. The last seven are **operator-only**: Fable
analyses and recommends, the ruling always escalates.

## Run

A run routes a question in three steps. The run's ledger and decisions file are the design's own:
`three-pillars-docs/tp-designs/<slug>/finalizer-ledger.json` and `decisions.md` beside it.

### 1. Ask Fable

```bash
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py prepare --stop <json|file> \
  --ledger three-pillars-docs/tp-designs/<slug>/finalizer-ledger.json \
  --decisions three-pillars-docs/tp-designs/<slug>/decisions.md --entry run
```

- `status: dispatch` — spawn `tp-finalizer` from the returned `agent_ref` with `model=fable` and
  the returned `brief`. On a Fable error, re-spawn once with the returned `fallback` (Opus,
  xhigh) and pass `--model-used opus --fallback-reason <why>` to `apply`.
- `status: noop` — a finalizer for this target is already running. Do nothing.
- `status: refused` — no dispatch: go straight to `escalate` below with that reason, so the
  operator card still gets its ruling file.

Save the reply verbatim to a file R (one JSON object, bare or in one fence; anything else is
unparseable and escalates, never `resolved`). Then:

```bash
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py apply --stop <json|file> \
  --ledger three-pillars-docs/tp-designs/<slug>/finalizer-ledger.json \
  --reply R --decisions three-pillars-docs/tp-designs/<slug>/decisions.md --scope <slug>
```

`--scope <slug>` is required for a question stop: without one `apply` exits 2, so no question can
be ruled on without a ruling file. The same scope rule holds for `escalate`:

```bash
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py escalate --stop <json|file> \
  --reason <refusal> --decisions three-pillars-docs/tp-designs/<slug>/decisions.md --scope <slug>
```

Never pass `--pr-url` for a question stop: a question posts nothing and labels nothing. A
`question` stop is pillar-checked (`skills/_shared/finalizer_ruling.py`): a resolved ruling needs
exactly one recommended option, a quote from `three-pillars-docs/vision.md` or
`three-pillars-docs/architecture.md` under the section it cites, and no pillar conflict. A stop
that fails those checks escalates — it is never quietly resolved.

### 2. `resolved`

Apply the recommended option and continue the run. Then record the ruling for the operator to
read later, through the explainer (`skills/_shared/explainer.md`):

```bash
python3 "$TP_ROOT"/skills/_shared/ruling_cli.py subject --id <ruling-id> --out subject.json
python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py request --kind auto-ruling \
  --slug <slug> --subject subject.json --out request.json
```

Spawn the drafter the `request` output names, finish the loop per that doc, then append the
ruling and point it at its page:

```bash
python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py ruling-append --slug <slug> \
  --envelope <ruling.json>
python3 "$TP_ROOT"/skills/_shared/ruling_cli.py link --id <ruling-id> --explain <ref>
```

The subject is always `ruling_cli.py subject` — never a hand-written summary of the question.

### 3. `escalate`

The operator answers exactly one question, and only after the analysis:

1. the explainer `human-escalation` loop (the checked kind: the Opus check applies) to the HTML
   page;
2. the card, built from the ruling file:

```bash
python3 "$TP_ROOT"/skills/_shared/ruling_cli.py card --id <ruling-id> --html <page.html>
```

3. one `AskUserQuestion` with exactly that one question — its text carries the card's trailing
   `ruling: <id>` line, which is what the hook accepts;
4. the answer:

```bash
python3 "$TP_ROOT"/skills/_shared/ruling_cli.py answer --id <ruling-id> --choice <label>
```

Then continue the run with the operator's choice. A run never adds or removes a lesson; it
records feedback only (`skills/_shared/lessons.py` is the seat's tool).

## Commit points

Ruling files are `three-pillars-docs/escalations/rulings/<slug>-<YYYYMMDD>-<hex6>.md`. A run
never commits them on its own mid-phase — a mid-phase commit on `tp/<slug>` trips the
worktree-isolation guard. They land at three points, each a scoped `git add`:

- **a. Tiers 1–6.** The orchestrator's next tier-boundary bookkeeping commit — the one that
  already stages `decisions.md` / `lock.json` — also stages the run's new or changed ruling
  files.
- **b. Tier 7 and a standalone `/tp-pr-iterate`.** The ruling files ride the terminal log flush
  with `decisions.md`. At the `two-stable` terminal the flush commit stages them and all three
  legs of the carry accept them through one path predicate (`skills/_shared/round_log_carry.py`
  `round_log_slug`, used by `skills/_shared/review_readiness.py`): the head-bound review proof
  and the ci-local stamp carry across the commit, and the head-delta review check treats the
  delta as review-exempt, so a converged PR is not refused for them. At every other terminal
  they stay modified and uncommitted beside `decisions.md`, and the report names them.
- **c. Terminal escalate.** The run skill's `## Cleanup` terminal `decisions.md` entry is
  committed with the ruling files, before the lock is released.

A ruling-only commit is rejected by the carry: the carry stays the closed allow-list anchored on
an archived design's log, so a ruling always travels with a real log flush.

**Base-sync hunks.** Each deferred living-doc hunk a base sync leaves behind is one question of
kind `base-sync-hunk` — operator-only, a seat ruling. Fable analyses it and recommends, the
ruling always escalates, and the recommendation rides the operator card. The merge boundary is
unchanged: the automation never applies the proposal itself. A code conflict on the same
boundary is kind `scope-growth`, also operator-only.

## Seat

`/tp-escalate` (`skills/tp-escalate/SKILL.md`) is the seat's half of this protocol, and it runs
in the **base checkout only** — it refuses in a `tp/*` worktree, where a run's rulings live. Seat
explainer drafters run on `opus`, never a local engine.

```bash
python3 "$TP_ROOT"/skills/tp-escalate/scripts/seat_brief.py build --scope <slug> \
  --question-file <f> --kind decision --out stop.json
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py prepare --stop stop.json \
  --ledger "<git-common-dir>/three-pillars/escalations/seat-ledger.json" \
  --decisions three-pillars-docs/escalations/seat-decisions.md --entry seat
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py apply --stop stop.json \
  --ledger "<git-common-dir>/three-pillars/escalations/seat-ledger.json" \
  --reply R --decisions three-pillars-docs/escalations/seat-decisions.md --scope <slug> --entry seat
```

`--scope seat` is for a question with no design of its own. `seat_brief.py build` adds the fleet
context to the stop — the in-flight registry, the orchestration handoff, and the run's newest
ruling, read from the run's worktree or from `tp/<slug>`, never from this checkout.

- **`resolved` with a slug** — relay the ruling to the run and let it continue:

```bash
python3 "$TP_ROOT"/skills/tp-escalate/scripts/seat_brief.py relay --id <ruling-id>
```

  Send the printed line with `skills/_shared/design_run_send.py`; with no tmux session, print it
  for the operator to paste. Then `ruling-append --slug <slug>` so the ruling lands in the shared
  late ledger and the run's `rulings-sync` lists it.
- **`escalate`** — the same human-escalation loop and card as a run. The answer relays to the run
  as `Operator ruling (answered by the operator in the seat session, relayed by the seat): …`.
- **feedback, or an answer that differs from the recommendation** — one `lesson`-kind Fable
  round; a `resolved` `lesson_proposal` goes to `skills/_shared/lessons.py`.
- **commit** — the ruling(s), `seat-decisions.md` and `three-pillars-docs/escalations/lessons.md`
  in one scoped add, pushed fail-open.

A seat ruling whose scope is `seat` is never carried by the run's log flush — only
`<slug>-…` names are.

## Explain

Both explainer kinds this protocol uses are in `skills/_shared/explainer.md`: `auto-ruling` (a
resolved ruling, no Opus check) and `human-escalation` (the operator question, checked). Two
rules hold on both sides:

- the **subject** is always `ruling_cli.py subject`, so the explanation is generated from the
  ruling rather than from a re-telling of it;
- the **card** is always `ruling_cli.py card` — one card path whether the explainer is enabled
  or not. The explainer adds the HTML page and nothing else.

An explainer failure never blocks a ruling, a commit or a PR: it degrades to one line and the
card still goes out.

## Hook

`skills/_shared/escalate_first_hook.py` is a `PreToolUse` hook on `AskUserQuestion`, registered
in `skills/_shared/hooks/claude-code-hooks.json`. It enforces this protocol in a design run and
nowhere else: `TP_DESIGN_RUN=1`, the cwd on `tp/<slug>`, that design's `lock.json` owner starting
with `orchestrator:`, and the lock's `phase` not `design`. The lock is read from
`three-pillars-docs/tp-designs/<slug>/` or, after the Tier 5.6 archive, from
`three-pillars-docs/completed-tp-designs/<slug>/`, so enforcement covers Tiers 6-7. A missing or
unreadable lock or `phase` allows the question (fail-open), and so does any internal error.

While it enforces, every question in the tool call must carry `ruling: <id>` naming an existing
ruling file whose outcome is `escalate`. An untagged question is denied with a line that points
back here. So: route the question through this protocol first, then ask. Check that the
registration is present with:

```bash
python3 "$TP_ROOT"/skills/_shared/escalate_first_hook.py --check-manifest \
  skills/_shared/hooks/claude-code-hooks.json
```

## Lessons

Two layers, both read by `skills/_shared/lessons.py`: the repo layer at
`three-pillars-docs/escalations/lessons.md` and the user layer under the Claude config dir. The
question brief carries them, so a past ruling informs the next one.

- **The seat only.** Lessons are added and removed only through `/tp-escalate` on the base
  checkout. A run never writes either layer; a run answer records feedback on its ruling file.
- **A lesson never overrides a pillar.** A proposal that contradicts a pillar section is refused;
  the answer is a `/tp-docs-update` proposal instead, because the pillar is what changed.
- **Bounded.** Each layer holds at most 60 lessons; a duplicate is not added twice.
