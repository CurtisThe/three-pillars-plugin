# tp-pr-iterate — Convergence rules (reference)

design: review-convergence (Parts B, D). The rules that decide **when a PR review loop stops**,
and the CLI each rule runs through. `SKILL.md` §Loop body and `round-topology.md` point here
instead of repeating them. Scripts live in `skills/tp-pr-iterate/scripts/` unless noted; the
caps companion is `skills/_shared/agent_caps.py` with its own design note
(`detailed-design-caps.md`).

Every rule below is a **contract on the loop**, not advice. Where a rule names a CLI, that CLI is
the only place the rule is computed — prose never re-decides it.

## D1 — Severity authority

There is exactly **one** severity authority per round: the Opus check. Its `blocking` is final —
a finding the Opus check marks `escape.disposition: "downgraded"` never blocks, whatever its
reproducer does afterwards.

- `severity.is_blocking(f)` is the single predicate: not a sentinel, `blocking is True`, not
  Opus-downgraded, and `reproduction != "refuted"`.
- `severity.finalize(findings)` runs **last in the round tail** — after `reproduce.run_reproducers`
  and the tail annotations — so nothing downstream can re-block a finding the check downgraded.
  `finding_class.tally` then counts that final state.
- A finding whose reproducer ran and passed (`not-reproduced` / `refuted`) is a **note**, not a
  blocker. An inconclusive reproducer keeps the Opus check's call; the runner never fails open.
- Sentinels are checked **before** the severity filter (a sentinel-only round is degraded, never
  clean).

## D2 — Freeze after a clean verdict

A round with `blocking == 0` and `degraded == 0` is a **clean verdict**: `round_freeze.mark_if_clean`
records `frozen_at` (the reviewed head) in iterate-state, and the loop is frozen from that point.

Before the inline fix, the loop asks the freeze question with the CLI:

```
python3 <scripts>/round_freeze.py is-frozen --state-path <state_path>   # exit 0 frozen, 1 not
```

Exit 0 → pass `frozen=True` on `fix_round.run_round`. Under `frozen=True` the non-blocking items
are **deferred** to `<proof_root>/rounds/<pr>/follow-up.json` instead of being edited, and
`round_freeze.py post --pr-url <url> --root <proof_root>` posts them **once**, at the terminal. On
a forge failure the items go to the loop log (flushed into `decisions.md`) with a loud
`follow-up:` line — never silently dropped.

A freeze is not immunity: a **new blocking finding after the freeze still gets its fix**. Only the
non-blocking residue waits.

## D3 — Delta rounds

Round 2+ does not re-review the whole PR. `round_plan.prior_reviewed_head` gives the last head that
produced a non-degraded tail, and the round reviews exactly `delta_text(prior head, head)`: the
fix commits between them, plus only the hand-resolution hunks of any first-parent merge. A sync
merge's base changes are never in the delta.

- The single angle is `delta-check` (`round_plan.DELTA_CHECK`): it says closed-or-open for each
  prior blocker and flags new defects in the delta. No finder is dispatched.
- The **security lens** joins the delta round only when `trust_boundary` flags the delta itself
  (`trust_boundary.surfaces(delta_text)` non-empty) — not when a sync merge dragged a security
  line in from the base.
- A missing prior head refuses (`prepare-refused: no prior reviewed head`) rather than silently
  widening back to the full diff.

## D4 — Audit dispositions

A design's final audit can already have decided a finding. When
`<design_dir>/audit-dispositions.json` exists, the loop passes it to the reproducer:

```
python3 <scripts>/reproduce.py --round-dir R --cwd . --head <head_reviewed> \
    --dispositions <design_dir>/audit-dispositions.json
```

- An **unchanged, already-dispositioned** finding (same file, overlapping lines, claim tokens
  matching, and `git diff --quiet audit_head head -- <file>`) is marked `dispositioned: true` and
  is **not blocking** — it does not restart the loop.
- A **reproduced blocker always blocks**: a finding with `reproduction == "reproduced"` is never
  dispositioned, whatever the audit said.
- Dispositions are consulted on round 1 only; a file that changed since the audit head is live
  again.

## D5 — Review weight

The review budget follows the design's weight class, not a global constant. The loop resolves it
once per round and passes it down:

