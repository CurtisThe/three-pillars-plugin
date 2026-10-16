# The explainer protocol

`skills/_shared/explainer/` drafts one of three kinds of **explain envelope**, restates
only evidence it is given in STE-80 prose (`skills/_shared/ste-writing.md`) and safe
diagrams, and never gates a merge. **This doc is the only place a `tp-explainer`
`Agent(` span lives** — every caller below points here instead of spawning the agent
itself.

## The three kinds
- `auto-ruling` — one ruling made without the operator; sections `decided`, `why`,
  `commits-to`.
- `human-escalation` — a question the operator must answer; sections `question`,
  `options`, `pillar-analysis`, `recommendation`; the recommended option is first.
- `pr-brief` — the whole-PR brief; sections `what-merging`, `whole-system`,
  `defaults-switches`, `risks-residuals`, `review-outcome`, `rulings-without-you`.

Only `pr-brief` and `human-escalation` get the Opus check (`explain_engine.needs_check`);
an `auto-ruling` relies on the decider's own record.

## The loop
Full draft → gate → one rewrite on failure → finalize → Opus check (checked kinds only)
→ render → deliver. Every call below is `explain_cli.py <sub>`, run with the caller's
own `--root <repo>` (omitted here for brevity).

### 1. Request
`explain_cli.py request --kind <kind> --slug <slug> [--subject F] [--base B]
[--review-digest F] --out <request.json>` builds the evidence bundle and resolves the
drafter in one call. It prints `{request, drafter, needs_check}`; `drafter` is
`explain_engine.resolve_drafter`'s own row, `{engine, model, effort, note, busy}`.

### 2. Draft
Spawn the drafter on the model `request` just resolved, never a model the caller picks:

`Agent(subagent_type=agent_ref("tp-explainer"), model=<the request output's
drafter.model>, prompt=<mode "draft", the request bundle path, one output envelope
path> + the spawn-prompt suffix below)`

When `drafter.engine` is `local`, spawn through the Strata-spawn discipline in
`skills/_shared/strata-spawn.md`: wait, mark, spawn, verify, decide, release.
`drafter.busy` is always `fallback` — a busy Strata slot is served on Sonnet at once,
never waited for (`strata-spawn.md` §Busy policy). On exhaustion, `strata_spawn.py
decide` answers `sonnet` (it never names Opus since one-cheap-engine) and
`explain_engine.on_exhausted` passes it through, still mapping a legacy `opus` to
`sonnet`, never left as Opus. When `drafter.engine` is `sonnet` or `opus`, spawn in the foreground on
that model with no Strata step.

**Spawn-prompt suffix** (every drafter and check spawn below carries this, verbatim,
the same line `agents/tp-explainer.md` already carries):

> never kill processes by name or pattern (`pkill`, `killall`, `kill $(pgrep …)`),
> including in a throwaway test script; stop only PIDs your own code started.

### 3. Gate and the one rewrite
`explain_cli.py gate --request <request.json> --envelope <draft.json>` runs schema +
sections, evidence refs, the STE lint and the diagram check
(`explain_gate.run_gates`: the sanitizer plus a connectivity check, so a diagram
with a dict-text label, no edge or an unconnected node fails with a reason; the
result carries `diagram_reasons`, one reason per diagram, and the rewrite prompt
states it). Exit 0: go to Finalize. Exit 3 the first time for a given
request: it prints a `rewrite_prompt` and `"next": "rewrite"` — re-spawn the same
drafter in draft mode, its prompt carrying the `rewrite_prompt` text, and run
`explain_cli.py gate` again on the new envelope. Exit 3 the second time: `rewrite_prompt`
is `null` and `"next": "finalize"` — there is only the one rewrite; go to Finalize, which
degrades deterministically instead.

### 4. Finalize
`explain_cli.py finalize --request <request.json> --envelope <draft-or-rewritten.json>
--out <final.json>` (`explain_degrade.finalize`): drops unsupported items, adds a style
note on a lint miss, drops an unusable diagram and leaves a one-line
`diagram omitted: <reason>` note for it (`diagram_notes`, kept across
`finalize --checked`), and falls back to a deterministic facts-only envelope when
the summary itself is unsupported. Prints `{out, facts_only,
check_outcome: null}`.

### 5. Opus check (checked kinds only)
For `pr-brief` and `human-escalation` (`explain_engine.needs_check`), spawn the same
agent in check mode, pinned to Opus — the only judgment call in the loop, and the one
step this protocol never routes:

`Agent(subagent_type=agent_ref("tp-explainer"), model="opus", prompt=<mode "check", the
request bundle path, the finalized envelope path, one output path> + the spawn-prompt
suffix above)`

