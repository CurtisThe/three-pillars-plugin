---
name: tp-run-full-design
description: "Autonomous full-design orchestrator. Drives the TDD pipeline unattended for a single task — pickup → design → worker → audits → PR — and produces a decision log for human review."
argument-hint: "{slug} [--pickup-skill <name>] [--task-id <id>] [--skip-design] [--mode {full|design|plan|build}] [--max-tokens N] [--max-wall-clock SECS] [--max-attempts N=3] [--pr-reviewers <comma-list>] [--no-review] [--no-iterate] [--local] [--force-takeover]"
---

# tp-run-full-design — Autonomous Orchestrator (Mode A0, single candidate)

This skill drives the entire three-pillars TDD pipeline unattended for a single task. It **dispatches each tier into a dedicated subagent** (## Dispatch loop): every delegated `--auto` skill runs inline *inside its slot's subagent*, which synthesizes a clipped return envelope (## Per-slot return contract). The orchestrator itself only ever reads those envelopes plus the running token total — never the tier work product — which is what keeps it under ~100k regardless of design size. Every decision is logged to `decisions.md` per `skills/_shared/auto-mode.md`. (This supersedes the earlier inline prose-orchestration pattern — modelled on `skills/tp-spike-auto/SKILL.md` — where the orchestrator read each delegated SKILL.md and followed its `--auto` instructions in its own context.)

**Mode A0 — MVP scope**: Tier 1 (pickup) → Tier 2 (design pipeline) → Tier 3 (a worker Agent **per plan phase**, each in an isolated worktree) → Tier 3.5 (validation gate on the worker's structured response) → Tier 5 (consolidation audits) → **Tier 5.6 (closeout: fold candidate→`tp/{slug}`, learn-verify, archive)** → Tier 6 (**completion PR** `tp/{slug}→{default}`, design already closed) → **Tier 7 (PR-iterate: drive the review loop to a reviewed-stable state)**. Tier 7 is **on by default** (`--no-iterate` opts out; `--no-review` implies no iteration) so a run ends at a *reviewed-stable* PR, not a fresh un-reviewed one — the orchestrator owns the review loop instead of leaving it for a separate invocation. The **merge-only gate** is preserved: Tier 7 iterates and pushes fix commits, but **never merges** — a human still merges the PR. Tier 4 (council over multiple candidates) is **out of scope for MVP** per design.md §Behavior 4 — adding it requires `/council` to gain a code-candidate evaluation mode, tracked as a follow-on design.

This orchestrator is **not itself an `--auto` skill** — it is the orchestrator *of* `--auto` skills. It does not expose `--auto` in its argument-hint, and the `--auto` ↔ `auto-mode.md` linkage requirement deliberately does not apply to this file (it is the orchestrator, not an auto-mode participant). It does, however, write `[tp-run-full-design/tier-N]`-prefixed entries to `decisions.md` per the prefix convention adopted in detailed-design.md §Decisions (OQ5).

## Arguments

- `{slug}` (required) — kebab-case design name. Must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. Identifies the design directory `three-pillars-docs/tp-designs/{slug}/` and the branch `tp/{slug}`. Distinct from `--task-id` (see below): the slug is the in-repo key; `--task-id` is the opaque upstream reference (e.g., a Jira ticket or Linear issue ID).
- `--pickup-skill <name>` (optional) — the `/tp-pickup-*` skill providing the task. If omitted, the orchestrator falls back to reading an already-seeded `design.md` in the design dir (manual-pickup escape hatch).
- `--task-id <id>` (optional) — opaque upstream task identifier passed verbatim to the pickup skill (e.g., `JIRA-1234`, `LIN-456`, a Notion page ID). Required when `--pickup-skill` is provided; ignored in manual-pickup Mode B. The pickup skill uses `{task-id}` to look up upstream metadata; the orchestrator never interprets the value. Surfaced in the pickup contract as `task_metadata.external_ref` per design.md §Pickup contract.
- `--skip-design` (optional) — opt out of Mode C's interactive-design front-end. When neither `--pickup-skill` nor `--skip-design` is passed, the orchestrator enters Mode C (see ## Tier 1.5). With `--skip-design` and no `--pickup-skill`, the orchestrator behaves as Mode B (read an already-seeded `design.md`).
- `--mode {full|design|plan|build}` (optional, default `full`) — selects a contiguous slot-range sub-window of the 1–11 slot list. `full` (the default) runs the entire pipeline unchanged — backward-compatible, no existing invocation changes. `design` runs Slots 2–4 then a scoped PR and stops (no plan or worker). `plan` runs Slots 5–6 then a scoped PR and stops (requires `design.md` + `detailed-design.md`). `build` starts at Slot 7 (`phase-implement`) and runs to Slot 11 (requires all three design artifacts; a `light` design needs only `design.md` + `plan.md` — the Slot-0 gate is passed the Tier-1 weight class). See `skills/tp-run-full-design/pipeline-modes.md` for the full mode-axis specification (resolution, precondition gate, PR shapes, decisions.md tokens).
- `--max-tokens N` (optional) — whole-run token budget cap. See ## Token budget.
- `--max-wall-clock SECS` (optional) — wall-clock budget. Independent of `--max-tokens`.
- `--max-attempts N` (optional, default `3`) — per-cycle attempt budget for the orchestrator's self-healing loops: audit retry-with-advice (## Retry-with-advice (audits)) and worker-contract retry (## Retry & max-attempts). Default `3` makes the flow self-heal out of the box; `--max-attempts 1` restores escalate-on-first-rejection for high-stakes runs.
- `--pr-reviewers <comma-list>` (optional, default `"copilot-pull-request-reviewer[bot]"`) — reviewers requested in Tier 6. The list is **partitioned**: human logins are requested via `gh pr create --reviewer`, and the Copilot bot is requested via the REST `requested_reviewers` endpoint (the `gh pr create --reviewer` path does not resolve the Copilot bot reliably). See ## Tier 6 — Step 2.
- `--no-review` (optional) — suppress all Tier 6 review requests (both the human `--reviewer` and the Copilot REST request). Use for human-out-of-band or no-review runs. Implies `--no-iterate` (no review requested ⇒ nothing for Tier 7 to iterate).
- `--no-iterate` (optional) — stop after Tier 6 (PR open) without driving the Tier 7 review loop. Restores the pre-Tier-7 "open the PR and hand back" behavior for operators who want to review the fresh PR themselves. Default is **iterate** (Tier 7 runs).
- `--local` (optional) — Slot 7 runs each task through the tier ladder of `skills/_shared/local-dispatch.md` (cheap `tp-task-worker` attempts, verified, escalating to Opus); needs `local_implement.full_design` (## Tier 1). Without it, dispatch is unchanged.
- `--force-takeover` (optional) — claims the design lock from a prior owner per `skills/_shared/collaboration.md`.

## Prerequisites

- The repo's `.gitignore` must exclude `.claude/worktrees/` (worker isolation pollutes this path; design.md §Prerequisites). If absent, this is a downstream-project misconfiguration — the orchestrator refuses to start.
- `gh` CLI must be installed and authenticated (Tier 6 uses `gh pr create`).
- Project test command must be runnable from the repo root (Tier 5 invokes it).

### Artifact policy

The orchestrator and its delegated subagents follow three rules about where work files land:

- **do not write under /tmp** — `/tmp/` is for the host OS's scratch space, not orchestrator-internal state. Worker outputs, decision logs, candidate artifacts, and ad-hoc scripts must live inside the repo where git tracks them and the operator can review them.
- **do not write under `three-pillars-docs/tp-designs/{slug}/candidates/`** from a worker subagent — the orchestrator owns that directory and writes its four artifact files (`branch.txt`, `summary.md`, `test-results.json`, `telemetry.json`) itself in Tier 3.5. Workers only compute and report; the orchestrator (via `write_candidate_artifacts`) is the sole writer.
- Ad-hoc orchestrator scripts and one-off demos belong under **`three-pillars-docs/tp-designs/{slug}/demos/`** — co-located with the design they support so the audit trail stays cohesive. Durable helpers — anything reused across runs or invoked by a SKILL.md — belong under **`skills/{skill}/scripts/`**.

## Execution flow

0. **Run first-run preflight** per skills/_shared/first-run.md, then the **design-run launch check** per `skills/_shared/design-run-launch.md` (`TP_DESIGN_RUN`): marker set → proceed; unset and started by a parent agent's task prompt → refuse before pickup and print the launcher call; operator-typed or unsure → warn once and continue.
1. **Validate `{slug}`** per `skills/_shared/validate-name.md` (must match `[a-z0-9-]+`).
2. Read project docs per `skills/_shared/read-project-docs.md` so each delegated tier inherits context.
3. Walk the slot list via the ## Dispatch loop (`slot 1..N`): each slot dispatches a subagent that runs its delegated `--auto` skill and returns a clipped envelope. The legacy inline tier ordering 1 → 2 → 3 → 3.5 → 5 → 6 maps onto the slots (Tier 4 is intentionally skipped for MVP — see ## Tier 4 below); the ## Tier sections detail each slot's per-tier semantics.
4. On any non-retryable failure, fall through to ## Cleanup and exit with the appropriate non-zero code (Tier 6 fail-open is the lone exception — see that section).

## Dispatch loop

The orchestrator is a lightweight driver: it never reads tier work product (design.md, plan.md, audit findings, council deliberation) directly. Instead it walks an ordered list of **slots** — one dispatched subagent per pipeline tier — and absorbs only each slot's clipped return envelope. This is what keeps the orchestrator under ~100k regardless of design size.

**The orchestrator runs in the main conversation, never as a subagent.** Slot dispatch is one level (orchestrator → tier subagent). The one sanctioned second level is Slot 7's `tp-worker` spawning `tp-task-worker` per `skills/_shared/local-dispatch.md` (depth 2 verified 2026-09-24; supersedes that part of the ADR "Subagent dispatch is single-level").

For `slot 1..N` in the slot list below, the orchestrator dispatches one subagent per slot:

```python
Agent(
  subagent_type="general-purpose",  # template default — resolved per-slot (see ## Slots): audit slots 4/6/8 → "tp-readonly-auditor", worker slot 7 → "tp-worker", all others stay "general-purpose"
  isolation="worktree",
  description="orchestrator/{slug}/{slot}",
  prompt=compose(top_doc_refs, project_context_block, slot_args, soft_budget, hard_budget, explicit_return_contract),
)
```

Both kwargs apply to the main slot dispatches: `subagent_type="general-purpose"` and `isolation="worktree"` (each slot forks a fresh worktree from the design branch HEAD so the orchestrator's branch stays clean). **Exception**: the audit fan-out sub-dispatches (Slots 4/6/8: reader, Round-1/2 personas, synthesizer) skip `isolation="worktree"` — they are read-only and share `tp/{slug}` directly (see ## Audit fan-out (Slots 4/6/8)). `compose(...)` assembles the slot prompt from top-level project-doc references (read once, ~20k), the injected `{project_context_block}`, the slot's arguments, its soft/hard token budget (see ## Per-slot budget table), and the per-tier `explicit_return_contract` (see ## Per-slot return contract). On return the orchestrator runs the on-return sequence (see ## Return clipping) and decides per `status`: advance to the next slot, retry-with-advice, resume a handoff, escalate, or abort. The orchestrator fills `{project_context_block}` **once per run** from `skills/_shared/project_context.py` (`load_context_block()`) and threads it into **every** slot dispatch — the worker slot (`tp-worker`), the audit fan-out slots (`tp-readonly-auditor`), and the `general-purpose` slots alike — so no spawned tier re-derives the project's conventions/stack/domain-rules from the codebase (the same injection council Round 1 and the `tp-phase-implement` worker already carry). **Omit the block when it is empty** (absent `project-context.md`) so `compose(...)` degrades to today's exact prompt byte-for-byte.

The slot sections below give each slot's delegated skill and return-envelope class; the per-tier semantics (pickup contract, worker isolation, the Tier 3.5 gate, audits, PR fail-open) are detailed in the ## Tier sections that follow and are reconciled into the slot model in the final reconcile phase. **`--mode` slot-range axis**: see `skills/tp-run-full-design/pipeline-modes.md` for the mode-resolution rule, precondition gate, and per-mode PR shapes.

## Slots

The orchestrator dispatches these slots in order (`slot 1..N`, where N = 9 fixed slots plus one `phase-implement` dispatch per plan phase). Each runs its delegated `--auto` skill inline and synthesizes a return envelope of the stated class, validated by `parse_tier_return` against the matching schema — **except** the `pickup` slot (its own `pickup-contract-v1` shape; ## Pickup contract v1 validation) and the worker / `phase-implement` slot (the `candidate.v1` path through `run_tier_3_5.py`).

### Slot 1 — `pickup`
Resolves the task source into a locked branch + `design.md` (## Tier 1). Returns the **pickup contract v1** envelope (unchanged shape — deliberately not folded into generator-return; see detailed-design §Decisions "Minor").

### Slot 2 — `design`
Runs `/tp-design {slug} --auto` (Mode C front-end excepted; ## Tier 2). **generator-return** class.

### Slot 3 — `detail`
Runs `/tp-design-detail {slug} --auto`. **generator-return** class.

### Slot 4 — `design-audit`
Drives the council audit fan-out (## Audit fan-out (Slots 4/6/8)) over `design.md` + `detailed-design.md` instead of dispatching a single `/tp-design-audit` subagent. **audit-return** class; the `verdict` drives retry-with-advice vs. escalation. **Guard certification** runs every attempt after the synth: the Slot 4 form of `skills/_shared/certification-protocol.md` §Step 2b (`S` = the `tp/{slug}` HEAD, the same `tp-certifier` dispatch, `python3 "$CERT" run`, one `python3 "$CERT" fold --slot 4`; `$CERT` resolved as in ## Tier 5 Step 2b).

### Slot 5 — `plan`
Runs `/tp-plan {slug} --auto`. **generator-return** class.

### Slot 6 — `plan-audit`
Drives the council audit fan-out (## Audit fan-out (Slots 4/6/8)) over `plan.md` + `detailed-design.md` (+ `design.md` when it has a `## State space` section, so members can run the map-check angle) instead of dispatching a single `/tp-plan-audit` subagent. **audit-return** class.

### Slot 7 — `phase-implement`
Runs `/tp-phase-implement {slug} --auto`, dispatched as `subagent_type="tp-worker"` (write-capable surface — Read/Edit/Write/Grep/Glob/Bash plus Agent; default model `opus`), **once per plan phase**; tasks run in order; under `--local` it hands each `local`/`sonnet` task to a nested `tp-task-worker` (## Phase-implement dispatch — nested per task). The worker / candidate machinery (## Tier 3 + ## Tier 3.5) is preserved: this slot keeps the `candidate.v1` contract and routes its return through `run_tier_3_5.py`, not `parse_tier_return`. Workers obey the file-size caps (`CLAUDE.md` §File Size Limits): an addition that would cross a cap splits by responsibility instead of growing the file — the file-size guard blocks hard-cap violations at commit.

### Slot 8 — `impl-audit`
Drives the council audit fan-out (## Audit fan-out (Slots 4/6/8)) over `design.md` + `plan.md` **and the candidate code** — the code reaching members via `--code-input` (the Slot-8 code-input addendum), not as a single `/tp-implementation-audit` subagent (## Tier 5 Step 2). **audit-return** class; verdict-only — never edits code regardless of confidence. (The Tier 5 Step 1 regression check still runs first and gates the fan-out.)

### Slot 9 — `design-learn`
Runs `/tp-design-learn {slug} --auto` (## Tier 5 Step 3). **generator-return** class; a synthesizer, not a gate. **After Slot 9, ## Tier 5.6 closeout runs**: the orchestrator folds the candidate onto `tp/{slug}` (`git merge --no-ff`, inline), runs `verify_learn.py` (learn-verify, advisory), then dispatches `/tp-design-complete {slug} --auto` to archive. The fold + learn-verify are orchestrator-inline and the archive is one `--auto` dispatch — Tier 5.6 is not a numbered slot of its own.

### Slot 10 — `PR`
Opens the **completion PR** (`tp/{slug} → {default}`) with the fail-open semantics of ## Tier 6, after Tier 5.6 has folded the code and archived the design. (On a Tier 5.6 fold conflict it opens the legacy candidate→tp PR instead; ## Tier 6 — legacy fallback.) Hands off to Slot 11 unless `--no-iterate`/`--no-review` is set, in which case it is terminal.

### Slot 11 — `pr-iterate`
Drives the completion-PR review loop to a reviewed-stable state. **Terminal slot.** The orchestrator owns the round loop directly (Tier 7 Step 1): each round it fans out the `ANGLES` set as top-level `general-purpose` sub-agents pinned `model="opus"`, then one round tail posts via `post_codereview_comment`, shells `run_round.py` and fixes inline, until a `terminal` phase. The round tail is the one working-tree writer, on the orchestrator's own `tp/{slug}` checkout (never checks out, orchestrator idle). Skipped under `--no-iterate` or `--no-review`. generator-return class; a non-converged loop is reported, never escalated past the merge-only gate.

### Light slot mapping (`weight-class: light`)

When Tier 1 reads `light` (## Weight-class consumption (Tier 1)), the slot sequence narrows — same machinery, fewer dispatches:

- **Slot 2 (`design`) emits design.md + plan.md in one dispatch** — the collapsed design.md and the thin plan.md from a single light-mode `/tp-design` sitting (the collapsed note must still pass `validate_design_floor.py`).
- **Slots 3 and 5 are skipped** (`detail`, `plan`) — the light class has no detailed-design.md and plan.md already landed with Slot 2.
- **Slots 4 + 6 merge into one audit fan-out** — a single council pass over design.md + plan.md using the `--light` merged conceptual+plan prompts (`skills/tp-plan-audit/SKILL.md` §Light mode prompts): same triad, **single round** (no Round 2), reader + 3 members + synth = **5 dispatches**.
- **Slot 8 = regression check + a single fidelity auditor** — Tier 5 Step 1's regression check runs unchanged and still gates; the 3-persona fan-out is replaced by **one** verdict-only auditor working the fidelity checklist (`skills/_shared/weight-class.md` §Light fidelity checklist), its finding confidences mapped through `auto_verdict.compute_verdict` (`"$TP_ROOT"/skills/_shared/auto_verdict.py`). It also returns `guard_claims[]`, and Step 2b runs unchanged.
- All other slots (1, 7, 9, 10, 11) run unchanged. The per-slot return contracts and the C1 token accounting are untouched — light is fewer dispatches, not a different protocol.

## Audit fan-out (Slots 4/6/8)

Each audit slot (`design-audit`, `plan-audit`, `impl-audit`) runs an
**orchestrator-owned council fan-out** instead of dispatching a single
`/tp-*-audit --auto` subagent. The orchestrator drives `/council --orchestrator`
(## ORCHESTRATOR MODE in `skills/council/SKILL.md`) itself — reading that mode
inline, never dispatching `/council` as a subagent — and issues the
`council-{name}` + synthesizer dispatches directly. Every arrow below is a
**top-level single-level dispatch** (orchestrator → subagent, no deeper), which
is what makes the fan-out feasible under L23. The council personas and the
synthesizer are **read-only** — they share `tp/{slug}` read-only with **NO
`isolation="worktree"`** (unlike the worker/`phase-implement` slot, whose
worktree-isolation posture is unchanged; see ## Dispatch loop).

The fixed sequence per audit slot is **reader → Round 1 → Round 2 → synth →
clip**:

1. **Reader (1 dispatch)** — dispatch one `general-purpose` subagent (`model="opus"`) to confirm
   the artifact paths exist and report their sizes (cheap, ~5k). This replaces
   "load artifacts" without pulling contents into the orchestrator. **This is a
   real dispatch and consumes `subagent_tokens`** — the reader IS counted in the budget
   (## Per-slot budget table dispatch accounting; F1).
2. **Round 1 (N dispatches, parallel)** —
   `/council --orchestrator --round 1 --members {triad} --artifacts {paths}`
   **(+ `--code-input base=tp/{slug},candidate=origin/candidate/{slug}/single,files=…`
   appended for the `impl-audit` slot only — see ### Slot-8 code-input addendum;
   Slots 4/6 omit it and stay artifact-only)**.
   The orchestrator validates the returned round-bundle, then each member
   envelope in a second loop (## Return clipping two-step), clips each Round-1
   envelope (keeps `argument_summary` + `findings` + per-finding `confidence` +
   envelope `confidence`), discards the raw replies, and sums each dispatch's
   `subagent_tokens` into the running total.
3. **Round 2 (N dispatches, parallel)** —
   `/council --orchestrator --round 2 --members {triad} --round1 {bundle}`
   **(+ the same `--code-input base=tp/{slug},candidate=origin/candidate/{slug}/single,files=…`
   appended for the `impl-audit` slot only — Slots 4/6 omit it)**, where
   `{bundle}` is the **full Round-1 round-bundle** file (every peer's verdict +
   findings + argument_summary, F5), **not a summary** and not a thinned list —
   so each persona can cross-examine concrete peer findings by index. Same
   validate + clip + token-sum. **Round 2 is skipped entirely under
   `--fast-audit` (0 dispatches).**
4. **Synth (1 dispatch)** — assemble the synthesizer prompt via
   `build_synth_prompt(artifact_paths, round1, round2, slot)` and dispatch one
   **`general-purpose` subagent, `model="opus"`, with NO `isolation="worktree"`** (F8 — read-only,
   shares `tp/{slug}`, identical isolation posture to the council personas). It
   reads the artifact paths, weighs the Round-1/Round-2 dicts (honoring each
   `challenged_finding_indices`), and returns the existing **`audit-return`**
   envelope.
5. **Clip** — the orchestrator parses the synth reply via
   `parse_tier_return(reply, audit-return.v1.json)`, holds only the `audit-return`
   dict (~5k), and the `verdict` drives the unchanged retry-with-advice /
   escalation rules (## Retry-with-advice (audits)).

**Default triad (F10):** all three audit tiers default to the engineering triad
**`torvalds, ada, feynman`** — reusing `tp-plan-audit`'s existing engineering triad, the in-scope
minimal default (the design forbids changing the council persona set or triad
definitions). `council/SKILL.md` already defines an `architecture` triad
(`aristotle, ada, feynman`) and a `shipping` triad (`torvalds, musashi, feynman`);
a follow-on could wire per-tier triads (e.g. `architecture` for design-audit) by
passing a different `--members` list — **no schema or code change required**, only
the orchestrator's default selection. `--deep-audit` → the full 18-member panel;
`--fast-audit` → the triad with Round 2 skipped. **Map check (Slots 4/6):** when design.md has a `## State space` section, every Round-1/Round-2 member prompt and the synthesizer brief append the Check-mode angle of `skills/_shared/state-space-protocol.md` ("was a better locus or alternative dismissed without evidence?"), filed as INCONSISTENT, never MISALIGNMENT, and tagged `category: "map-check"` by the member itself; the synthesizer keeps (or adds) that tag in the audit-return `findings[]`, and **any** such finding — under **any** verdict (`pass`, `pass-with-notes` or `needs-work`) and any confidence — escalates the run to the operator immediately (## Retry-with-advice escalation, map-check trigger); it never becomes re-spawn advice and never passes silently. No map → no angle (the `--auto` rule).

### Slot-8 code-input addendum (`impl-audit` only)

The five-step sequence above is shared by all three audit slots. **For
`impl-audit` (Slot 8) only**, the **council members (Round 1 + Round 2) and the
synthesizer read the candidate code** — the artifact-only audit (the question
`design-audit` / `plan-audit` answer) can never tell whether the *code* honors
the design. The **reader does NOT review the code**: it stays the cheap
`general-purpose` path-existence dispatch of step 1, additionally confirming that
the Slot-8 code-input **refs/paths resolve** — that `tp/{slug}` and
`origin/candidate/{slug}/single` exist and the touched-file paths are present —
so a broken ref-pair fails fast before the member rounds spend tokens. The reader
reports existence only; it never reads the diff body or judges the code. **Slots
4/6 stay artifact-only** (no `--code-input`, `code_input=None` on the synth call,
byte-identical to the five steps above); the addendum below is scoped to Slot 8
and changes nothing for `design-audit` / `plan-audit`.

- **Refs reach the members via `--code-input`.** The orchestrator computes the
  ref-pair once (inline, cheap) — `base = tp/{slug}`,
  `candidate = origin/candidate/{slug}/single` — and derives the touched-file
  list with name-only three-dot `git diff --name-only
  tp/{slug}...origin/candidate/{slug}/single` (a path list, ~hundreds of bytes,
  **never** the diff body). Each Round-1/Round-2 dispatch carries
  `--code-input base=tp/{slug},candidate=origin/candidate/{slug}/single,files=…`
  (## ORCHESTRATOR MODE in `council/SKILL.md`); every member runs its own
  three-dot `git diff tp/{slug}...origin/candidate/{slug}/single` /
  `git show origin/candidate/{slug}/single:<file>` and judges the **code against**
  `design.md` + `plan.md`. The orchestrator never holds the raw diff.
- **The synth call gains the 5th arg for Slot 8.** `build_synth_prompt` now takes
  a defaulted `code_input=None` 5th parameter. For `impl-audit` the synth step
  calls `build_synth_prompt(["…/design.md", "…/plan.md"], round1, round2,
  "impl-audit", code_input={base, candidate, touched_files})`; the synthesizer
  reads the candidate code itself via those refs (it gets the refs, not the diff
  body). For `design-audit` / `plan-audit` the existing 4-arg
  `build_synth_prompt(artifact_paths, round1, round2, slot)` literal (step 4
  above) stays correct — it is equivalently `code_input=None`, so no edit to that
  literal is required; the parameter is defaulted and this addendum is where the
  Slot-8 5-arg form is documented.
- **Large-diff gate → audit-by-dimension (no truncation).** Above **1500**
  changed lines (insertions + deletions from three-dot `git diff --shortstat
  tp/{slug}...origin/candidate/{slug}/single`) Slot 8 engages **audit-by-dimension**
  (## Handoff protocol — pre-split): one read-only dispatch per dimension
  (`consistency`, `coverage`, `codebase-fit`), each carrying the same
  `--code-input`, instead of one member reading the whole diff at once. The diff
  is **never trimmed** — the fan-out widens by dimension so each unit stays within
  budget. When the count exceeds 1500 the orchestrator appends
  `[tp-run-full-design/tier-5] impl-audit-large-diff <N> lines → audit-by-dimension`
  to `decisions.md` (Confidence: High) so an oversized candidate is visible rather
  than silently fragmented.

## Per-slot budget table

Each slot carries a fixed **soft budget** — a sizing hint passed into `compose(...)` so the slot knows how much room it has — and a single **hard ceiling of 500k tokens / slot**, well below the 1M harness limit so that a single handoff split (## Tier sections / handoff phase) can never overflow. These are static; there is no derivation math (detailed-design §Decisions "Static per-tier budget table").

| Slot | Soft budget | Light | Hard ceiling |
|---|---|---|---|
| `pickup` | 50k | 50k | 500k |
| `design` | 80k | 100k (collapsed design.md + thin plan.md) | 500k |
| `detail` | 60k | — (skipped) | 500k |
| `design-audit` | 200k | 150k (merged audit — Slots 4+6 as one fan-out) | 500k |
| `plan` | 100k | — (skipped) | 500k |
| `plan-audit` | 200k | — (merged into the 150k fan-out above) | 500k |
| `phase-implement` | 200k / phase | 200k / phase | 500k |
| `impl-audit` | 200k | 80k (single fidelity auditor) | 500k |
| `certifier` (Slots 4/8, if claims) | 150k / dispatch | 150k / dispatch | 500k |
| `design-learn` | 100k | 100k | 500k |
| `PR` | 50k | 50k | 500k |

The audit slots (`design-audit`, `plan-audit`, `impl-audit`) are weighted higher (200k) because audits read the full design + plan + codebase; generators and the PR slot are lighter. `phase-implement` is budgeted **per plan phase** — one dispatch per phase, each with its own 200k soft budget. The **Light** column applies when Tier 1 reads `weight-class: light` (### Light slot mapping): the design slot grows to 100k (it emits two artifacts), the merged audit runs at 150k, the fidelity audit at 80k, and the **hard ceiling is unchanged** at 500k. The light numbers are tunable sizing hints, recorded here as the single source of truth.

### Audit-tier dispatch accounting — the reader IS counted (F1)

Each audit slot fans out into the reader → Round 1 → Round 2 → synth sequence (## Audit fan-out (Slots 4/6/8)). Every one of those is a real top-level dispatch consuming `subagent_tokens`, so **the reader is a counted dispatch** and the per-tier total is `1 (reader) + N (Round 1) + N (Round 2) + 1 (synth)`:

| Mode | N (members) | Round 2? | Dispatches | Breakdown |
|---|---|---|---|---|
| default (triad) | 3 | yes | **8** | 1 + 3 + 3 + 1 |
| `--deep-audit` (full panel) | 18 | yes | **38** | 1 + 18 + 18 + 1 |
| `--fast-audit` (triad, no R2) | 3 | no | **5** | 1 + 3 + 0 + 1 |

These 8 / 38 / 5 counts are used everywhere the audit budget appears — this table, the SKILL prose, and the `test_budget_table()` grep-anchor literals. All accounting **includes the reader**; the dispatches are summed by the existing C1 `subagent_tokens` running total with no new budget mechanism (## Token accounting).

The soft budgets are advisory sizing only. The **whole-run `--max-tokens` cap** is the real constraint: it bounds the running sum across all dispatches (## Token accounting) and is **checked at slot boundaries** — after each slot returns and before the next is dispatched. A slot in flight always finishes before a boundary abort; there is no mid-slot preemption (## Token budget). The orchestrator itself stays under ~100k throughout because it only ever holds clipped envelopes plus the running token sum.

## Token accounting (C1)

Budget enforcement reads an **authoritative** per-dispatch token count, not the subagent's self-report. After each `Agent(...)` dispatch returns, the orchestrator reads the harness `subagent_tokens` field from the **Agent-tool return metadata** (the same return envelope that carries `agentId` and `worktreePath`) and adds it to a **running total** that it sums across all dispatches. At each slot boundary it checks that running total against `--max-tokens` (## Token budget).

This is the C1 decision, and it is load-bearing. Claude Code exposes no running self-total to an agent, but each dispatch's authoritative cost *is* returned to the parent in `subagent_tokens` (spike H1). The P1 dogfood probe verified the field is live before any budget machinery was built on it: the outer probe dispatch returned `subagent_tokens: 35322`, corroborated by six council dispatches, so the committed probe verdict is `C1-ABSENT? NO` and whole-run budget enforcement is viable. (Had the probe found the field absent, this section would instead document `--max-tokens` as deferred / a slot-count heuristic — see plan Task 3.3's C1-ABSENT branch — but that branch was not taken.) The audit-slot **fan-out** dispatches (reader + Round-1 + Round-2 personas + synthesizer; ## Audit fan-out (Slots 4/6/8)) are summed by this **same** running total — ordinary `Agent(...)` dispatches counted by the existing C1 sum, **no new budget mechanism** (the 8 / 38 / 5 reader-counted totals in ## Per-slot budget table). The return envelope's `telemetry.tokens_used` is a **separate, advisory/nullable** field — the subagent's own self-report, which spike F4 showed undercounts by ~50%; it is informational only and **not used for budget** — the orchestrator sources the running total only from the harness `subagent_tokens` metadata, never the parsed envelope. Reading the budget number from the envelope is the C1 regression this rule exists to prevent.

## Per-tier briefing emit

After each tier's **outcomes** land in `decisions.md`, the orchestrator refreshes the live fleet-state briefing — a **CLI step, not a Python hook**, so the ~100k budget is untouched: it shells out once per tier to the **pro-tier** `python3 "$TP_ROOT"/skills/_shared/html_briefing/emit_run_briefing.py --slug {slug} --worktree {worktree} --tier {tier-id} --tokens {running-total}` (running total from ## Token accounting / C1). The call is **fail-open** — a briefing failure (bad args, a raising producer, or — in the FREE core build — an absent `html_briefing`) never aborts the tier loop, and `decisions.md` stays the loop's durable record (html-briefing-flow Task 4.2); on success it writes the offline `index.html` + `fleet-state.json` + one `ledger.jsonl` row (the C2 timeline/cost source). It never passes `--serve` (a foreground localhost-only server for the human-initiated standalone surface — it would block the auto loop). See `skills/_shared/html_briefing/` (pro-tier) and html-briefing-flow Task 4.3.

## Per-slot return contract

Every dispatched slot is given an `explicit_return_contract` in its `compose(...)` prompt — the slot-level parallel of the worker's Tier-3 `explicit_artifact_contract`. It tells the subagent exactly how to run its tier and what to return:

1. **Run the tier's `--auto` skill inline.** The subagent follows the delegated skill's SKILL.md `--auto` instructions directly in its own context — it does **not** shell out to `claude -p`. Running inline is what keeps the dispatch's `subagent_tokens` visible to the orchestrator (## Token accounting / C1) and is why a single-level fan-out is sufficient.
2. **Let the skill write its native artifacts + `decisions.md` entries** under its own prefix. The delegated `--auto` skills are **unmodified** — they still only write `decisions.md` plus their artifacts and set an exit code; they emit no return envelope of their own. This rewrite adds no requirement to any delegated skill.
3. **Synthesize the return envelope itself.** After the skill finishes, the subagent composes the tier-return envelope from the skill's `decisions.md` entries + the skill's **exit code** — `status` (`pass` / `needs-work` / `errored`), plus the `verdict` + `findings` for audit slots and `artifact_paths` for generator slots — and emits it as the **last** fenced ```json block in its reply. This is the C2 decision: the orchestrator never interprets the raw skill output; it parses the subagent-synthesized envelope (## Return clipping) against the slot's schema class.

Because the delegated skills are untouched, envelope synthesis is a thin layer the dispatched subagent owns, not a change to the pipeline. The schema class per slot is given in ## Slots (generator-return / audit-return / pickup-contract; the worker / `phase-implement` slot keeps `candidate.v1` and routes through `run_tier_3_5.py`).

## Return clipping

When a slot subagent returns, the orchestrator runs this fixed **on-return sequence** before touching the next slot:

1. **Read `subagent_tokens`** from the Agent return metadata, add it to the running total, and check the total against `--max-tokens` at this slot boundary (## Token accounting, ## Token budget).
2. **Parse** the reply with `parse_tier_return(reply, schema_path)` for the slot's schema class — it extracts the last fenced ```json block and validates it. (The worker / `phase-implement` slot routes through `run_tier_3_5.py` and the `candidate.v1` path instead.)
3. **Clip**: keeps only the parsed dict and **discards the raw reply**. `parse_tier_return` is the clip point — the orchestrator retains nothing else from the subagent, which is what bounds its context to ~100k.
4. **Branch on `status`**: `pass` → advance to the next slot; `needs-work` → retry-with-advice or escalate per the audit rules; `handoff-pending` → resume from the committed handoff; `errored` → escalate.
5. **Log** an `[orchestrator/<slot>]`-prefixed entry to `decisions.md` recording the `status`, the clipped summary, and the running token total.

Only the clipped dict survives into the next iteration; the raw subagent reply, its scratch reasoning, and any artifact contents never enter the orchestrator's context.

Record/replay hooks (`--record`/`--replay`): see `record-replay.md`.

## Handoff protocol — pre-split (M2)

A dispatched subagent **cannot self-yield mid-call**: the harness exposes no "pause and hand back partial progress" primitive, so once a slot subagent is running the orchestrator cannot reach in and checkpoint it. A single oversized dispatch is therefore caught only at the *next* slot boundary — never interrupted mid-flight — consistent with the no-mid-tier-abort rule (## Token budget). "Checkpointed dispatch" does not mean a subagent pausing itself; it means the orchestrator splitting the work *before* it dispatches.

The mechanism is **pre-split**, decided on the orchestrator side. Instead of one giant dispatch for a long tier, the orchestrator issues a series of **sequential dispatches**, reading the harness `subagent_tokens` (## Token accounting) **between** them and stopping when the slot's work is done or its budget boundary is reached. Each long-tier class has a natural split axis:

- **`design-audit` / `plan-audit` / `impl-audit` → audit-by-dimension** — one dispatch per audit dimension (e.g. consistency, coverage, codebase-fit) rather than one dispatch reading the whole design + plan + codebase at once.
- **`plan` → plan-by-section** — one dispatch per plan section / phase group when the plan is large.
- **`phase-implement` → phase-by-phase** — one dispatch per plan phase. This is already the Slot 7 model (## Slots): one `phase-implement` dispatch per plan phase, each within its own per-phase budget.

Pre-splitting is purely an orchestrator-side sequencing decision; the delegated `--auto` skills are unchanged. The orchestrator reads `subagent_tokens` between the sequential dispatches and sums each into the running total exactly as for any other dispatch, so a pre-split tier obeys the same whole-run `--max-tokens` cap (## Token budget). A dispatch that nonetheless overshoots its budget is still only caught at the next boundary — pre-split shrinks each unit so the overshoot is bounded, it does not add mid-dispatch preemption.

### Cold-resume worklist

Each pre-split checkpoint is persisted to a **committed** worklist file at `three-pillars-docs/tp-designs/{slug}/.handoffs/{slot}-{attempt}-{N}.md` — `{slot}` is the slot name, `{attempt}` its retry-with-advice attempt (## Retry-with-advice counter), and `{N}` the sequential checkpoint index within that dispatch chain. The file is a markdown body with a `handoff.v1` envelope embedded as its **last** fenced ```json block; on resume the orchestrator parses it with `parse_tier_return(body, handoff.v1.json)` (the `handoff-pending` branch of ## Return clipping).

The worklist is **committed to git** at each checkpoint, never held only in the orchestrator's context — that durability is what makes a **cold-resume** possible. If the orchestrator process dies mid-tier (SIGTERM, crash, host restart), a fresh `/tp-run-full-design {slug}` invocation reads the latest committed `.handoffs/{slot}-{attempt}-{N}.md` under `tp-designs/{slug}/`, recovers `partial_state` + `next_action` + `files_to_continue_with` + `remaining_budget_estimate` from the embedded envelope, and resumes the pre-split chain from the next checkpoint instead of restarting the whole tier. Because the worklist lives under `tp-designs/{slug}/` and is committed, it survives both the orchestrator discarding its own context (## Return clipping) and any worker-worktree cleanup.

## Tier 1 — Pickup

The pickup tier resolves the task source into a `design.md` and a locked branch the orchestrator can drive. Two modes:

**Mode A — Pickup skill provided** (`--pickup-skill <name>` AND `--task-id <id>` passed):

1. Refuse with a clear error if `--task-id` is missing — Mode A cannot proceed without an upstream identifier to hand to the pickup skill. (Append `[tp-run-full-design/tier-1] missing-task-id` to decisions.md and exit non-zero.)
2. Invoke the pickup skill with the orchestrator identity flag and pass the slug + task-id through:
   ```
   /{pickup-skill} --orchestrator --slug {slug} --task-id {task-id}
   ```
   - `{slug}` is the in-repo key the orchestrator already received as its required positional.
   - `{task-id}` is the opaque upstream reference; the pickup skill is responsible for resolving it into upstream metadata and seeding `design.md`.
3. The pickup skill is responsible for:
   - Validating the upstream task identified by `{task-id}` is ready
   - Creating `three-pillars-docs/tp-designs/{slug}/`
   - Creating and locking branch `tp/{slug}` with `owner = orchestrator` (see ## Lock ownership)
   - Seeding `design.md` (or `spike.md`) if the upstream system carries that data
   - Returning a **pickup contract** envelope on stdout (with `task_metadata.external_ref = {task-id}` echoed verbatim so the orchestrator can re-cite it in the Tier 6 PR description)
4. Read the returned pickup contract.

**Mode B — Manual pickup** (no `--pickup-skill`):

1. Read existing `three-pillars-docs/tp-designs/{slug}/design.md` (must exist).
2. Acquire the lock per `skills/_shared/collaboration.md`. If held, honor `--force-takeover` or refuse.
3. Synthesize a minimal pickup contract from local state (no callbacks; `phase_hook`, `writeup_hook`, `escalate_hook` all `null`).

**Local preflight** (both modes): run `python3 "$TP_ROOT"/skills/_shared/agent_override_warn.py --root .` on every run, with or without `--local` (Behavior 11; always exits 0; log any warning). Under `--local` only, then run `python3 "$TP_ROOT"/skills/_shared/local_implement_config.py --check full_design`: exit 1 → refuse before Tier 2 (append its line as a `[tp-run-full-design/tier-1]` entry, exit non-zero).

### Pickup contract v1 validation

Validate the returned contract before any other work: schema and rules in `boundary-contracts.md` §Pickup contract v1.

### Lock + branch protocol

The pickup skill (Mode A) or the orchestrator itself (Mode B) acquires the design lock per `skills/_shared/collaboration.md`. The orchestrator is a distinct lock-owner identity — see ## Lock ownership.

After Tier 1 succeeds, the orchestrator is on branch `tp/{slug}` and the lock's `phase` field reflects the current tier (e.g., `phase: "tier-2"` once Tier 2 begins). Each subsequent tier refreshes `last_touched` and bumps `phase` as it enters.

### Weight-class consumption (Tier 1)

After the pickup contract validates, read the design's **weight class** (`skills/_shared/weight-class.md`):

```bash
python3 "$TP_ROOT"/skills/_shared/weight_class.py read three-pillars-docs/tp-designs/{slug}
```

This is a **direct design.md frontmatter read** — the pickup-contract v1 envelope is unchanged and the class **never rides** it (audit finding m1). The legacy `("full", "default")` read (no/invalid frontmatter) routes as `full` — fail-safe toward more checking.

Routing rules by class:

- **`full`** — the pipeline as documented below; no change.
- **`light`** — the light slot mapping (see ## Slots and ## Per-slot budget table for the light column).
- **`just-do-it`** — **escalates to `light`**: an unattended run warrants the audit floor. Log the escalation to decisions.md with exactly this entry (the auto-mode Decision Entry template, class transition named):

  ```markdown
  ### [tp-run-full-design] weight-class escalation: just-do-it → light
  **Question**: design.md declares `just-do-it`; may an unattended run skip the audit floor?
  **Decided**: Escalated just-do-it → light for this run (design.md's declared class unchanged).
  **Reasoning**: Unattended runs warrant the light audit floor; escalation is always allowed, de-escalation never (skills/_shared/weight-class.md §Escalation rule).
  **Confidence**: High
  ```

- **`spike`** — **refuse** (audit finding M1): `/tp-spike-auto` Phase 1 is **interactive** by design and cannot run unattended. This is a refusal with guidance, not a conversion — never silently re-class a spike as a full design. Append exactly this BLOCKED entry and exit non-zero:

  ```markdown
  ### [tp-run-full-design] BLOCKED — spike-class design cannot run unattended
  **Cause**: weight-class-spike-refusal
  **Details**: design.md declares `weight-class: spike`. /tp-spike-auto Phase 1 (design Q&A) is interactive by design — run it manually; if a follow-on full design emerges, re-run this orchestrator against it. No spike→full conversion is attempted.
  ```

- **De-escalation is refused**: the orchestrator may escalate ceremony above the declared class (logged as above), never de-escalate below it. Any flag, config, or heuristic requesting a lighter run than design.md declares takes the same BLOCKED path (`**Cause**: weight-class-de-escalation-refused`).

### Tier 1 outcomes

- **Success**: pickup contract valid, lock held, branch checked out, weight class read and routed. Proceed to Tier 2.
- **Failure**: any validation rule above, or the spike-class / de-escalation refusal. Append the categorized decisions.md entry, exit non-zero. No partial state — Tier 2 never runs on an invalid contract.

## Tier 1.5 — Mode C front-end (interactive design)

Mode C is the default behavior when the operator invokes `/tp-run-full-design {slug}` **without** `--pickup-skill` and **without** `--skip-design`. It exists for the "I want autonomous-from-here, but the design conversation needs a human" workflow — the orchestrator runs `/tp-design` interactively, then asks the operator whether to continue unattended.

> **Note on decisions.md prefix**: Tier 1.5 emits tokens under the `[tp-run-full-design/tier-1]` prefix (not `tier-1.5`). This is deliberate — Tier 1.5 is a front-end to Tier 1's pickup flow, not an independent tier with its own concerns. Reusing the `tier-1` prefix keeps `grep '[tp-run-full-design/tier-1]' decisions.md` complete for the entire pickup-and-confirm phase. The Tier 3.5 prefix (`tier-3.5`) is the structural parallel: it gets its own prefix because Tier 3.5 is its own tier with its own retry budget and failure taxonomy, whereas Tier 1.5 is purely a sequencing concern.

### Default routing

When neither `--pickup-skill` nor `--skip-design` is set:

1. **No `design.md` in the design dir** — invoke `/tp-design {slug}` first and let it run its normal interactive conversation. Once `/tp-design` commits the new `design.md`, fall through to the confirmation prompt.
2. **`design.md` already exists** — re-enter /tp-design (per OQ4). The design skill itself handles the revise-or-fresh choice; the orchestrator does not special-case the existing-design path. Once `/tp-design` commits its update (or no-ops on a revise-no decision), fall through to the confirmation prompt.

Pass `--skip-design` to bypass this tier — Mode B's plain manual-pickup behavior resumes (the orchestrator reads the existing `design.md` and proceeds directly to Tier 2 audits without re-running `/tp-design`).

### Confirmation prompt (blocking yes/no)

After `/tp-design` returns, the orchestrator asks the operator:

```
Go autonomous from here?
[y/n]
```

There is no countdown auto-proceed (OQ1) — a human must explicitly answer. The orchestrator blocks on stdin until it receives `y`/`yes` or `n`/`no` (case-insensitive). Any other input re-prompts.

### Outcomes

- **`y` / `yes`** — Append `[tp-run-full-design/tier-1] autonomous-continue` to decisions.md, advance to Tier 2 with the orchestrator-held lock. The rest of the run is unattended.
- **`n` / `no`** — Terminal no-branch state per OQ7:
  - `design.md` is already committed (by the preceding `/tp-design`).
  - The branch `tp/{slug}` is preserved at the design commit.
  - The lock owner restored to the invoking human (the orchestrator releases its claim cleanly without requiring `--force-takeover` on the operator's next `/tp-design-detail {slug}` invocation).
  - One `[tp-run-full-design/tier-1] no-autonomous-run` entry is appended to decisions.md.
  - Exit code 0.

The "no" path is the seamless hand-off — the operator gets a committed design they can pick up manually, with no leftover orchestrator state to clean up.

## Tier 2 — Design pipeline chain

Slots 2–6 are the design pipeline. The orchestrator **dispatches one subagent per slot** (## Dispatch loop); each subagent runs one of the five design-pipeline skills in `--auto` mode **inline within the subagent** and synthesizes its return envelope (## Per-slot return contract). **The orchestrator never runs these skills in its own context** — it only reads each slot's clipped envelope (## Return clipping). Each delegated skill still writes `[<skill-name>]`-prefixed entries to `decisions.md` per `skills/_shared/auto-mode.md`; the orchestrator does NOT rewrite these entries — the native skill prefix is preserved, and only orchestrator-emitted entries use the `[tp-run-full-design/tier-N]` prefix.

The five slots dispatch in order, one skill each (run inline in the dispatched subagent; Slot 4 is the fan-out):

| Slot | Skill | Return class |
|---|---|---|
| 2 — `design` | `/tp-design {slug} --auto` | generator-return (Shape A gate) |
| 3 — `detail` | `/tp-design-detail {slug} --auto` | generator-return |
| 4 — `design-audit` | ## Audit fan-out + Step 2b (## Slot 4) | audit-return |
| 5 — `plan` | `/tp-plan {slug} --auto` | generator-return |
| 6 — `plan-audit` | `/tp-plan-audit {slug} --auto` | audit-return |

### Per-skill semantics

Each delegated skill follows one of the three auto-mode shapes defined in `skills/_shared/auto-mode.md`:

- **`/tp-design --auto`** — **Shape A** (validator gate). Delegates to `skills/_shared/validate_design_floor.py`. Either PASS (proceed) or BLOCKED (a `design.md` floor violation — missing Problem/Vision-alignment/Scope/Behaviors). The orchestrator treats BLOCKED as a Tier 2 abort cause; see "Audit rejection" below. Any other exit or failure to launch → BLOCKED with Cause: floor-validator-crash, Details: captured stderr (truncated to 500 chars). Never treat a non-0/1 exit as PASS.
- **`/tp-design-detail --auto`** — **Shape B** (generator). Produces `detailed-design.md` from `design.md` without user Q&A; every judgment call self-logs Confidence: High/Medium/Low. The orchestrator does not gate on Confidence here — generation always proceeds; Confidence: Low entries are informational and surface in the Tier 5 audit.
- **Slot 4 (`design-audit`)** — the ## Audit fan-out synth plus the Slot 4 form of Step 2b (## Slot 4), never a `/tp-design-audit` subagent (its Step 6b, lacking the Agent tool, would BLOCK every claim).
- **`/tp-plan --auto`** — **Shape B** (generator). Produces `plan.md` from detailed-design.md. Same gating semantics as design-detail.
- **`/tp-plan-audit --auto`** — **Shape C**: High-confidence findings auto-resolve; any **Medium or Low** finding escalates BLOCKED.

### Audit rejection — self-heal, then escalate

The orchestrator is built to **self-heal**: an audit `needs-work` verdict does not stop the run. The orchestrator re-runs the generator that produced the rejected artifact, hands it the audit's findings as advice, and lets the audit re-judge — looping up to the per-cycle attempt budget (## Retry-with-advice (audits)). **Every finding — high, medium, or low confidence — drives a re-spawn** (except `category: "map-check"`, which escalates instead); confidence no longer gates retry-vs-escalate. This is on by default (`--max-attempts` defaults to `3`).

Escalation to a human is the **terminal fallback**, not the first response. There are four terminal causes — the two below plus **map-check escalation** (any `category: "map-check"` finding from Slot 4/6, any verdict: append `[tp-run-full-design/tier-2] map-check-escalated`) and **certification-unverified** (Slots 4/8; both per ## Retry-with-advice escalation):

- **Retry budget exhausted** — the per-cycle budget (`--max-attempts`) is spent and the audit still returns `needs-work`. Append `[tp-run-full-design/tier-2] audit-retry-exhausted` with the residual findings.
- **Shape A design-floor BLOCKED** (from `/tp-design` — e.g. `design.md` missing Problem / Vision-alignment / Scope / Behaviors). This is the one structural floor that cannot self-heal: in Mode A/B the `design.md` is human/pickup-seeded, so re-running the validator cannot author the missing sections. It escalates without retry. Append `[tp-run-full-design/tier-2] design-floor-blocked`.

On any terminal cause the orchestrator does NOT proceed to the worker tier, and:

1. Appends the categorized `decisions.md` entry (`audit-retry-exhausted` or `design-floor-blocked`) with the verdict / residual-finding list and Confidence: High.
2. Returns BLOCKED to the operator (exits non-zero from the orchestrator).
3. Leaves the lock + branch as-is so a human can pick up via `/tp-session-restore {slug}` and address it without re-running pickup.

The floor is **never removed** — self-healing changes only *who tries first*. The audit must still PASS for the run to advance, and the orchestrator never auto-merges; a human reviews the final PR. The orchestrator attempts the mechanical fix before spending a human's attention; when it cannot converge within the budget, the human still gets the gate. Setting `--max-attempts 1` restores escalate-on-first-rejection for high-stakes runs.

### Token-cap boundary check

The orchestrator checks `--max-tokens` at each **slot boundary** — after each design-pipeline slot subagent returns — summing the harness `subagent_tokens` into the running total (## Token accounting). See ## Token budget for the abort semantics; Tier 2 implements no boundary logic of its own.

## Tier 3

Worker (one subagent per plan phase, each in an isolated worktree). Tier 3 is invoked once per plan phase — it spawns a worktree-isolated subagent for Phase N, hands it the design, plan, the target phase number, and an explicit artifact contract, and waits for the structured response that Tier 3.5 will validate. The candidate branch (`candidate/{slug}/single`) is shared across all phase dispatches: Phase 1 creates it; Phase 2+ fetches and continues from it.

### Worker Agent invocation

`worker_prompt = compose(design.md, plan.md, phase=N, tier_table=T if --local) + explicit_artifact_contract`, then `Agent(subagent_type="tp-worker", isolation="worktree", description="candidate/{slug}/phase-{N}", prompt=worker_prompt)`, with no `model` (default model `opus`).

`isolation="worktree"` is mandatory: it cuts a fresh git worktree under `.claude/worktrees/agent-<id>/` so the worker's `.git/index` is independent of the orchestrator's. The orchestrator's branch (`tp/{slug}`) stays clean while the worker commits on the shared candidate branch. Note: the worker's auto-entry branch is `worktree-agent-<id>` (a Claude Code default, NOT the orchestrator's `tp/{slug}`), which is exactly why item 1 of the worker contract below requires an explicit branch setup step — without it the worker would build on the auto-entry branch and the orchestrator would have nowhere clean to merge from. This is S13 finding F2; see `completed-tp-designs/agent-worktree-isolation-spike/d12-worker-contract-revision.md`.

### `explicit_artifact_contract` — 6 worker responsibilities

Appended to `worker_prompt` verbatim: the six-item list in `boundary-contracts.md` §explicit_artifact_contract.

## Tier 3.5 — Validation gate

Tier 3.5 runs **at the end of every phase dispatch**, not deferred to the last phase — a malformed envelope is caught at the phase that produced it (see ## Phase-implement dispatch).

Tier 3.5 parses the worker's structured response, validates it against `candidate.v1.json`, writes the four candidate artifact files, and cleans up the worker worktree. Failures here decide whether `--max-attempts` retries (see ## Retry & max-attempts) or escalates.

### No-op short-circuit

Before parsing anything: if the `Agent(...)` return envelope has no `worktreePath` field, the worker made no file system changes in its worktree (Claude Code auto-cleans empty worktrees before returning). Action:

- Skip the artifact-write (there's nothing to validate or persist).
- Append `[tp-run-full-design/tier-3.5] worker-noop` to `decisions.md` with Confidence: High.
- **Escalate immediately** — `--max-attempts` does NOT retry this case (case (a) in detailed-design.md §Error Semantics; the worker producing nothing is a non-retryable structural failure, not a transient one). Per S13 finding F8.

### Wrapper-driven pipeline

For the normal path (`worktreePath` present), the orchestrator runs `run_tier_3_5.py` (below), which composes `parse_candidate_response` → `write_candidate_artifacts` → `cleanup_worker_worktree` → `git ls-remote` SHA cross-check → phase re-run.

Invocation (Bash `timeout: 600000`; the re-run's 480 s phase budget fits inside it):

```
python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/run_tier_3_5.py
```

Pipe a JSON object on stdin: `{worker_response, agent_meta: {agentId, worktreePath}, design_dir, candidate_id, slug, rerun}`. Read the single-line JSON envelope on stdout: `{status, case, event_token, detail}`. The exit code carries the orchestrator's next action:

- **`rerun`** (required) — `{plan_path, phase, phase_base_sha, test_cmd?}`, validated after the SHA cross-check (bad → `stdin-invalid`): `rerun_phase_tests.py` re-runs each task's declared Targets at the SHA in a scratch tree. Confirmed red → case f; skips, unverified runs, a phase verifying nothing (`unverified`, not a pass), unlisted files (case g) self-log, exit 0.
- **`0` — proceed**: `status: "ok"`, `case: null`, `event_token: "ok"`. Tier 3.5 succeeded; advance to Tier 5.
- **`1` — retry per `--max-attempts`** (case c only): `status: "retry"`, `case: "c"`, `event_token: "schema-validation-error"`. The worker emitted a fenced JSON block with the canonical schema string but the payload failed validation — re-enter Tier 3 if attempts remain.
- **`2` — escalate**: `status: "escalate"`, `case` in `{"a", "b", "e", "f", null}` (f: `rerun-failed`, failing nodes in `detail`). Append the `[tp-run-full-design/tier-3.5] <event_token>` line to decisions.md and exit non-zero. `case: null` is reserved for wrapper-internal failures (`event_token` `stdin-invalid`, `invalid-worktree-path`, `artifact-write-failed`, `cleanup-failed`, `sha-check-failed`, or `rerun-error`) — these are environmental or contract violations, not retryable, and must not collide with exit 1 (case c).

`cleanup_worker_worktree` force-removes a locked worktree (`--force -f`) and self-logs `[tp-run-full-design/tier-3.5] worktree-cleanup-locked <path>` (never an envelope case). The wrapper keys paths and branch refs off the worker-reported `candidate_id`; the stdin `candidate_id` is advisory (decisions.md correlation).

### SHA cross-check (case (e), non-retryable)

After `write_candidate_artifacts` returns, the orchestrator runs a final sanity check on the candidate branch:

```
git ls-remote origin candidate/{slug}/{candidate_id}
```

If the remote head SHA does not match `parsed["sha"]`, the worker's push claim is wrong (push race, auth, or a fabricated SHA). Action:

- Append `[tp-run-full-design/tier-3.5] sha-mismatch {slug}:{parsed_sha}:{remote_sha}` with Confidence: High (the event-type token classifies; see ### Distinguishing case (e)).
- **Escalate immediately** — case (e) is non-retryable; an environmental issue, not a worker fault.

### Tier 3.5 outcomes

- **Envelope parsed** (not a/b/c), before any case: append a `### [tier] <task_id> — <final>` entry per `telemetry.task_tiers[]` record to decisions.md (sole full-design writer: pipe it to `tier_ladder.py entry --record -`).
- **Success**: 4 artifact files written, worktree cleaned, SHA check passes; any record with `final == "env-error"` is non-retryable — append `[tp-run-full-design/tier-3.5] task-env-error <task_id>` and escalate. Proceed to Tier 5.
- **Retryable failure** (case (c)): re-enter Tier 3 per ## Retry & max-attempts.
- **Non-retryable failure** (case (a) no-op, (b) no-block, (e) sha-mismatch, (f) rerun-failed): escalate per its decisions.md entry above; exit non-zero.

## Phase-implement dispatch — nested per task

The `phase-implement` slot (Slot 7) is dispatched **once per plan phase**: one Opus `tp-worker` owns the phase and runs `/tp-phase-implement {slug} --auto` inline (## Per-slot return contract), taking its tasks **one after another** — never a parallel worktree fan-out. Without `--local` each task is an inline red-green-refactor cycle, as before. With `--local` the worker prompt carries the phase's tier table and the worker follows `skills/_shared/local-dispatch.md`: one nested `tp-task-worker` spawn per `local`/`sonnet` row (the sanctioned second level, ## Dispatch loop), checked by `task_verify.py` and escalated by `tier_ladder.py`; `opus` rows stay inline. It stays within its phase-implement soft budget (200k / phase; ## Per-slot budget table) and returns one **candidate / phase envelope** — never the per-task work (## Return clipping).

**Per-phase ordering (fixed sequence within each phase dispatch):**

1. **Branch setup** (contract item 1): Phase 1 creates `candidate/{slug}/single`; Phase 2+ fetches and continues. Just before each dispatch, capture `phase_base_sha`: first phase → `git rev-parse {base-ref}`; later → the prior Tier-3.5-`ok` SHA. Log `[tp-run-full-design/tier-3] phase N dispatch phase_base_sha=<sha>`; invariant across that phase's Tier 3 retries; on cold resume re-derive (the dispatch line, else the prior `candidate-*.json`). Under `--local`, also run `python3 "$TP_ROOT"/skills/_shared/task_eligibility.py <plan> --phase N` before the dispatch, log its output as `[tp-run-full-design/tier-3] phase N tier table`, and put it in the `tp-worker` prompt.
2. **Implement + commit** (contract items 2, 3): run tasks one-after-another, one commit per task.
3. **push before synthesizing the envelope** (contract item 4 precedes item 5): `git push -u origin candidate/{slug}/{candidate_id}` — the SHA in the envelope must reference a pushed commit so the orchestrator's `git ls-remote` SHA cross-check (Tier 3.5 case e) is meaningful. Under the single-worker model, `candidate_id == "single"`, so the branch is `candidate/{slug}/single`.
4. **Synthesize the `candidate.v1` envelope** (contract item 5): the final `candidate.v1` JSON block.
5. **Orchestrator runs `run_tier_3_5.py` at the end of this phase** (before dispatching the next phase): parse → write artifacts → cleanup → `git ls-remote` SHA cross-check → phase re-run (stdin `rerun`).

## Tier 4 — Council coordination (skipped in MVP)

Mode A0 has **no Tier 4**. The single candidate from Tier 3 is taken verbatim through Tier 5's audits; if those pass, Tier 6 opens the PR. There is no inter-candidate selection, no diff-voting, no persona overlay.

Adding Tier 4 requires:
- `/council` gaining a code-candidate evaluation mode (`--input` over `candidates/`, voting semantics over diffs, not over positions) — Round 1 finding B1.
- A non-test discriminator between candidates (mutation testing, secondary-LLM audit, or council reading diffs directly) — finding V2.

These are out of scope and tracked as a separate multi-candidate follow-on design.

## Tier 5 — Consolidation audits

Tier 5 takes the validated single candidate from Tier 3.5 and runs it through the consolidation audits — regression check, implementation audit, design-learn synthesis — as **dispatched slots** (## Dispatch loop), never inline in the orchestrator. There is no inter-candidate comparison in MVP (Tier 4 is skipped); the single candidate is either accepted or rejected verbatim.

Slot 8 (`impl-audit`) runs as **two sequential dispatch surfaces, not one subagent**: Step 1 is a *distinct isolated dispatch* (a regression-check subagent with `isolation="worktree"`) that runs **first**; Step 2 is the *orchestrator-owned read-only council fan-out* (members share `tp/{slug}`, no isolation) that runs **after**, only on a green Step 1. Step 1 writes a working tree (checkout) and so must isolate; Step 2 only `git show`/`git diff`s and so legitimately shares. They are sequential phases of the slot, never the same dispatched subagent.

### Step 1 — Regression check (distinct isolated dispatch)

The orchestrator **dispatches a regression-check subagent** for Slot 8 with `isolation="worktree"`. This is its **own** isolated dispatch (it is NOT the council fan-out of Step 2). It first re-runs the project test suite on the candidate branch:

```
# checkout lands in the slot's OWN worktree (isolation="worktree"), NEVER the
# orchestrator's (## Branch hygiene). Fast iteration lane — no full ci-local here.
git fetch -q origin candidate/{slug}/single
git checkout candidate/{slug}/single
$(python3 "$TP_ROOT"/skills/_shared/iteration_lane.py --lane iteration --granularity phase)
```

**Branch-hygiene requirement (load-bearing):** the regression check needs the candidate's *working tree*, so it must `git checkout` the candidate branch — which is why the `impl-audit` slot is dispatched with **`isolation="worktree"`**. A check running in a shared worktree would mutate the orchestrator's HEAD and orphan its in-flight commits (## Branch hygiene). Do **not** "optimize" this slot to share `tp/{slug}` — unlike the *read-only* audit fan-out sub-dispatches (Slots 4/6/8, which only `git show`/`git diff`), the regression check writes the working tree via checkout and **must** isolate.

The seam resolves the `--fast` lane in the dev repo and degrades to the project-discovered command (`CLAUDE.md` / `Makefile` / `pyproject.toml` / `package.json`, never `pytest`) in a consumer repo. It writes **no** stamp: the one mandatory full `scripts/ci-local.sh` run is the human's `/tp-merge` `ci_local_stamp` gate at land, not any orchestrator step. Full output stays in the subagent's context; the orchestrator sees only the reported result in the audit-return envelope. On a reported regression (any test the worker did not already mark failed/skipped in `test_results`):

- Append `[tp-run-full-design/tier-5] test-regression` with the failing test names + Confidence: High.
- **Escalate immediately** — a regression in tests the worker reported as passing is a contract violation by the worker (the `test_results.passed` count was wrong). Not retryable by re-running the worker. Operator pickup.

### Step 2 — `impl-audit` slot (orchestrator-owned council code-audit fan-out)

Once Step 1's regression check is green, the orchestrator itself drives the
**read-only council code-audit fan-out** for Slot 8 (## Audit fan-out (Slots
4/6/8)) — a **distinct dispatch surface from Step 1**: the orchestrator owns it
directly (per ORCHESTRATOR MODE), its members **share `tp/{slug}` with no
isolation** (they only `git show`/`git diff`), and it runs **after** Step 1's
isolated regression-check subagent has returned green. This is sequential, not the
same subagent as Step 1. The fan-out is: reader → Round 1
→ Round 2 → synth → clip over `design.md` + `plan.md` **and the candidate code**,
the code reaching every member via `--code-input` (the Slot-8 code-input
addendum). This is the same orchestrator-owned fan-out `design-audit` /
`plan-audit` already run, only the **inputs widen** — the control flow is
unchanged. Step 1 **gates** Step 2 (sequential, not alternative): there is no
point auditing code that fails its own tests, so Step 2 runs only on a green
regression check. The fan-out is **verdict-only** — it never edits code
regardless of confidence — and the synthesizer computes the overall verdict from
the merged Round-1/Round-2 findings (the same confidence/verdict mix the
standalone audit skill would compute), returning it in the **audit-return**
envelope:

- All findings High (or no findings) → **PASS** or **PASS WITH NOTES**. Proceed to Step 3.
- Any Medium or Low finding → **NEEDS WORK**. Rather than escalating, the orchestrator triggers **retry-with-advice** (## Retry-with-advice (audits)): it re-spawns the `phase-implement` worker with the finding list as advice and re-dispatches `impl-audit` to re-judge, looping up to `--max-attempts`. It appends `[tp-run-full-design/tier-5] impl-audit-needs-work` and escalates **only when the attempt budget is exhausted** (## Retry-with-advice escalation). (`--max-attempts 1` restores escalate-on-first-rejection.)

The PASS vs PASS WITH NOTES split is informational — both proceed to Tier 6. The notes are surfaced in the Tier 6 PR description so the reviewer sees what passed-with-caveats.

**Step 2b — guard certification** (every Slot 8 attempt, after Step 2's synth, before Step 3). The procedure is `skills/_shared/certification-protocol.md` §Step 2b; it is not restated here. Resolve the CLI once (`$RS` is reused below):

```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
CERT="$(python3 "$RS" certify.py)" || exit 1
CL="$(python3 "$RS" certify_ledger.py)" || exit 1
```

First `python3 "$CERT" claimant-check --base tp/{slug} --ref S --design {design}` (`{design}` = the repo-relative design dir; exit 1 → `certification-unverified`, `claimant-records`). Dispatch `Agent(subagent_type="tp-certifier", isolation="worktree", model="opus")` once per claims file **per attempt** (verdict files first), the claims bytes fenced as untrusted data, with the resolved absolute `$CERT` path. Copy each `records_file` to scratch, run `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>` (sha256 + count; exit ≠ 0 → run that file with `--unverified records-handoff` instead of `--records`), then copy it under `certifications/records/`. Run `python3 "$CERT" run … --watch-ref …` per file (`--name` = the file's path under `certifications/`, `--out <scratch>/r<N>.result.json`), then one `python3 "$CERT" fold --slot 8` with a `--result` for every result (sweep ones included) and `--verdict-guards <scratch>/diff.txt` (`git -c core.quotePath=false diff --no-renames --name-only tp/{slug}...S > <scratch>/diff.txt`): its output replaces the Step 2 envelope and feeds the branching of ## Retry-with-advice escalation (a `guard_claims[]` id no `records/` result certified folds `unverified`). Its step 6 (ledger files) runs through `$CL` only when a `sweep-NN.claims.json` or `self.claims.json` exists and only renders the pending issues file; `issues apply` runs after the Tier 5.6 fold (its Step 1). One commit, at protocol step 7 (after the HEAD assert).

### Step 3 — `design-learn` slot (`/tp-design-learn {slug} --auto`)

The orchestrator **dispatches the `design-learn` slot subagent** (Slot 9), which runs `/tp-design-learn {slug} --auto` inline — Shape B generator. It reads the completed implementation and synthesizes:

- Project doc updates (architecture.md / product_roadmap.md / known_issues.md) — applied per the skill's normal write protocol.
- A `[tp-design-learn]`-prefixed decisions.md trail of what was learned.

`/tp-design-learn --auto` **never edits `three-pillars-docs/vision.md`** — that load-bearing literal is enforced by the skill itself (a SKILL.md prose contract; see `skills/tp-design-learn/SKILL.md`). The orchestrator does not duplicate that check; the delegated skill owns it.

If `/tp-design-learn --auto` produces only High-confidence updates, Tier 5 is done and Tier 6 opens the PR. If it logs Medium/Low-confidence judgments, they flow into the PR description but do not block — design-learn is a synthesizer, not a gate.

### Tier 5 outcomes

- **All three steps pass** → proceed to Tier 5.6 (closeout).
- **Step 1 (regression)** → escalate, exit non-zero (a non-retryable worker-contract violation; see Step 1).
- **Step 2 (NEEDS WORK)** → retry-with-advice (re-spawn `phase-implement`); escalate + exit non-zero **only** when the attempt budget is exhausted (## Retry-with-advice escalation).
- **Step 2b (unverified)** → escalate, exit non-zero (`certification-unverified`; `not-binding`/`false-red` fold to NEEDS WORK, the Step 2 row).
- **Step 3 (design-learn errors)** → log Medium-confidence, proceed (the candidate is already audited; missing project-doc updates do not invalidate the implementation).

## Tier 5.6 — Closeout (fold → learn-verify → archive)

**This is the closeout-before-merge terminal.** Before this tier, the orchestrator stopped at an *un-closed* candidate→tp PR; now Tier 5.6 folds the candidate code onto `tp/{slug}`, verifies the learn propagation, and archives the design, so Tier 6 opens **one completion PR** (`tp/{slug} → {default}`) that already contains code + propagated docs + the archived design. One human merge then lands a *closed* design. The **merge-only gate is preserved** — Tier 5.6 is feature-internal, entirely below the gate; nothing here merges to `{default}`.

### Step 1 — Fold the candidate into `tp/{slug}` (orphan-safe merge-in)

The orchestrator is pinned on `tp/{slug}` (## Branch hygiene). Folding is a **merge-in, not a checkout** — HEAD stays on `tp/{slug}`, so it does NOT trip the orphan hazard (which is *checkout*, not *merge*):

```
git merge --no-ff origin/candidate/{slug}/single -m "Fold candidate into tp/{slug}"
```

- The candidate is **code-only** and `tp/{slug}` is **artifacts-only** ⇒ near-disjoint trees ⇒ the merge is clean in the common case.
- **Conflict → `git merge --abort`**, then fall back to the legacy **candidate→tp PR** (## Tier 6 — legacy fallback) and append `[tp-run-full-design/tier-5.6] fold-conflict` (Confidence: High). **Never auto-resolve** a fold conflict — that would be the silent mutation the vision forbids; the human resolves it on the fallback candidate PR.
- **Clean fold → pending issues** (if Step 2b rendered `certifications/records/known-issues.pending.md`): `python3 "$CL" issues apply --pending <it> --known-issues three-pillars-docs/known_issues.md` on the folded tree (`$CL` per ## Tier 5 Step 2b; ids re-derived past the candidate's entries), then commit. After a conflict it stays pending.

### Step 2 — Learn-verification (advisory)

With the code now folded onto `tp/{slug}`, run the learn-verify grep:

```
python3 "$TP_ROOT"/skills/_shared/verify_learn.py --range {default}...tp/{slug} --json
```

It reports `three-pillars-docs/**` lines (living **and** `completed-tp-designs/`) that still name a symbol/file this design **retired** — the "learn ran ≠ docs match as-built" gap. **Range note**: `{default}...tp/{slug}` (three-dot) diffs merge-base→`tp/{slug}`, surfacing *this design's* deletions; the literal `tp/{slug}...{default}` would diff the wrong (base) side. **Advisory only** — `verify_learn.py` always exits 0 and fails open; flagged refs flow into the Tier 6 PR description **and** a `[tp-run-full-design/tier-5.6] learn-verify` decisions.md entry, and **never block** (the hard gate is the framework's CI closeout check, not this grep).

### Step 3 — Archive (`/tp-design-complete {slug} --auto`)

Dispatch `/tp-design-complete {slug} --auto` (see that skill's `## Auto Mode`): it `git mv`s the design dir to `completed-tp-designs/`, stamps completion frontmatter, rewrites Current Focus / Design Inventory, and commits `Complete design: {slug}` — whose pre-commit self-check runs the staged-blob guard `verify_archive_staged.py` (a stampless / lock-phaseless / dangling-cite archive can never be committed) — and it **opens no PR** (Tier 6 owns the single completion PR) and removes no worktree. Its step-3 learn-ran hard-block is **auto-satisfied** because Tier 5 Step 3 (Slot 9 `design-learn`) just ran. The archival commit lands on `tp/{slug}` (## Branch hygiene assert-before-commit applies).

### Tier 5.6 outcomes
- **Fold clean + archive committed** → proceed to Tier 6 (completion PR `tp/{slug} → {default}`).
- **Fold conflict** → `git merge --abort`, open the legacy candidate→tp PR (## Tier 6 — legacy fallback), flag, exit 0 (work durable on the candidate branch; the human resolves the conflict).
- **`/tp-design-complete --auto` BLOCKs** (learn somehow not satisfied) → it logs a BLOCKED entry to decisions.md; the orchestrator surfaces it and exits non-zero (operator pickup). Should not occur given Step 3 of Tier 5 ran.

## Tier 6 — Completion PR open + fail-open

After Tier 5.6, `tp/{slug}` carries the folded code + propagated docs + the archived design. Tier 6's job is to push `tp/{slug}`, open the **completion PR** (`tp/{slug} → {default}`) with a structured description, and exit cleanly. There is no separate `final/{slug}` branch — `tp/{slug}` *is* the PR branch. The `--require-pr-confirm` operator-gate is a deferred feature (see ## Deferred features below).

### Step 1 — Ensure pushed

```
git push origin tp/{slug}
```

Pushes the post-fold, post-archive `tp/{slug}` (the fold-merge + `Complete design:` commits from Tier 5.6). Idempotent if already pushed.

#### Tier 6 — legacy fallback (fold conflict)

If Tier 5.6 Step 1 hit a fold conflict and aborted, the candidate code is **not** on `tp/{slug}`. In that case ONLY, Tier 6 opens the legacy **candidate→tp PR** instead (`--base tp/{slug} --head candidate/{slug}/single`) so the human can resolve the conflict there, and the design is **not** archived (it stays in-flight). This is the pre-merged-design-closeout terminal, retained purely as the conflict escape hatch. The normal path is the completion PR below. Its PR body tells the human, after resolving the conflict, to run `python3 "$CL" issues apply --pending {design}/certifications/records/known-issues.pending.md --known-issues three-pillars-docs/known_issues.md` (`$CL` per ## Tier 5 Step 2b), since Tier 5.6 applies only on a clean fold.

### Step 2 — `gh pr create` + partitioned review request (F2)

The orchestrator opens the PR **and then summons review itself** — a PR with no reviewer requested is a loop that has nothing to classify (F2, pr-fix-targeting-and-auto-review). `--pr-reviewers` defaults to `"copilot-pull-request-reviewer[bot]"`; `--no-review` suppresses all review requests. **Tier 6 is the sole initial completion-PR review requester in the autonomous path.** (Cross-ref: `tp-design-complete/SKILL.md` `## Auto Mode` — under `--auto`, `/tp-design-complete` defers the review request to Tier 6 and logs `review-request-deferred-to-tier-6`; Tier 7 / `/tp-pr-iterate` re-requests per round, idempotent — re-fires only on a new head SHA, fail-open.)

**Partition the reviewer list before requesting** — GitHub's Copilot bot is not requestable through the same path as human logins:

```python
COPILOT_SLUGS = {"copilot-pull-request-reviewer[bot]", "copilot", "copilot[bot]"}
reviewers = [] if opts.no_review else opts.pr_reviewers.split(",")
humans = [r for r in reviewers if r.strip().lower() not in COPILOT_SLUGS]
bots   = [r for r in reviewers if r.strip().lower() in COPILOT_SLUGS]
```

**Create the PR** through the shared PR-author chokepoint (`skills/_shared/github_pr_author.py` — unconfigured repos run the identical `gh pr create` underneath, byte-identical to before; request the human reviewers inline, drop `--reviewer` entirely when `humans` is empty — `gh pr create --reviewer ""` errors):

```
# Resolve the FREE chokepoint git-toplevel-first (see first-run.md §Resolve a FREE _shared script)
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
GHPA="$(python3 "$RS" github_pr_author.py)" || exit 1
[ -n "$GHPA" ] || exit 1
python3 "$GHPA" create --context autonomous -- \
  --base {default} \
  --head tp/{slug} \
  --title "{slug}: {task_metadata.title}" \
  --body "$(structured PR description)" \
  [--reviewer "<comma-joined humans>"   # only when humans is non-empty]
```

`{default}` is the repo's base branch (usually `master`) — the **completion PR** merges the now-closed design (`tp/{slug}`, carrying folded code + propagated docs + archived design) back to the base. This replaces the pre-merged-design-closeout candidate→tp PR; the only time a candidate→tp PR is opened now is the fold-conflict fallback above.

**Request the Copilot bot via REST** (after the PR exists; resolve `{n}` from the created PR URL) — this is the known-good path. Do **not** use `gh pr edit` with the add-reviewer flag: on a repo with classic Projects enabled that route fails with a GraphQL `Projects (classic) … deprecated` error before the reviewer is added, whereas the REST `requested_reviewers` endpoint below resolves the Copilot bot reliably. Use:

```
gh api repos/{owner}/{repo}/pulls/{n}/requested_reviewers \
  -f 'reviewers[]=copilot-pull-request-reviewer[bot]'
```

**Fail-open (load-bearing):** a non-zero exit from *either* the human `--reviewer` add or the Copilot REST request must **not** fail the run — the PR already exists. Log one block to `decisions.md` and continue:

```
[tp-run-full-design/tier-6] review-request-failed
**Reviewers attempted**: <list>
**Cause**: <gh stderr>
**Confidence**: Medium
```

A successful `gh pr create` followed by a failed review request is still a Tier 6 success (exit 0). Pairs with `copilot-review-custom-instructions` (the `.github/copilot-instructions.md` that makes the requested Copilot review produce convention-aware comments instead of no-ops).

`{base}` is `{default}` and `{head}` is `tp/{slug}` — the **completion PR**. The diff is the design's full work: the folded candidate code (Tier 5.6 Step 1) plus the design-pipeline artifacts + propagated docs on `tp/{slug}`, with the design dir already moved to `completed-tp-designs/` (Tier 5.6 Step 3). There is no candidate fork-point illusion to warn about — that was the old candidate→tp diff; the completion PR is an ordinary `{default}...tp/{slug}` diff. The fail-open compare URL below uses the same base/head.

The structured PR description embeds:
- Link to task source (from `pickup_contract.task_metadata.external_ref`).
- Candidate `summary` from the parsed response.
- `test_results.{passed,failed,skipped}` counts + a fenced excerpt of `raw`.
- Tier 5 verdict (PASS or PASS WITH NOTES; the notes inline if present).
- Tier 5 design-learn synopsis (one-paragraph what-changed).
- **Closeout status**: design archived to `completed-tp-designs/{slug}/`, plus the Tier 5.6 learn-verify result (any stale-ref flags inline, advisory).
- Explicit label: "produced by orchestrator MVP — single candidate, closed before merge". Reviewers understand the audit trail is shallower than a multi-candidate dossier will be, but the design is already closed out (learn + archive) — one merge lands it.

#### About this diff (completion PR)

Because Tier 5.6 folded the candidate into `tp/{slug}` *before* this PR, the diff is a normal merge-base→`tp/{slug}` view — no fork-point deletion artifacts. If the fold itself conflicted, Tier 6 took the legacy candidate→tp fallback instead (## Tier 6 — legacy fallback) and this completion PR was not opened. A reviewer who wants to confirm the eventual `{default}` merge is conflict-free can run `gh pr view {n} --json mergeStateStatus`; semantic merge conflicts are resolved by the human at merge time via `/tp-merge {slug}` (the merge-only gate), not here.

### Step 3 — Fail-open semantics (load-bearing)

If `gh pr create` fails — `gh` not installed, auth expired, network error, GitHub API rejection — Tier 6 **fails open**, mirroring the pattern from `skills/tp-design-complete/SKILL.md` step 6g. A helper exit code of **3** (`BotAuthUnavailable` — the configured `github.pr_author_account` bot is unavailable in the `gh` keyring) is ONE specific `gh pr create` failure cause; take the same fail-open path below but log it under its OWN decisions token `bot-auth-unavailable`, distinct from `gh-pr-create-failed`, so a misconfigured bot is never conflated with a benign gh/network cause:

1. Append a Medium-confidence decisions.md entry:
   ```
   [tp-run-full-design/tier-6] gh-pr-create-failed
   **Cause**: <gh stderr or exception>
   **Compare URL**: https://github.com/{owner}/{repo}/compare/{base}...{head}?expand=1
   **Confidence**: Medium
   ```
2. Print the compare URL to stdout so the operator can manually open the PR via web:
   ```
   https://github.com/{owner}/{repo}/compare/{default}...tp/{slug}?expand=1
   ```
3. **Exit 0** — the orchestrator's exit code MUST reflect "delivered, awaiting manual PR" not "failed". This is mandatory: the candidate branch is on origin and the work is preserved; any CI or downstream tool watching the orchestrator's exit code should treat this run as a successful delivery with a manual-PR-needed flag, not as a failure to retry. **Do NOT exit non-zero on a `gh` failure**; do NOT retry `gh pr create` (only Tier 3+3.5 retries via `--max-attempts`); do NOT fall through to ## Cleanup's abnormal-exit branch. Exit 0, return success, orchestrator exit code 0.

The grep anchor `exit 0` on this paragraph is testable; do not remove the literal phrasing.

### Step 4 — Vision deviation acknowledgment (silent mutation)

This step intentionally violates vision.md's non-goal "Not a tool that silently mutates user work" — see design.md §Behavior 6 deviation paragraph. The deviation is bounded by two stronger commitments preserved at the *outcome* level:

- **Auto-merge is never in scope.** The PR exists; a human must merge. The orchestrator opens but does not close.
- **The PR description + decisions.md form the proposal artifact** the human reviewer reads before merging. The audit trail is the deviation's compensation.

If an operator prefers a pre-PR confirmation gate for high-stakes runs, the deferred `--require-pr-confirm` flag (## Deferred features) will add that gate without changing the default behavior.

### Tier 6 outcomes

- **`gh pr create` succeeds** → decisions.md entry `[tp-run-full-design/tier-6] pr-opened {pr-url}`, then **proceed to Tier 7** (unless `--no-iterate`/`--no-review`, in which case Tier 6 is terminal and the run exits 0).
- **`gh pr create` fails** → exit 0 (fail-open), decisions.md entry `[tp-run-full-design/tier-6] gh-pr-create-failed`, compare URL printed. Tier 7 is skipped (no PR to iterate).
- **Push itself fails** (rare — Tier 3.5 already verified origin has the candidate) → exit non-zero, abnormal cleanup.

### Deferred features

- `--require-pr-confirm` — pre-PR operator gate. Trigger to land: first user request or first under-reviewed-PR incident.
- `--dry-run` report formatter — operator UX. Tracked as D12.1 follow-on.

## Tier 7 — PR-iterate (review loop to reviewed-stable)

Tier 6 opens the PR and requests a review; **Tier 7 drives that review to a stable state** so a run ends at a reviewed-stable PR rather than a fresh one. This is the orchestrator *incorporating* `/tp-pr-iterate` directly — not chaining it at a downstream launch layer. It is **on by default**; `--no-iterate` (and `--no-review`, which implies it) skips it.

Folding the loop into Tier 7 (not a fleet-layer `… && /tp-pr-iterate` chain) makes *every* invocation — direct, interactive-fleet, or headless-fleet — converge the same way, and lets the fleet emit the bare `/tp-run-full-design … --skip-design` command for all worker forms (no `&&` chain).

### Step 1 — Orchestrator-owned round loop (Slot 11)

**The orchestrator drives `run_round` iteration-by-iteration at top level** — it does NOT delegate the whole loop to one Slot 11 subagent. This is the B1 fix: a Slot 11 subagent cannot dispatch the per-head ANGLES fan-out (L23 single-level limit), so the loop must live at the orchestrator where fan-out is legal.

Each round follows `skills/tp-pr-iterate/round-topology.md` (details and recovery):

1. **Prepare + fan out.** `git fetch origin {default}`; `review_base` is the base-branch tip, re-fetched every round. Run `round_scratch.py prepare` (under `default_proof_root()`) → round dir `R`; its `angles.json` manifest is the path authority. Fan out the `ANGLES` set as N top-level `general-purpose` sub-agents, each pinned `model="opus"` (reviews always Opus; L23-safe at top level), one per manifest angle with its manifest prompt; each writes its full reply to its own `reply_path` and returns one line (a missing reply reads as the fail-closed sentinel).
   - **Round tail.** Then dispatch one Opus round-tail sub-agent **without** worktree isolation: it runs in the orchestrator's own `tp/{slug}` checkout while the orchestrator is idle, and is the loop's one working-tree writer (it never checks out; it commits only its derived paths). It runs `reproduce.py --round-dir R --cwd . --head <head>` (merges the replies via `merge_codereview_angles`, runs each blocking finding's reproducer). A clean round finishes (two-stable) with `converge.py --round-dir R`; otherwise it runs `capture_proof` and `post_codereview_comment` (mandatory, no silent reviews), then step 2.
2. **Shell out the round decision** — NOT an in-process call. Run:
   ```
   python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/run_round.py
   ```
   with a JSON object on stdin carrying: `state_path`, `head_sha`, `codereview_findings` (the fan-out or cached value), `reviewed` (`copilot_reviewed_successfully(pr_url)`), `unresolved_actionable`, `ci_rollup` (the most-recent `statusCheckRollup` from `_ci_settled_on_head`), `config` (the repo's `.three-pillars/config.json` contents — **must be passed explicitly** so `review.expects_copilot=false` and `ci.expects_github_checks=false` are honoured; omitting it defaults to both `true`, which blocks code-review-only convergence on repos without Copilot), `review_proof_root` (the gitignored proof dir from `default_proof_root()` — **always pass this**; absent on a convergence-eligible round fails closed with `proof_enforced=False` in the envelope), `review_base` (the base-branch tip, re-fetched every round — the gate re-runs the diff as a provenance check), and the round bookkeeping from the manifest (`pr_url`, `round`, `ordinal`, `class_log_path`, and `decisions_path` = the manifest's loop log). The wrapper reads + writes `iterate-state.v1.json` and emits a single-line JSON envelope. **Resume is in-worktree, not cross-clone**: every state path in use is gitignored and no code path commits the state, so a resumed loop recovers from a process crash inside a live worktree — a genuinely *committed* per-round state is the intended contract, not one any current code performs (see `tp-pr-iterate/SKILL.md` §Cold-resume contract). An absent state file is the documented **start condition**: `run_round.py` bootstraps a schema-valid round-0 state and proceeds (`state_bootstrapped: true`), reserving `state-read-failed` (exit 2) for the **unreadable** cases: content that is not a JSON object, a **dangling symlink** (`Path.exists()` says absent, but the seed still refuses to write through the link), or a **non-regular** node (FIFO, socket, directory — including one reached through a symlink). Note that "exists with content" is the wrong test in both directions: a FIFO, socket, directory or `/dev/null` all exist with *no* content and still exit 2, while a dangling symlink exits 2 though `Path.exists()` is False. A **zero-length** *regular* state file counts as absent and is re-seeded, because it is the residue of a crash mid-seed and refusing it would wedge every later round. **Serial callers only**: two bootstraps racing on ONE `state_path` are **not supported** — a claim still in flight is also 0 bytes, so a racing round cannot tell it from crash residue, re-seeds it, and the last write wins. What is silently lost is the losing round's accumulated state: `transitions`, `last_codereview_head_sha` / `last_codereview_findings` (the currency fields the independent-review conjunct reads) and `degraded_review_retries`. So is `iteration`, since the round-budget tick increments it every counted round (the cap in step 4). A fleet that runs loops in parallel must give **each loop its own `state_path`**. An empty/zero-line diff or missing artifact → `proof_ok=False` → `blocked-no-independent-review`.
3. **Inline fix (in the round tail).** If `action == "fix"`, the tail runs the reduced `/tp-pr-fix` form: `fix_round.run_round(…, loop_mode=True, paths=…)` with `paths` from `tree_scope.derive_fix_paths`, committing only those paths and pushing a new head to `tp/{slug}`. It writes `R/tail/envelope.json`; the orchestrator runs `round_scratch.py tail-check --round-dir R` (missing/invalid → `tail-failed`, needs-human-attention) and re-fans-out on the new head.
4. Loop until the envelope reports a `terminal` phase:
   - `"two-stable"` / `"two-stable [code-review-only]"` (`converged: true`) → PR reviewed-stable. The `converge.py` finisher posts the trusted proof digest as the LAST head-binding action, then shells `run_round.py`.
   - `"blocked-no-independent-review"` (`converged: false`) → **terminal** (not a keep-looping yield). No independent review ran for the current head; `tp:needs-human-attention` is applied and the loop stops.
   - **Round budget (the cap).** `run_round` calls `round_budget.tick` every round: blocking findings at `iteration >= round_cap` stop as `budget-exhausted` (also growth, test/code ratio, `budget-error`; wall clock → `cap-exhausted`; k-consecutive → `convergence-failure`). Report every `holding` signal; to recover, raise `pdw.guards.round_cap` (or the named limit) in `.three-pillars/config.json`, leave it uncommitted, and re-run. Outcome `pr-iterate-budget-exhausted`.
   - **Terminal log flush.** At every terminal, `round_scratch.py flush` appends the loop log to `decisions.md`. At `two-stable` it is committed locally and **not pushed** (an exception to commit-then-push, because a push would move the PR head). Every other terminal's report names `decisions.md` as modified and uncommitted (flushed, left dirty so `HEAD` stays the PR head for a re-run).

**The loop is dual-source — it never depends on Copilot alone.** On a repo that declares `review.expects_copilot=false`, the two-stable terminal drops the Copilot conjunct and converges on the `/code-review` arm alone. Do **not** short-circuit Tier 7 because Copilot did not post — run the loop and let the `/code-review` arm carry it.

State is persisted by `run_round.py` each round, so a crash between rounds is resumable from the written state file (in-worktree — the path is gitignored; see the resume caveat above).

### Step 2 — Clip + log

The slot returns a **generator-return** envelope summarizing the loop: rounds run, the terminal (`two-stable` ⇒ converged, a budget terminal ⇒ `budget-exhausted`, else `cap-reached`), and the final head SHA. The orchestrator clips it (## Return clipping) and logs `[tp-run-full-design/tier-7] pr-iterate-{converged|budget-exhausted|cap-reached} {pr-url}`.

**Base-moved during the loop.** If the completion PR goes `mergeStateStatus: DIRTY`/`BEHIND` mid-iteration (another PR merged to `{default}` and the branch now conflicts — typically on the shared living docs), the `pr-iterate` slot must resolve it by running **`/tp-merge-from-main {slug}`** (base-into-branch, zero-drop verifier, semantic deferral, re-test, re-push) — **never a free-hand `git merge`**, which skips the verifier and risks a silent content-drop. This is the same base-sync rule `/tp-pr-iterate` carries (see its "Failure modes" → *Base moved under the PR*). Syncing the base *into* the branch is reversible and below the gate; landing the PR (the `/tp-merge` land gate, next paragraph) is the human's.

### The merge-only gate (load-bearing)

Tier 7 **iterates and pushes fix commits; it NEVER merges.** A human reviews the reviewed-stable PR and then triggers the merge by running `/tp-merge {slug}` — the land gate, which calls `require_merge_gate_pass` (the deterministic gate's five predicates, including a current human approval) and performs the irreversible `gh pr merge` ONLY on PASS, refusing on a blocked gate. (A moved base is synced first with `/tp-merge-from-main {slug}`.) The orchestrator never hand-merges and never auto-merges. This is consistent with the standing merge-only gate: autonomous through push + PR + review-response, paused before the `/tp-merge` step. A non-converged loop (cap-reached, or persistent structural findings) is **reported, not escalated past the gate** — the operator reviews the PR as usual; the work is durable on the candidate branch regardless.

### Tier 7 outcomes

- **Converged** (`two-stable` or `two-stable [code-review-only]`) → decisions.md entry `[tp-run-full-design/tier-7] pr-iterate-converged {pr-url}`; exit 0. The PR is reviewed-stable, awaiting human merge.
- **Blocked — no independent review** (`blocked-no-independent-review`) → **terminal** (`converged: false`: no real ANGLES fan-out ran for the current head; `tp:needs-human-attention`). Report as `pr-iterate-cap-reached` (blocked, non-converged). **Convergence is byproduct-only + proof-bound (review-integrity-enforcement):** `run_round.py` emits `converged=true` only as a byproduct of a two-stable terminal bound to the shared `convergence_proof.non_degraded_proof_on_head` predicate (the merge gate's own); a degraded/absent proof-on-head or an unparseable/NO-ANGLES angle blocks with a `not_converged_reason` and increments the committed `degraded_review_retries` counter (default bound 1). On a `not_converged_reason`, re-run the review on head (re-`capture_proof` + re-`post_codereview_comment` with a fresh digest) then re-shell `run_round.py`; at the bound, record not-converged + escalate. Full contract: `tp-pr-iterate/proof-of-review.md` → *Convergence action contract*.
- **Budget exhausted** (`budget-exhausted` / `cap-exhausted` / `convergence-failure` from `round_budget.tick`) → `[tp-run-full-design/tier-7] pr-iterate-budget-exhausted {pr-url}`; exit 0. Reported with every `holding` signal and `decisions.md` as modified and uncommitted; not escalated.
- **Loop non-start** (e.g. `gh` down, PR already closed before the first round) → log `[tp-run-full-design/tier-7] pr-iterate-noop {pr-url}`; exit 0 (fail-open). **A Copilot review that never attaches is NOT this case** — the `/code-review` arm is still a review source; the loop runs and converges (or hits a cap). Reserve `pr-iterate-noop` for a genuine non-start, never for "Copilot was absent."
- **Every terminal outcome above** also shells `sweep_orphan_branches.py` once, after Tier 7 completes — the same `worktree-agent-*` orphan-branch reclaim as the `## Cleanup` step, on the normal clean-exit path.

## Branch hygiene — the orchestrator worktree stays pinned on `tp/{slug}` (load-bearing)

The orchestrator runs in **one worktree, checked out on `tp/{slug}` for the entire run**, and that invariant must hold across every slot dispatch and every orchestrator commit. Violating it orphans commits — the concrete failure mode observed in practice:

> A slot subagent that did `git checkout candidate/{slug}/single` **in the orchestrator's shared worktree** (to run a regression suite) moved the orchestrator's HEAD onto the candidate branch. A subsequent orchestrator commit then landed on the candidate branch instead of `tp/{slug}`; when a later slot checked back out to `tp/{slug}`, that commit was orphaned (reachable only by SHA).

Three rules prevent it:

1. **The candidate branch is remote-only to the orchestrator.** After Tier 3.5 the candidate lives at `origin/candidate/{slug}/single`. The orchestrator **never checks it out** in its own worktree. It inspects the candidate read-only via `git show origin/candidate/{slug}/single:<path>`, `git diff tp/{slug}...origin/candidate/{slug}/single`, `git log origin/candidate/{slug}/single` — never `git checkout`/`git switch`. **The one permitted write-integration is the Tier 5.6 fold** (`git merge --no-ff origin/candidate/{slug}/single`): a merge *into* the currently-checked-out `tp/{slug}` keeps HEAD on `tp/{slug}`, so it does not drift HEAD and does not orphan commits. The hazard this rule prevents is *checkout/switch onto the candidate*, not *merge the candidate in* — those are categorically different. (A fold conflict aborts via `git merge --abort`, which also leaves HEAD on `tp/{slug}`.)
2. **Any slot needing the candidate's *working tree* (regression test) runs with `isolation="worktree"`** so its checkout/commits land in *its* worktree. The read-only audit fan-out sub-dispatches (Slots 4/6/8) may share `tp/{slug}` precisely because they only `git show`/`git diff` and never checkout; the worker (Tier 3) and the regression check (Tier 5 Step 1) **must** isolate. The one exception is the Tier 7 round tail: it is the one working-tree writer on the orchestrator's own `tp/{slug}` checkout, which it never checks out away from, with the orchestrator idle, committing only its derived paths.
3. **Assert before every orchestrator commit.** Immediately before any `git commit` the orchestrator runs `git symbolic-ref --short HEAD` and verifies it equals `tp/{slug}` (not detached, not `candidate/...`). If it does not, the orchestrator `git checkout tp/{slug}` first and logs `[tp-run-full-design/branch-hygiene] head-reattached {prev-ref}`. A commit is never made on a drifted HEAD.

Recovery, if an orphan nonetheless occurs: the commit stays reachable by SHA (`git log <sha>`), and a **path-scoped** `git checkout <sha> -- <path>` restores its tree onto `tp/{slug}` (safe because the orchestrator is not mid-merge — cf. the never-`git checkout <ref> -- .`-mid-merge rule). Re-commit on `tp/{slug}`.

## Token budget

`--max-tokens N` is a single **whole-run** cap, not per-tier (per detailed-design.md §Decisions OQ6). Token usage accumulates across all tiers; the cap is checked at each **tier boundary** — entry to `## Tier 2`, `## Tier 3`, `## Tier 3.5`, `## Tier 5`, `## Tier 6`. There is no mid-tier check.

### Tier-boundary check (the only abort point)

Before entering each tier, sum the tokens consumed so far. If the running total ≥ `--max-tokens`:

1. Append a decisions.md entry tagged with the tier the orchestrator was *about to enter*:
   ```
   [tp-run-full-design/tier-N] token-cap-abort
   **Usage**: <running-total>
   **Cap**: <--max-tokens value>
   **Skipped**: <tier-N and everything downstream>
   **Confidence**: High
   ```
2. Exit non-zero cleanly — the candidate branch (if Tier 3.5 already wrote artifacts) stays on origin; the lock is released; no PR opens.
3. The terminal entry's `tier-N` prefix names the tier that would have run next, so a grep for `tp-run-full-design/tier-` over decisions.md after a cap-abort identifies the abort point.

### No mid-tier abort

A tier in flight finishes — the orchestrator waits for the in-flight skill or subagent to return, *then* checks the cap and aborts at the next boundary. The reasoning: each **individual phase dispatch** is the atomic unit — interrupting a phase mid-execution leaves partial state that's harder to reason about than spending the few extra tokens to complete the unit and abort cleanly at the boundary. Operators who need a harder cap should set `--max-tokens` lower than the expected unit cost, not expect mid-tier preemption.

### `--max-wall-clock` is independent

`--max-wall-clock SECS` is checked at the same tier boundaries with the same abort semantics, using `[tp-run-full-design/tier-N] wall-clock-abort` as the decisions.md tag. The two caps are independent — hitting either aborts; neither is derived from the other.

## SIGTERM graceful abort

A mid-run `SIGTERM` (operator interrupt of the orchestrator, host shutdown, CI timeout signal) aborts the run on the **same boundary-only discipline** as the token-cap and wall-clock aborts (## Token budget): the orchestrator never kills an in-flight dispatch. There is **no mid-tier / mid-slot kill** — a slot subagent already running is allowed to return, and the orchestrator stops dispatching **at the next slot boundary** (consistent with ## No mid-tier abort).

On receipt of SIGTERM the orchestrator:

1. Sets an abort flag and stops scheduling new slot dispatches. The currently in-flight slot (if any) finishes at its own boundary; the orchestrator does not interrupt it mid-flight — interrupting a slot leaves partial state that is harder to reason about than the few extra tokens spent letting the unit complete.
2. Leaves all durable state in place — committed design artifacts, any pushed candidate branch on `origin/`, and the committed `.handoffs/{slot}-{attempt}-{N}.md` worklist (## Handoff protocol — pre-split (M2)). These are kept **durable** precisely so a later `/tp-run-full-design {slug}` can **cold-resume** from the last committed checkpoint rather than restarting the tier.
3. Appends a categorized `[tp-run-full-design/tier-N] sigterm-abort` entry to `decisions.md` — tagging the slot the orchestrator was about to dispatch, mirroring the `token-cap-abort` / `wall-clock-abort` tokens so a grep over `tp-run-full-design/tier-` identifies the abort point — then runs ## Cleanup (release or hand back the lock; never `git reset --hard` or drop a remote ref).
4. Exits cleanly. The exit reflects an interrupted-but-resumable run, not a crash: nothing is half-written because the abort lands only on a boundary.

The guarantee is symmetric with the rest of the abort model — artifacts + `.handoffs/` stay durable, the lock is handed back, and a subsequent invocation cold-resumes from where the SIGTERM landed.

## Retry & max-attempts

`--max-attempts N` (default `3`) is the **worker** retry budget — it retries **Tier 3 + 3.5** on a malformed structured response. It does NOT retry Tier 6's `gh pr create`. It is the *same flag* that bounds audit retry-with-advice (## Retry-with-advice (audits)), but the two use **independent counters** (worker-retry here; per-audit-cycle there) — this section governs only the worker. A malformed JSON block on attempt N is plausibly transient, the hiccup this default absorbs.

### Retry-eligibility table (gated by failure class)

The five worker-contract failure modes from detailed-design.md §Error Semantics map to retry vs. escalate as follows:

| Case | Source | Retryable? |
|---|---|---|
| (a) no-op (`worktreePath` absent) | Tier 3.5 short-circuit | **No** — escalate immediately |
| (b) `NoCandidateBlockError` or `UnknownSchemaVersionError` | `parse_candidate_response` | **No** — escalate immediately (worker ignored the contract) |
| (c) `SchemaValidationError` | `parse_candidate_response` | **Yes** — retry up to `--max-attempts` |
| (e) sha-mismatch | Tier 3.5 SHA cross-check | **No** — escalate immediately (environmental, not worker fault) |
| (f) rerun-failed | Tier 3.5 phase re-run | **No, escalate (v1)** |

Only (c) is retryable. The others are structural or environmental — a retry won't change the outcome and just burns tokens; an (f) retry would also inherit the pushed red commits.

### Retry loop

The retry loop operates **per phase** — each plan phase N runs its own retry loop bounded by `--max-attempts`. The worker counter resets per phase entry (see ### Counter-reset rule below).

```
for N in plan_phases:          # outer per-phase loop (Slot 7)
  attempt = 1                  # counter resets per phase dispatch
  while attempt <= --max-attempts:
    run_tier_3(phase=N)        # spawns the worker Agent for phase N
    result = run_tier_3_5(phase=N)  # parse → write → cleanup → sha-check
    if result.success:
      break
    if result.case in {a, b, e, f}:
      escalate(result)
      exit_nonzero()
    # case (c) — retryable
    append_decisions_log(f"[tp-run-full-design/tier-3.5] retry attempt {attempt}/{--max-attempts}")
    attempt += 1
  if attempt > --max-attempts:
    append_decisions_log("[tp-run-full-design/tier-3.5] retry-exhausted")
    escalate(result)
    exit_nonzero()
```

After exhaustion (N > `--max-attempts`), escalate the last failure's case + details.

### Distinguishing case (e) from retries under the same tier prefix

Both retry-attempt entries and case-(e) sha-mismatch escalations live under the `[tp-run-full-design/tier-3.5]` prefix. The **event-type token** after the prefix is the disambiguator and must be stable across orchestrator versions:

- `retry attempt N/M` — retry-eligible failure on attempt N (case c only); `retry-exhausted` — final escalation after `--max-attempts` retries
- `sha-mismatch <slug>:<parsed_sha>:<remote_sha>` — case (e), environmental; `no-candidate-block` — case (b); `worker-noop` — case (a); `rerun-failed <task:node …>` — case (f); `task-env-error <task_id>` — a `task_tiers` record ended `env-error`. All non-retryable.
- informational, never a case: `worktree-cleanup-locked` and the re-run's `rerun-skipped`, `rerun-phase-unverified`, `rerun-unverified <n>`, `files-escape-logged` (exit 0)

A grep over decisions.md for `[tp-run-full-design/tier-3.5]` returns the full Tier 3.5 history; the second token classifies (OQ5).

### Counter-reset rule

The **worker** attempt counter is reset to 1 at the start of each phase dispatch — Phase 1's exhausted retries do not eat Phase 2's budget. It is scoped per-phase-dispatch invocation and is **never shared** with the audit retry-with-advice counters (those are per-audit-cycle; ## Retry-with-advice counter) or with Tier 6 (which has no retry mechanism). The counter is also not shared across orchestrator runs: a fresh `/tp-run-full-design {slug}` invocation always starts at attempt 1.

Why this matters: a future operator might assume `--max-attempts 3` means "three retries shared across the whole pipeline." It does not. The budget is applied **per self-healing loop, independently**: the worker tier (this section) and each audit cycle (## Retry-with-advice counter) each get their own fresh count of up to `--max-attempts` per orchestrator run. They never draw down a shared pool.

### Interaction with `--max-tokens`

Retries consume tokens. Each retry's tier-boundary check (## Token budget) sees a higher running total; if the cumulative usage crosses `--max-tokens` mid-retry-loop, the next tier-boundary token-cap-abort wins over the retry. The cap is the harder constraint. This means a worker stuck in retryable failures (case c/d) on a tight token budget will be killed by `--max-tokens` before exhausting `--max-attempts` — the design is intentional.

## Retry-with-advice (audits)

This is a **distinct mechanism** from ## Retry & max-attempts (which retries the *worker* on a malformed structured response). Retry-with-advice handles an **audit slot** (`design-audit`, `plan-audit`, `impl-audit`) that returns a `needs-work` verdict: rather than escalating, the orchestrator re-runs the *generator* that produced the rejected artifact, hands it the audit's findings as advice, and lets the audit re-judge — the core of the self-healing flow.

### When it fires

It fires **by default** on every audit `needs-work` verdict (`--max-attempts` defaults to `3`):

- **Every finding drives a re-spawn — high, medium, and low confidence alike** (except `category: "map-check"` — see the exemption below). Confidence does not gate retry-vs-escalate; it is carried into the advice so the generator knows how sure the audit was, but even an uncertain finding gets an automated attempt before a human is involved. (Setting `--max-attempts 1` disables the loop and restores escalate-on-first-rejection.)
- The loop runs until the audit **passes** (advance) or the per-cycle budget is **exhausted** (escalate — ## Retry-with-advice escalation). The audit gate itself is never bypassed: a re-judged artifact must actually PASS to advance. **Map-check exemption:** a finding with `category: "map-check"` (Slots 4/6, state-space Check mode) questions design.md's own framing, which no generator re-spawn may revise — it is **never** re-spawn advice. Check for it on **every** audit return, before looking at the verdict: if any is present, whatever the verdict or confidence, do not retry (not even the other findings — design.md must change first) and escalate at once via the map-check trigger of ## Retry-with-advice escalation.

### File-reference re-spawn

The orchestrator re-spawns the **upstream generator** slot for the rejected artifact — `design-audit` → re-spawn `detail` (or `design`); `plan-audit` → re-spawn `plan`; `impl-audit` → finding→phase mapping below. The re-spawn prompt is a **file-reference**, not an inline re-paste of the artifact:

- It passes the **path** to the prior artifact the generator already wrote (e.g. `three-pillars-docs/tp-designs/{slug}/plan.md`) and tells the re-spawned subagent to read it and revise in place.
- It passes the audit's findings (each tagged with its confidence) wrapped as advice ("you produced `<path>`; address these findings: …"), sourced from the clipped `audit-return` envelope's `findings[]`.

**`impl-audit` finding→phase mapping (Behavior 3):** When `impl-audit` returns `needs-work`, the orchestrator does **not** re-run all phases. Instead:

1. Each finding in the `audit-return` `findings[]` carries the file path(s) it flags.
2. The orchestrator maps each flagged file → the plan phase that **committed** it on `candidate/{slug}/single`, using `git diff --name-only` between each phase's base SHA and tip SHA (recorded in the per-phase `candidate.v1` envelopes / `decisions.md` entries).
3. Re-dispatch **only those phase(s)** whose touched files intersect a finding, passing the findings as advice. Phases with no flagged files are not re-run — their committed work stands.
4. **Ambiguity fallback**: if a finding's file cannot be mapped to a single phase (touched by multiple phases, or absent from all phase commit sets), fall back to a **full re-run** for that finding only and append `[orchestrator/impl-audit] phase-map-ambiguous <file>` (Confidence: Low) to `decisions.md` for AM review.
5. Re-dispatch obeys the per-phase worker counter (### Counter-reset rule) bounded by `--max-attempts`; the impl-audit retry-with-advice cycle counter (## Retry-with-advice counter) is the outer bound. The two counters stay independent.

This is the spike-validated shape (detailed-design §Decisions "Re-run prompt = file-reference"): the file-reference is cheaper than re-pasting the artifact inline into the prompt, and the spike observed no flaw-regeneration from withholding the inline copy. After the generator re-spawn returns, the orchestrator re-dispatches the **same audit slot** to re-judge; the cycle repeats until the audit passes or the attempt budget is spent (see ## Retry-with-advice counter).

## Retry-with-advice counter

Each audit slot that enters retry-with-advice runs its own **per-audit-cycle** attempt counter:

- The counter is **reset to 1 at the start of each audit cycle** — each time the orchestrator first dispatches a given audit slot (`design-audit`, `plan-audit`, `impl-audit`). A cycle is one audit slot's full retry loop.
- It is **never shared** across audits (the `plan-audit` counter is independent of `design-audit`'s), **never shared** with the worker-retry counter (## Retry & max-attempts), and never carried across orchestrator runs.
- It is **bounded by `--max-attempts`**: per cycle, the generator is re-spawned at most `--max-attempts − 1` times (attempt 1 is the original audit; each later attempt is one generator re-spawn + one audit re-judge). When the budget is spent and the audit still returns `needs-work`, the orchestrator stops and escalates (## Retry-with-advice escalation).

Each attempt appends an `[orchestrator/<audit-slot>] retry-with-advice attempt N/M` entry to `decisions.md`, mirroring the worker-retry log shape so a grep over the prefix returns the full per-cycle history.

## Retry-with-advice escalation

Escalation is the **terminal fallback** — the orchestrator self-heals first and involves a human only when it cannot converge. Findings of **all confidences — high, medium, and low — are retried** (## Retry-with-advice (audits)); confidence is advice to the generator, not a gate that skips the retry.

There are exactly three escalation triggers in the audit loop — **budget exhausted** and **`certification-unverified`** below, and the **map-check trigger**: any `category: "map-check"` finding on an audit return, under any verdict, escalates immediately with no retry cycle (append `[orchestrator/<audit-slot>] map-check-escalated` with the findings, then leave lock + branch as-is exactly as for `retry-exhausted`):

- **Budget exhausted** — a cycle spends its per-cycle retry budget (## Retry-with-advice counter) and the audit still returns `needs-work`. The orchestrator appends `[orchestrator/<audit-slot>] retry-exhausted` with the residual findings to `decisions.md` and exits per ## Cleanup.
- **`certification-unverified`** — a Slot 4/8 fold with `verdict == unverified`, `tree_mutated`, `claimant-records`, `records-handoff`, or a certify.py exit ≠ 0 / incomplete `--out` (## Tier 5 Step 2b). Append `[orchestrator/<audit-slot>] certification-unverified`, add `tp:needs-human-attention` where a PR exists, exit per ## Cleanup; it is **never** re-spawn advice. Order on every audit return: map-check → `certification-unverified` → `status`.

This keeps the audit gate a true floor without "escalate immediately": the orchestrator never advances on a `needs-work` artifact and never auto-merges (a human reviews the final PR), but it exhausts its automated repair attempts before handing the problem to a person. The only rejections that escalate *without* a retry loop are the Shape A design-floor (## Tier 2 — "Audit rejection — self-heal, then escalate") and the map-check trigger, because in both the fix belongs in the human-seeded `design.md`, which a generator re-spawn cannot author; and `certification-unverified`, since a claim nobody could observe needs an operator, not a re-roll.

## Lock ownership

The orchestrator writes `owner: "orchestrator:<git-email>"` at lock-creation (runner's `git config user.email` prefixed with `orchestrator:`, per the `orchestrator-identity` design). `same_actor` in `skills/_shared/inflight_registry.py` collapses prefixed and bare forms so a human re-running over an orchestrator-held lock takes the Refresh path without `--force-takeover`. A mid-run `--force-takeover` is detected at the next tier-boundary lock-refresh, which then aborts.

## Cleanup

On any abnormal exit (token cap, validation failure, audit BLOCKED, worker non-retryable failure), the orchestrator MUST:

1. Append the terminal decisions.md entry classifying the exit.
2. Release the lock or hand it back to the prior owner (per `skills/_shared/collaboration.md` graceful-handoff).
3. Leave the candidate branch on `origin/` if any work was pushed (Tier 3.5 onward) — never `git reset --hard` or drop a remote ref. The work is the human reviewer's input even when the PR did not open.
4. Clean up worker worktrees per `skills/tp-run-full-design/scripts/cleanup_worker_worktree.py` (Tier 3.5's normal-path cleanup; this section enumerates the abnormal-path obligation), then `python3 "$TP_ROOT"/skills/_shared/task_verify.py sweep --design-dir three-pillars-docs/tp-designs/{slug}` (fail-open).
5. Shell `python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/sweep_orphan_branches.py` (fail-open — Option B backstop) to reclaim any lingering `worktree-agent-*` branch whose per-worker sweep (Task 1.2's Option A trigger) was skipped by this early abort or crash.