```
--review-weight "$(python3 "$TP_ROOT"/skills/_shared/weight_class.py review-weight <design_dir>)"
```

on `round_scratch.py prepare`, which stamps it into iterate-state.

| review weight | round cap |
|---|---|
| `just-do-it` | 2 |
| `light` / `spike` / `full` | 3 |

- An explicit `pdw.guards.round_cap` in `.three-pillars/config.json` **still wins** over the
  weight default.
- Extending a `round-cap` needs a **reproduced, Opus-confirmed blocker**: `budget_extension.grant`
  raises unless the state carries `reproduced_blockers > 0`. The extension round is a delta round
  by construction (D3).

## D6 — Round plan

- **Round 1** — the full angle set from `finder_round.round_angles`, **plus the `security` angle**,
  reviewed against the PR base. Under `SMALL_DIFF_LINES` the non-check angles collapse to one
  `combined` angle; the Opus check is always kept.
- **Round 2+** — the delta round of D3: one `delta-check` angle over the fix delta, with the
  security lens only when the delta touches a trust surface.

`round_plan.plan` returns `mode` (`full` | `delta`), the reviewed `base`, `pr_base` and `security`,
and `round_scratch.py prepare` merges them into the round manifest — the manifest stays the path
and plan authority for the round.

## Caps

Per-agent caps are the loop's, not each agent's (D7, operator ruling 23: soft 15 min / hard 25 min).

- After **each** finder dispatch, record the spawn:
  `agent_caps.py spawned --slot-root <R> --slot <angle> --agent-id <id> --started <iso>`.
- (Start it with the Bash tool's `run_in_background`, never a `bash -c` / `nohup` wrapper: `skills/_shared/matchable-commands.md`.) <!-- matchable: ok -->
- Run **one** background watcher for the round:
  `agent_caps.py watch --slot-root <R>` — it prints `wrap-up` once at the soft cap (send the
  `wrap-up-message` text to that agent only) and `stop` at the hard cap (`TaskStop` that agent,
  then `put-capped` keeping its partial).
- A slot dispatched without a spawn record prints a loud `caps:` line — never silent
  non-enforcement.
- **A capped reply is not evidence**: `evidence_complete.check` refuses completion when a required
  confirmer reply is `capped`, and the Opus check prompt is told which slots were capped.

## D8 — Evidence-complete terminal

When the review has produced everything it can and there is nothing to fix, the loop stops
**clean-but-unconverged** rather than burning another round:

```
python3 <scripts>/converge.py --round-dir R    # exit 4, "terminal": "evidence-complete"
```

`evidence_complete.check` is true when the tail findings are readable, nothing is blocking, no
sentinel is present, at least one non-advisory Claude confirmer left a parseable reply, no required
confirmer reply is capped, and `HEAD` still equals the manifest head. A real-blocker refusal never
takes this path.

On that terminal the orchestrator posts **one PR comment** carrying the accept hint
(`accept_hint`) the JSON prints (`Approve with a review body line: tp-accept: <head>
<reason>`) through `forge.comment_post`,
flushes the loop log (`round_scratch.py flush`), and **never starts another round**.

## Base-sync carry check

After any mid-loop `/tp-merge-from-main` push, the loop asks the carry question **once**, before
preparing anything:

```
python3 "$TP_ROOT"/skills/_shared/carry_check.py --repo . --pr-url <url>   # 0 carried, 1 not, 2 error
```

It runs **before the next round is prepared** and **before any `round_scratch.py flush` commit** —
a log-flush commit is never stacked on the sync merge ahead of this check.

- **Carried** (exit 0): no re-review. The loop first runs `scratch_leftovers.py provision --slug {slug}`
  then `scratch_leftovers.py check --expect --slug {slug}` (exit 1: no converge, a stop), then goes to the
  converge oracle (`converge.py --round-dir R`) on the synced head. A docs-only sync (every path the merge
  hand-resolved is a living-doc `.md`) is carried by the proof-neutral carry (`merge_carry.py`).
- **Not carried** (exit 1): the next round is a **delta round** from the pre-sync reviewed head
  (D3, `round_plan.prior_reviewed_head`) — never a full re-review of the synced diff.
- Exit 2 is an error, not a verdict: the loop stops and reports it rather than re-reviewing.