Then `explain_cli.py finalize --request <request.json> --envelope <final.json> --checked
<checked.json> --out <final.json>` re-finalizes the checked envelope and reports
`check_outcome` (`accepted` / `edited` / `rewritten`, `explain_degrade.check_outcome`'s
diff-ratio verdict — never the check's own self-report).

### 6. Telemetry
`explain_cli.py telemetry --row <JSON>` appends one row (`{ts, slug, kind, engine,
served, gates, rewrite_used, check_outcome, facts_only, degraded}`); `explain_cli.py
report` prints the per-engine rewrite rate.

### 7. Render
`explain_cli.py render --envelope <final.json> --format html|markdown|card|log [--head H]
[--title T] [--slug S] [--html-path P]`. `html` passes `assert_offline`; `markdown`
carries the review-loop marker; `card` puts the recommended option first; `log` is the
auto-mode Decision Entry shape.

## Deliver
Every delivery call below is fail-open: a forge failure prints one line and exits 0,
never blocks the caller (see §Degrade lines).

`explain_cli.py brief --slug <slug> --envelope <final.json> --head <sha>` writes
`brief.md`, the offline HTML and the stored envelope; it commits nothing — the caller's
own commit stages `brief.md`. `explain_cli.py headline --slug <slug>` prints the one-line
PR-body headline, and prints nothing when `explainer.enabled` is false, so the PR body
stays byte-identical with the explainer off.

`explain_cli.py post --slug <slug> --pr <n> [--context manual|autonomous] [--kind
pr-brief|rulings]` posts or edits the one comment of that kind, found by stored id, then
by marker, then posted new. `explain_cli.py post ... --envelope <final.json>` is the
refresh form: it edits the comment and the stored envelope/HTML in place at the current
head, leaves `brief.md` alone, and runs no commit. `explain_cli.py refresh-needed --slug
<slug> --pr <n>` exits 0 when the PR head has moved past the briefed head, 1 when
current.

### Rulings
`explain_cli.py ruling-append --slug <slug> --envelope <ruling.json>` appends one
auto-ruling to the ledger and never commits. `explain_cli.py rulings-sync --slug <slug>
--pr <n>` rebuilds and posts the one rolling rulings comment (a no-op on an empty
ledger) — run right after every brief `post`, so rulings made before the PR existed
still reach it. `explain_cli.py rulings-fold --slug <slug>` folds late rulings (made
after the archival commit) into the archived ledger; it runs just before the Tier 7
terminal log flush.

### Refresh
A refresh never commits, so it cannot move the head it describes: the committed
`brief.md` stays the PR-open snapshot, stamped with its own head SHA. Call
`refresh-needed`; when stale, re-run the loop from Request through Render on the new
evidence, then `post ... --envelope <final.json>` to edit the comment and HTML in place.

### Artifact and record-artifact
When the claude.ai Artifact tool exists and `explain_config.load`'s `publish_artifact`
switch is on, publish the rendered HTML as a private artifact, then run
`explain_cli.py record-artifact --slug <slug> --kind pr-brief|rulings --url <artifact
url>` to store the URL in that kind's delivery record. With no Artifact tool (Hermes,
plain CLI) or `publish_artifact: false`, skip straight past this step — the local HTML
file is always written regardless.

## Call points
Five call points cite this doc; none spawns `tp-explainer` itself.
1. `/tp-design-complete` step 6b3 (after 6b2 `number_issues`, before the 6c `git mv`) —
   drafts `brief.md` (6f stages it); it runs at top level because the subagent `--auto`
   archive cannot spawn.
2. `/tp-design-complete` step 6g — after the PR is created and its number written back,
   `post` the brief, then `rulings-sync`.
3. `/tp-run-full-design` Tier 5.6 Step 2b — the autonomous equivalent of 6b3.
4. `/tp-run-full-design` Tier 6 — after PR creation, `post` the brief then
   `rulings-sync`.
5. `/tp-run-full-design` Tier 7 — at every terminal, `refresh-needed`, then (when stale)
   a refresh `post`, and `rulings-fold --slug <slug>` just before the terminal log flush.

A later caller, `fable-escalation`, reuses `request --kind auto-ruling|human-escalation`,
`ruling-append`, `rulings-sync` and `render --format card`; it is wired per `skills/_shared/escalation.md`.

## Degrade lines
Every fail-open path prints one line on stderr and exits 0: `explainer: <reason> — see
<path>`. A bad input on a delivery subcommand (a missing file, a bad slug) is also a degrade
line: it prints nothing on stdout and exits 0, not 2. A pipeline subcommand keeps exit 2 and
the JSON `{"error": ...}`. A caller never lets an explainer failure block its own commit or PR:

```
explain_cli.py post --slug <slug> --pr <n> || true   # the comment post never blocks the PR
```

The `||` guard is load-bearing: a non-zero exit from any delivery subcommand must never
reach the caller — `brief.md` or the comment is optional, the commit and the PR are not.
A caller checks `explain_cli.py enabled` first and skips the whole loop, byte-identically
to today's PR flow, when it exits 1; `headline` alone re-checks `enabled` itself, so the
PR body stays byte-identical even if a caller forgets the guard.
