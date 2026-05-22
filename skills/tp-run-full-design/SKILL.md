---
name: tp-run-full-design
description: "Autonomous full-design orchestrator. Drives the TDD pipeline unattended for a single task — pickup → design → worker → audits → PR — and produces a decision log for human review."
argument-hint: "{slug} [--pickup-skill <name>] [--task-id <id>] [--skip-design] [--max-tokens N] [--max-wall-clock SECS] [--max-attempts N=1] [--pr-reviewers <comma-list>] [--force-takeover]"
---

# tp-run-full-design — Autonomous Orchestrator (Mode A0, single candidate)

This skill drives the entire three-pillars TDD pipeline unattended for a single task. It composes the existing `--auto` skills via the same prose-orchestration pattern as `skills/tp-spike-auto/SKILL.md`: read each delegated SKILL.md and follow its `--auto` instructions in order, logging every decision to `decisions.md` per `skills/_shared/auto-mode.md`.

**Mode A0 — MVP scope**: Tier 1 (pickup) → Tier 2 (design pipeline) → Tier 3 (single worker Agent in an isolated worktree) → Tier 3.5 (validation gate on the worker's structured response) → Tier 5 (consolidation audits) → Tier 6 (PR open). Tier 4 (council over multiple candidates) is **out of scope for MVP** per design.md §Behavior 4 — adding it requires `/council` to gain a code-candidate evaluation mode, tracked as a follow-on design.

This orchestrator is **not itself an `--auto` skill** — it is the orchestrator *of* `--auto` skills. It does not expose `--auto` in its argument-hint, and framework invariant 24 (`--auto` ↔ `auto-mode.md` linkage) deliberately does not apply to this file. It does, however, write `[tp-run-full-design/tier-N]`-prefixed entries to `decisions.md` per the prefix convention adopted in detailed-design.md §Decisions (OQ5).

## Arguments

- `{slug}` (required) — kebab-case design name. Must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. Identifies the design directory `three-pillars-docs/tp-designs/{slug}/` and the branch `tp/{slug}`. Distinct from `--task-id` (see below): the slug is the in-repo key; `--task-id` is the opaque upstream reference (e.g., a Jira ticket or Linear issue ID).
- `--pickup-skill <name>` (optional) — the `/tp-pickup-*` skill providing the task. If omitted, the orchestrator falls back to reading an already-seeded `design.md` in the design dir (manual-pickup escape hatch).
- `--task-id <id>` (optional) — opaque upstream task identifier passed verbatim to the pickup skill (e.g., `JIRA-1234`, `LIN-456`, a Notion page ID). Required when `--pickup-skill` is provided; ignored in manual-pickup Mode B. The pickup skill uses `{task-id}` to look up upstream metadata; the orchestrator never interprets the value. Surfaced in the pickup contract as `task_metadata.external_ref` per design.md §Pickup contract.
- `--skip-design` (optional) — opt out of Mode C's interactive-design front-end. When neither `--pickup-skill` nor `--skip-design` is passed, the orchestrator enters Mode C (see ## Tier 1.5). With `--skip-design` and no `--pickup-skill`, the orchestrator behaves as Mode B (read an already-seeded `design.md`).
- `--max-tokens N` (optional) — whole-run token budget cap. See ## Token budget.
- `--max-wall-clock SECS` (optional) — wall-clock budget. Independent of `--max-tokens`.
- `--max-attempts N` (optional, default `1`) — Tier 3+3.5 retry budget on retryable worker-contract failures. See ## Retry & max-attempts.
- `--pr-reviewers <comma-list>` (optional) — passed verbatim to `gh pr create --reviewer ...` in Tier 6.
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

0. **Run first-run preflight** per skills/_shared/first-run.md.
1. **Validate `{slug}`** per `skills/_shared/validate-name.md` (must match `[a-z0-9-]+`).
2. Read project docs per `skills/_shared/read-project-docs.md` so each delegated tier inherits context.
3. Execute tiers 1 → 2 → 3 → 3.5 → 5 → 6 in order (Tier 4 is intentionally skipped for MVP — see ## Tier 4 below).
4. On any non-retryable failure, fall through to ## Cleanup and exit with the appropriate non-zero code (Tier 6 fail-open is the lone exception — see that section).

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

### Pickup contract v1 validation

The orchestrator validates the returned contract against this schema before doing any other work. The contract is JSON-shaped, **version 1**, and the validation rules are intentionally strict — a malformed contract aborts the run before Tier 2 spends tokens.

```json
{
  "version": 1,
  "slug": "kebab-case-design-name",
  "branch": "tp/{slug}",
  "dir": "three-pillars-docs/tp-designs/{slug}",
  "task_metadata": {
    "title": "Human-readable task title",
    "hypothesis": "What is unknown / what we want to learn",
    "external_ref": "Opaque pickup-skill-specific reference",
    "phase_hook": null,
    "writeup_hook": null,
    "escalate_hook": null
  }
}
```

Validation rules — each maps to an explicit failure mode:

- **`version` is required and must equal `1`.** The orchestrator refuses any contract whose `version` it does not recognize. Append `[tp-run-full-design/tier-1] unknown-pickup-version <value>` to decisions.md and exit non-zero. Forward-compatibility shims are deferred to a v2 design — never silently downgrade.
- **`slug`, `branch`, `dir`, `task_metadata`** are required top-level keys. Missing any → `[tp-run-full-design/tier-1] missing-required-field <key>` and exit non-zero.
- **`slug`** must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. Mismatch → `[tp-run-full-design/tier-1] invalid-slug <value>`.
- **`branch`** must equal `tp/{slug}` exactly. Mismatch (e.g., pickup skill returned a candidate branch by accident) → `[tp-run-full-design/tier-1] branch-slug-mismatch`.
- **`dir`** must equal `three-pillars-docs/tp-designs/{slug}` exactly and the directory must exist on disk.
- **`task_metadata.title`** is required and non-empty (used in the Tier 6 PR title).
- **`phase_hook`, `writeup_hook`, `escalate_hook`** may each be `null` or an opaque string. If `null`, the corresponding callback is omitted (fire-and-forget) and noted once in decisions.md as `[tp-run-full-design/tier-1] hook-omitted <hook-name>`. Per detailed-design.md §Decisions (OQ2), hook failures are Medium-confidence boundary events that **do not abort the run**.

### Lock + branch protocol

The pickup skill (Mode A) or the orchestrator itself (Mode B) acquires the design lock per `skills/_shared/collaboration.md`. The orchestrator is a distinct lock-owner identity — see ## Lock ownership.

After Tier 1 succeeds, the orchestrator is on branch `tp/{slug}` and the lock's `phase` field reflects the current tier (e.g., `phase: "tier-2"` once Tier 2 begins). Each subsequent tier refreshes `last_touched` and bumps `phase` as it enters.

### Tier 1 outcomes

- **Success**: pickup contract valid, lock held, branch checked out. Proceed to Tier 2.
- **Failure**: any validation rule above. Append the categorized decisions.md entry, exit non-zero. No partial state — Tier 2 never runs on an invalid contract.

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

Tier 2 drives the five design-pipeline skills in `--auto` mode, in order. Each writes `[<skill-name>]`-prefixed entries to `decisions.md` per `skills/_shared/auto-mode.md`; the orchestrator does NOT rewrite these entries — the native skill prefix is preserved, and only orchestrator-emitted entries use the `[tp-run-full-design/tier-N]` prefix.

```
/tp-design {slug} --auto
/tp-design-detail {slug} --auto
/tp-design-audit {slug} --auto
/tp-plan {slug} --auto
/tp-plan-audit {slug} --auto
```

### Per-skill semantics

Each delegated skill follows one of the three auto-mode shapes defined in `skills/_shared/auto-mode.md`:

- **`/tp-design --auto`** — **Shape A** (validator gate). Delegates to `skills/_shared/validate_design_floor.py`. Either PASS (proceed) or BLOCKED (a `design.md` floor violation — missing Problem/Vision-alignment/Scope/Behaviors). The orchestrator treats BLOCKED as a Tier 2 abort cause; see "Audit rejection" below.
- **`/tp-design-detail --auto`** — **Shape B** (generator). Produces `detailed-design.md` from `design.md` without user Q&A; every judgment call self-logs Confidence: High/Medium/Low. The orchestrator does not gate on Confidence here — generation always proceeds; Confidence: Low entries are informational and surface in the Tier 5 audit.
- **`/tp-design-audit --auto`** — **Shape C** (audit with confidence-based dispatch). High-confidence findings auto-resolve (the skill applies the fix); any **Medium or Low** finding escalates BLOCKED.
- **`/tp-plan --auto`** — **Shape B** (generator). Produces `plan.md` from detailed-design.md. Same gating semantics as design-detail.
- **`/tp-plan-audit --auto`** — **Shape C**. Same High-auto-resolve / Medium-or-Low-escalate semantics as design-audit.

### Audit rejection — escalate immediately

Tier 2 must escalate on audit rejection — there is no retry, no continue-on-warning option, and no override flag. This is the load-bearing safety floor; once it trips, the orchestrator stops and surfaces the rejection to a human.

On any audit rejection — **Shape A floor-validator BLOCKED** (from `/tp-design`) or **Shape C any-Medium-or-Low present** (from `/tp-design-audit` or `/tp-plan-audit`) — Tier 2 stops immediately, **does not proceed to the worker tier**, and:

1. Appends an entry to `decisions.md`:
   ```
   [tp-run-full-design/tier-2] audit-rejected
   **Cause**: <floor-validator | medium-low-confidence-findings>
   **Skill**: <which of the 5 raised the rejection>
   **Details**: <the rejection's verdict JSON or finding list>
   **Confidence**: High
   ```
2. Returns BLOCKED to the operator (exits non-zero from the orchestrator).
3. Leaves the lock + branch as-is so a human can pick up via `/tp-session-restore {slug}` and address the rejection without re-running pickup.

The rationale: a bad design produces a bad plan produces a bad implementation. The further Tier 2 progresses on a flawed design, the more tokens the worker tier wastes producing a candidate that the consolidation audit will reject anyway. The cost of an early Tier 2 abort is a few seconds of tokens already spent; the cost of pushing through to Tier 5 is the full design-pipeline + worker budget. Audit rejection is a load-bearing safety floor; do not soften it with retry logic — `--max-attempts` retries the *worker* (Tier 3+3.5), not the design (see ## Retry & max-attempts).

### Token-cap boundary check

Tier 2 checks `--max-tokens` at entry and after each of the 5 skill invocations (token boundary = skill exit). See ## Token budget for the abort semantics — Tier 2 does not implement its own logic.

## Tier 3

Worker (single candidate, isolated worktree). Tier 3 spawns a single worker subagent in an isolated git worktree, hands it the design + plan + an explicit artifact contract, and waits for the structured response that Tier 3.5 will validate.

### Worker Agent invocation

```python
worker_prompt = compose(design.md, plan.md) + explicit_artifact_contract

Agent(
  subagent_type="general-purpose",
  isolation="worktree",
  description="candidate/{slug}/single",
  prompt=worker_prompt,
)
```

`isolation="worktree"` is mandatory: it cuts a fresh git worktree under `.claude/worktrees/agent-<id>/` so the worker's `.git/index` is independent of the orchestrator's. The orchestrator's branch (`tp/{slug}`) stays clean while the worker commits on its own candidate branch. Note: the worker's auto-entry branch is `worktree-agent-<id>` (a Claude Code default, NOT the orchestrator's `tp/{slug}`), which is exactly why item 1 of the worker contract below requires an explicit `git checkout -b candidate/...` step — without it the worker would build on the auto-entry branch and the orchestrator would have nowhere clean to merge from. This is S13 finding F2; see `completed-tp-designs/agent-worktree-isolation-spike/d12-worker-contract-revision.md`.

### `explicit_artifact_contract` — 6 worker responsibilities

The contract appended to `worker_prompt` is a literal numbered list. Six items, in order, no negotiation:

1. **`git checkout -b candidate/{slug}/{candidate_id} {base-ref}`** — cut a fresh candidate branch off the orchestrator's base ref (typically `tp/{slug}` HEAD). Do NOT work on the auto-entry `worktree-agent-<id>` branch — the orchestrator cannot merge from there cleanly (S13 finding F2).
2. **Implement the plan literally on the candidate branch.** Follow `plan.md`'s task list in order. Each task is one red-green-refactor cycle and one commit on the candidate branch.
3. **Commit work on the candidate branch.** One commit per plan task. No `--no-verify`, no `Co-Authored-By` trailer, no `git add -A` — scope each commit to the files the task touched.
4. **`git push -u origin candidate/{slug}/{candidate_id}`** — push the candidate branch to origin. This is the boundary-crossing mechanism (S13 answer to Round 1 finding B2): once pushed, the candidate is durable even if the worker worktree is later cleaned up.
5. **Return a structured response** as the final answer text — a fenced JSON block in the exact shape below, with no content after it. This block is the orchestrator's ONLY input from the worker; anything else in the response text is treated as scratch.
   ```json
   {
     "schema": "tp-run-full-design/candidate/v1",
     "candidate_id": "{candidate_id}",
     "branch": "candidate/{slug}/{candidate_id}",
     "sha": "<git rev-parse HEAD>",
     "summary": "<short narrative — what was implemented, key tradeoffs>",
     "test_results": {
       "passed": <int>, "failed": <int>, "skipped": <int>,
       "raw": "<test-runner stdout, truncated to 4000 chars>"
     },
     "telemetry": {
       "duration_ms": <int>, "tokens_used": <int>, "tool_calls": <int>
     }
   }
   ```
6. **Do NOT write artifact files to the parent worktree.** Specifically: do not create or edit anything under `three-pillars-docs/tp-designs/{slug}/candidates/`. The orchestrator writes those artifacts itself in Tier 3.5 — the worker only computes and reports. (Why: Claude Code's harness blocks subagent `.md` Write calls as a deliberate signal that subagents should compute, not file-write. Fighting that signal is what got the prior worker-writes-artifacts contract scrapped — see d12-worker-contract-revision.md.)

## Tier 3.5 — Validation gate

Tier 3.5 is the orchestrator's post-worker handling — it parses the worker's structured response, validates it against `candidate.v1.json`, writes the four candidate artifact files, and cleans up the worker worktree. Failures here decide whether `--max-attempts` retries (see ## Retry & max-attempts) or escalates.

### No-op short-circuit

Before parsing anything: if the `Agent(...)` return envelope has no `worktreePath` field, the worker made no file system changes in its worktree (Claude Code auto-cleans empty worktrees before returning). This indicates the worker bailed out without doing the work. Action:

- Skip the artifact-write (there's nothing to validate or persist).
- Append `[tp-run-full-design/tier-3.5] worker-noop` to `decisions.md` with Confidence: High.
- **Escalate immediately** — `--max-attempts` does NOT retry this case (case (a) in detailed-design.md §Error Semantics; the worker producing nothing is a non-retryable structural failure, not a transient one). Per S13 finding F8.

### Wrapper-driven pipeline

For the normal path (worker returned with `worktreePath` present), the orchestrator shells out to the wrapper at `skills/tp-run-full-design/scripts/run_tier_3_5.py`. The wrapper owns the composition of `parse_candidate_response` → `write_candidate_artifacts` → `cleanup_worker_worktree` → `git ls-remote` SHA cross-check. The orchestrator no longer imports the helpers directly.

Invocation:

```
python3 skills/tp-run-full-design/scripts/run_tier_3_5.py
```

Pipe a JSON object on stdin: `{worker_response, agent_meta: {agentId, worktreePath}, design_dir, candidate_id, slug}`. Read the single-line JSON envelope on stdout: `{status, case, event_token, detail}`. The exit code carries the orchestrator's next action:

- **`0` — proceed**: `status: "ok"`, `case: null`, `event_token: "ok"`. Tier 3.5 succeeded; advance to Tier 5.
- **`1` — retry per `--max-attempts`** (case c only): `status: "retry"`, `case: "c"`, `event_token: "schema-validation-error"`. The worker emitted a fenced JSON block with the canonical schema string but the payload failed validation — re-enter Tier 3 if attempts remain.
- **`2` — escalate**: `status: "escalate"`, `case` in `{"a", "b", "e", null}`. Append the appropriate `[tp-run-full-design/tier-3.5] <event_token>` line to decisions.md and exit non-zero. `case: null` is reserved for wrapper-internal failures (`event_token` `stdin-invalid`, `invalid-worktree-path`, `artifact-write-failed`, `cleanup-failed`, or `sha-check-failed`) — these are environmental or contract violations, not retryable, and must not collide with exit 1 (case (c) retry).

The wrapper handles its own decisions.md side effects for the cleanup-retry path: `cleanup_worker_worktree`'s lock-held retry is **internal** to the helper, succeeds silently, and self-logs via `[tp-run-full-design/tier-3.5] worktree-cleanup-retry <path>`. It never surfaces to the orchestrator as a separate envelope case.

The wrapper's source of truth for `candidate_id` is the worker-reported value (extracted from the fenced JSON). The orchestrator's stdin top-level `candidate_id` is advisory routing context — used for correlation in the orchestrator's own decisions.md entries, never for path construction or branch reference inside the wrapper.

### SHA cross-check (case (e), non-retryable)

After `write_candidate_artifacts` returns, the orchestrator runs a final sanity check on the candidate branch:

```
git ls-remote origin candidate/{slug}/{candidate_id}
```

If the remote head SHA does not match `parsed["sha"]`, the worker's claim about what was pushed is wrong (push race, auth issue, or worker fabricated the SHA). Action:

- Append `[tp-run-full-design/tier-3.5] sha-mismatch {slug}:{parsed_sha}:{remote_sha}` with Confidence: High. The `sha-mismatch` event-type token distinguishes this entry from the retry-attempt entries under the same tier-3.5 prefix (preserves the prefix scheme's machine-readability per detailed-design §Decisions (OQ5)).
- **Escalate immediately** — case (e) is non-retryable; an environmental issue, not a worker fault.

### Tier 3.5 outcomes

- **Success**: 4 artifact files written, worktree cleaned, SHA cross-check passes. Proceed to Tier 5.
- **Retryable failure** (case (c)): re-enter Tier 3 per ## Retry & max-attempts.
- **Non-retryable failure** (case (a) no-op, (b) no-block, (e) sha-mismatch): escalate per the appropriate decisions.md entry above; exit non-zero.

## Tier 4 — Council coordination (skipped in MVP)

Mode A0 has **no Tier 4**. The single candidate from Tier 3 is taken verbatim through Tier 5's audits; if those pass, Tier 6 opens the PR. There is no inter-candidate selection, no diff-voting, no persona overlay.

Adding Tier 4 requires:
- `/council` gaining a code-candidate evaluation mode (`--input` over `candidates/`, voting semantics over diffs, not over positions) — Round 1 finding B1.
- A non-test discriminator between candidates (mutation testing, secondary-LLM audit, or council reading diffs directly) — finding V2.

These are out of scope and tracked as a separate multi-candidate follow-on design.

## Tier 5 — Consolidation audits

Tier 5 takes the validated single candidate from Tier 3.5 and runs it through the consolidation audits: regression check, implementation audit, design-learn synthesis. There is no inter-candidate comparison in MVP (Tier 4 is skipped); the single candidate is either accepted or rejected verbatim.

### Step 1 — Regression check (project test suite)

```
git checkout candidate/{slug}/single
{project-test-command}
```

Discover the project test command from `CLAUDE.md` / `Makefile` / `pyproject.toml` / `package.json` scripts. The orchestrator does NOT hardcode `pytest` — it reads the same convention every other tp-* skill reads. On a failure (any test the worker did not already mark as failed/skipped in `test_results`):

- Append `[tp-run-full-design/tier-5] test-regression` with the failing test names + Confidence: High.
- **Escalate immediately** — a regression in tests the worker reported as passing is a contract violation by the worker (the `test_results.passed` count was wrong). Not retryable by re-running the worker, since the candidate branch is what it is. Operator pickup.

### Step 2 — `/tp-implementation-audit --auto`

```
/tp-implementation-audit {slug} --auto
```

Shape C audit, but **verdict-only** — it never edits code regardless of confidence. The skill self-assesses each finding and computes a verdict via `skills/_shared/auto_verdict.py::compute_verdict(confidences)`:

- All findings High (or no findings) → **PASS** or **PASS WITH NOTES**. Proceed to Step 3.
- Any Medium or Low finding → **NEEDS WORK**, exit non-zero from the audit. Orchestrator appends `[tp-run-full-design/tier-5] impl-audit-needs-work` with the finding list and escalates.

The PASS vs PASS WITH NOTES split is informational — both proceed to Tier 6. The notes are surfaced in the Tier 6 PR description so the reviewer sees what passed-with-caveats.

### Step 3 — `/tp-design-learn --auto`

```
/tp-design-learn {slug} --auto
```

Shape B generator. Reads the completed implementation and synthesizes:

- Project doc updates (architecture.md / product_roadmap.md / known_issues.md) — applied per the skill's normal write protocol.
- A `[tp-design-learn]`-prefixed decisions.md trail of what was learned.

`/tp-design-learn --auto` **never edits `three-pillars-docs/vision.md`** — that load-bearing literal is enforced by the skill itself (a SKILL.md prose contract; see `skills/tp-design-learn/SKILL.md`). The orchestrator does not duplicate that check; the delegated skill owns it.

If `/tp-design-learn --auto` produces only High-confidence updates, Tier 5 is done and Tier 6 opens the PR. If it logs Medium/Low-confidence judgments, they flow into the PR description but do not block — design-learn is a synthesizer, not a gate.

### Tier 5 outcomes

- **All three steps pass** → proceed to Tier 6.
- **Step 1 (regression)** → escalate, exit non-zero.
- **Step 2 (NEEDS WORK)** → escalate, exit non-zero.
- **Step 3 (design-learn errors)** → log Medium-confidence, proceed (the candidate is already audited; missing project-doc updates do not invalidate the implementation).

## Tier 6 — PR open + fail-open

The candidate branch is itself the PR branch — there is no separate `final/{slug}` branch (design.md §Behavior 6; Round 1 finding S5). Tier 6's job is to push the candidate (if the worker hasn't already), open a PR with a structured description, and exit cleanly. The `--require-pr-confirm` operator-gate is a deferred feature (see ## Deferred features below).

### Step 1 — Ensure pushed

```
git push origin candidate/{slug}/single
```

Idempotent — if the worker already pushed in step 4 of the explicit_artifact_contract, this is a no-op. The SHA cross-check in Tier 3.5 already confirmed `origin` has the candidate at the expected SHA; this push exists to handle the (rare) case where the worker committed but didn't push.

### Step 2 — `gh pr create`

```
gh pr create \
  --base tp/{slug} \
  --head candidate/{slug}/single \
  --title "orchestrator/{slug}: {task_metadata.title}" \
  --body "$(structured PR description)" \
  --reviewer "{opts.pr_reviewers}"
```

`{base}` is the design branch `tp/{slug}` — the orchestrator's pickup-time base ref. The PR diff is exactly the candidate's work; the design pipeline's plan.md / detailed-design.md / audit artifacts on `tp/{slug}` form the PR's contextual base. The fail-open compare URL below uses the same base.

The structured PR description embeds:
- Link to task source (from `pickup_contract.task_metadata.external_ref`).
- Candidate `summary` from the parsed response.
- `test_results.{passed,failed,skipped}` counts + a fenced excerpt of `raw`.
- Tier 5 verdict (PASS or PASS WITH NOTES; the notes inline if present).
- Tier 5 design-learn synopsis (one-paragraph what-changed).
- An **About this diff** section (see paragraph below).
- Explicit label: "produced by orchestrator MVP — single candidate". Reviewers should understand the audit trail is shallower than a multi-candidate dossier will be.

#### About this diff

Embed this paragraph verbatim in the PR description so reviewers understand the fork-point semantics before they read the side-by-side diff:

> **About this diff**: this candidate branch was forked from `tp/{slug}` HEAD *before* the design-side artifacts (audit findings, plan revisions, decisions.md) were written back onto `tp/{slug}`. GitHub's side-by-side view computes the diff against the current base HEAD, so design-side files committed after the fork point can appear as deletions even though a 3-way merge will preserve them. Run `gh pr view --json mergeStateStatus` or the local preview hook below to confirm the merge is conflict-free before reviewing diff hunks. The fork-point semantics are a deliberate Tier 3 choice (worker isolation; see design.md §Worker isolation).

Optional local merge-preview hook — reviewers (or the orchestrator, ad-hoc) can confirm no design-side files are silently lost by running:

```
git merge-tree --name-only "$(git merge-base tp/{slug} candidate/{slug}/single)" tp/{slug} candidate/{slug}/single
```

The base argument MUST be the true common ancestor (`$(git merge-base ...)`), not `tp/{slug}` HEAD. `--merge-base=tp/{slug}` would set the base to the current base HEAD, which advances every time design-side artifacts land — producing a preview that disagrees with the eventual 3-way merge once the bases diverge. A non-empty output flags files that the 3-way merge will touch; cross-reference with the diff to spot any apparent deletion that is actually a preserved file (per design.md §Scope).

### Step 3 — Fail-open semantics (load-bearing)

If `gh pr create` fails — `gh` not installed, auth expired, network error, GitHub API rejection — Tier 6 **fails open**, mirroring the pattern from `skills/tp-design-complete/SKILL.md` step 6g:

1. Append a Medium-confidence decisions.md entry:
   ```
   [tp-run-full-design/tier-6] gh-pr-create-failed
   **Cause**: <gh stderr or exception>
   **Compare URL**: https://github.com/{owner}/{repo}/compare/{base}...{head}?expand=1
   **Confidence**: Medium
   ```
2. Print the compare URL to stdout so the operator can manually open the PR via web:
   ```
   https://github.com/{owner}/{repo}/compare/tp/{slug}...candidate/{slug}/single?expand=1
   ```
3. **Exit 0** — the orchestrator's exit code MUST reflect "delivered, awaiting manual PR" not "failed". This is mandatory: the candidate branch is on origin and the work is preserved; any CI or downstream tool watching the orchestrator's exit code should treat this run as a successful delivery with a manual-PR-needed flag, not as a failure to retry. **Do NOT exit non-zero on a `gh` failure**; do NOT retry `gh pr create` (only Tier 3+3.5 retries via `--max-attempts`); do NOT fall through to ## Cleanup's abnormal-exit branch. Exit 0, return success, orchestrator exit code 0.

The grep anchor `exit 0` on this paragraph is testable; do not remove the literal phrasing.

### Step 4 — Vision deviation acknowledgment (silent mutation)

This step intentionally violates vision.md's non-goal "Not a tool that silently mutates user work" — see design.md §Behavior 6 deviation paragraph. The deviation is bounded by two stronger commitments preserved at the *outcome* level:

- **Auto-merge is never in scope.** The PR exists; a human must merge. The orchestrator opens but does not close.
- **The PR description + decisions.md form the proposal artifact** the human reviewer reads before merging. The audit trail is the deviation's compensation.

If an operator prefers a pre-PR confirmation gate for high-stakes runs, the deferred `--require-pr-confirm` flag (## Deferred features) will add that gate without changing the default behavior.

### Tier 6 outcomes

- **`gh pr create` succeeds** → exit 0; the orchestrator's terminal decisions.md entry is `[tp-run-full-design/tier-6] pr-opened {pr-url}`.
- **`gh pr create` fails** → exit 0 (fail-open), decisions.md entry `[tp-run-full-design/tier-6] gh-pr-create-failed`, compare URL printed.
- **Push itself fails** (rare — Tier 3.5 already verified origin has the candidate) → exit non-zero, abnormal cleanup.

### Deferred features

- `--require-pr-confirm` — pre-PR operator gate. Trigger to land: first user request or first under-reviewed-PR incident.
- `--dry-run` report formatter — operator UX. Tracked as D12.1 follow-on.

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

A tier in flight finishes — the orchestrator waits for the in-flight skill or subagent to return, *then* checks the cap and aborts at the next boundary. The reasoning: tiers are atomic units (Tier 3's worker Agent, Tier 5's audit) and interrupting them mid-execution leaves partial state that's harder to reason about than spending the few extra tokens to complete the unit and abort cleanly at the boundary. Operators who need a harder cap should set `--max-tokens` lower than the expected unit cost, not expect mid-tier preemption.

### `--max-wall-clock` is independent

`--max-wall-clock SECS` is checked at the same tier boundaries with the same abort semantics, using `[tp-run-full-design/tier-N] wall-clock-abort` as the decisions.md tag. The two caps are independent — hitting either aborts; neither is derived from the other.

## Retry & max-attempts

`--max-attempts N` (default `1`) is the retry budget for **Tier 3 + 3.5 only**. It does NOT retry Tier 2 audits, Tier 5 audits, or Tier 6's `gh pr create`. The semantics are scoped narrowly because Tier 3 is the only tier whose failure mode is plausibly transient — a worker LLM that produced a malformed JSON block on attempt N may produce a valid one on N+1.

### Retry-eligibility table (gated by failure class)

The five worker-contract failure modes from detailed-design.md §Error Semantics map to retry vs. escalate as follows:

| Case | Source | Retryable? |
|---|---|---|
| (a) no-op (`worktreePath` absent) | Tier 3.5 short-circuit | **No** — escalate immediately |
| (b) `NoCandidateBlockError` or `UnknownSchemaVersionError` | `parse_candidate_response` | **No** — escalate immediately (worker ignored the contract) |
| (c) `SchemaValidationError` | `parse_candidate_response` | **Yes** — retry up to `--max-attempts` |
| (e) sha-mismatch | Tier 3.5 SHA cross-check | **No** — escalate immediately (environmental, not worker fault) |

Only (c) is retryable. The other three are structural or environmental — a retry won't change the outcome and just burns tokens.

### Retry loop

```
attempt = 1
while attempt <= --max-attempts:
  run_tier_3()       # spawns the worker Agent
  result = run_tier_3_5()  # parse → write → cleanup → sha-check
  if result.success:
    break
  if result.case in {a, b, e}:
    escalate(result)
    exit_nonzero()
  # case (c) — retryable
  append_decisions_log(f"[tp-run-full-design/tier-3.5] retry attempt {attempt}/{--max-attempts}")
  attempt += 1
if attempt > --max-attempts:
  append_decisions_log("[tp-run-full-design/tier-3.5] retry-exhausted")
  escalate(last_result)
  exit_nonzero()
```

Each retry appends a `[tp-run-full-design/tier-3.5] retry attempt N/M` entry to decisions.md. After exhaustion (N > `--max-attempts`), append a `retry-exhausted` entry and escalate the last failure's case + details.

### Distinguishing case (e) from retries under the same tier prefix

Both retry-attempt entries and case-(e) sha-mismatch escalations live under the `[tp-run-full-design/tier-3.5]` prefix. The **event-type token** after the prefix is the disambiguator and must be stable across orchestrator versions:

- `retry attempt N/M` — retry-eligible failure encountered on attempt N (case c only)
- `retry-exhausted` — final escalation after `--max-attempts` retries
- `sha-mismatch <slug>:<parsed_sha>:<remote_sha>` — case (e), non-retryable, environmental
- `no-candidate-block` — case (b), non-retryable
- `worker-noop` — case (a), non-retryable
- `worktree-cleanup-retry <path>` — informational, from `cleanup_worker_worktree` lock-held retry (Task 1.4 helper, not a worker retry)

A grep over decisions.md for `[tp-run-full-design/tier-3.5]` returns the full history of Tier 3.5 events; the second token classifies. This preserves the prefix scheme's machine-readability (per detailed-design.md §Decisions OQ5).

### Counter-reset rule

The attempt **counter is reset to 1 at the start of each Tier 3 entry** in a single orchestrator run. It is scoped per-Tier-3+3.5 invocation and is **never shared with Tier 2, Tier 5, or Tier 6** — those tiers have no retry mechanism. The counter is also not shared across orchestrator runs: a fresh `/tp-run-full-design {slug}` invocation always starts at attempt 1.

Why this matters: a future operator might assume `--max-attempts 3` means "three retries anywhere in the pipeline." It does not. It means "up to three attempts at the worker tier, per orchestrator run." Document the per-attempt scope here so the rule isn't surprising when an audit at Tier 2 fails and the operator wonders why the retry budget didn't kick in.

### Interaction with `--max-tokens`

Retries consume tokens. Each retry's tier-boundary check (## Token budget) sees a higher running total; if the cumulative usage crosses `--max-tokens` mid-retry-loop, the next tier-boundary token-cap-abort wins over the retry. The cap is the harder constraint. This means a worker stuck in retryable failures (case c/d) on a tight token budget will be killed by `--max-tokens` before exhausting `--max-attempts` — the design is intentional.

## Lock ownership

Per detailed-design.md §Decisions (OQ1), MVP ships with `owner = runner's git email` — the same identity the existing collaboration protocol uses for human developers. A dedicated orchestrator-identity sentinel (`owner: "orchestrator@<host>"`) is a separate design (D15 `lock-owner-classes`); MVP does not require it. If a human passes `--force-takeover` against an orchestrator-held lock mid-run, the orchestrator surfaces the takeover via its standard preflight refusal (it cannot detect mid-run preemption, but the next tier-boundary lock-refresh will fail and abort cleanly).

## Cleanup

On any abnormal exit (token cap, validation failure, audit BLOCKED, worker non-retryable failure), the orchestrator MUST:

1. Append the terminal decisions.md entry classifying the exit.
2. Release the lock or hand it back to the prior owner (per `skills/_shared/collaboration.md` graceful-handoff).
3. Leave the candidate branch on `origin/` if any work was pushed (Tier 3.5 onward) — never `git reset --hard` or drop a remote ref. The work is the human reviewer's input even when the PR did not open.
4. Clean up worker worktrees per `skills/tp-run-full-design/scripts/cleanup_worker_worktree.py` (Tier 3.5's normal-path cleanup; this section enumerates the abnormal-path obligation).
