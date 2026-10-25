<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Tier 1 — Pickup

### Mode A — Pickup skill provided

- Refuse if `--task-id` is missing: append `[tp-run-full-design/tier-1] missing-task-id` to decisions.md, exit non-zero.
- Invoke `/{pickup-skill} --orchestrator --slug {slug} --task-id {task-id}`.
- Pickup skill validates the task, creates `three-pillars-docs/tp-designs/{slug}/`, locks `tp/{slug}` (`owner = orchestrator`, `run-safety.md` ## Lock ownership), seeds `design.md`/`spike.md`, returns a pickup contract with `task_metadata.external_ref = {task-id}` for the Tier 6 PR description.

### Mode B — Manual pickup

- Read existing `three-pillars-docs/tp-designs/{slug}/design.md` (must exist).
- Acquire the lock per `skills/_shared/collaboration.md`; if held, honor `--force-takeover` or refuse.
- Synthesize a minimal contract: `phase_hook`, `writeup_hook`, `escalate_hook` all `null`.
- Print `python3 "$TP_ROOT"/skills/_shared/weight_class.py lighten three-pillars-docs/tp-designs/{slug}` as
  `lighten (informational, no routing change): <line>` and log it; fail-open (a missing axis or error prints
  nothing). The routing and the de-escalation refusal below are unchanged.

**Local preflight**: Always run `python3 "$TP_ROOT"/skills/_shared/agent_override_warn.py --root .` (exits 0; log warnings). Under `--local` only: `python3 "$TP_ROOT"/skills/_shared/local_implement_config.py --check full_design` exit 1 → refuse before Tier 2 (log `[tp-run-full-design/tier-1]`); `python3 "$TP_ROOT"/skills/_shared/local_backend.py` exit 1 → refuse with its line; print the routing check unlogged (`local-routing.md` §Orchestrator); cheap-tier `cheap-tier.md` §Tier 1.

### Pickup contract v1 validation

Validate the returned contract first: schema/rules in `boundary-contracts.md` §Pickup contract v1.

### Weight-class consumption

- `python3 "$TP_ROOT"/skills/_shared/weight_class.py read three-pillars-docs/tp-designs/{slug}` (`weight-class.md`) — direct design.md frontmatter read; the class never rides the contract. A `("full","default")` read routes as `full`.
- `full` — documented pipeline; `light` — light slot mapping (`SKILL.md` ## Per-slot budget table light column).
- `just-do-it` — run `python3 "$TP_ROOT"/skills/_shared/jdi_eligibility.py route --design-dir three-pillars-docs/tp-designs/{slug} --base origin/<base> --head HEAD`; `route: just-do-it` → `SKILL.md` ### Just-do-it slot mapping, log `[tp-run-full-design] weight-class route: just-do-it`; `route: light` → append the escalation line it prints to decisions.md and route `light` (the script already stamped `design.md` + `seed.md`). On `route: light` commit the stamped `design.md` + `seed.md` with the escalation's decisions.md entry (scoped `git add` on `tp/{slug}`) before Tier 2. A script exit 2 (`ESCALATE bad-input`) is logged the same way and routes `light` as well.
- `spike` — refuse: `/tp-spike-auto` Phase 1 is interactive, cannot run unattended; never re-class silently. BLOCKED `**Cause**: weight-class-spike-refusal`, exit non-zero.
- De-escalation refused: escalate above the declared class (logged), never below; a lighter run than declared → BLOCKED `**Cause**: weight-class-de-escalation-refused`.

### Scratch provision

Every run (Mode A, B and C, whatever its env; Mode C before it advances to Tier 2) runs `python3 "$TP_ROOT"/skills/_shared/scratch_leftovers.py provision --slug {slug}` before Tier 1 outcomes. It is idempotent and prints `<run dir> created` or `<run dir> exists`. Log `[tp-run-full-design/tier-1] scratch-provisioned <run dir>` with the printed path (suffix ` late` when it printed `created`), then compare `printenv TMPDIR` with that path and log `[tp-run-full-design/tier-1] scratch-redirect-missing` when they differ (a manual fallback keeps its old `TMPDIR`: its own temp files are reported, not redirected). A create failure is one note, not a stop.

### Tier 1 outcomes

- **Success**: contract valid, lock held, on branch `tp/{slug}`, class routed → Tier 2; each tier refreshes `last_touched` and bumps `phase`.
- **Failure**: any rule above → append a categorized decisions.md entry, exit non-zero; Tier 2 never runs on an invalid contract.

## Tier 1.5 — Mode C front-end (interactive design)

- Default when `/tp-run-full-design {slug}` has neither `--pickup-skill` nor `--skip-design`: run `/tp-design` interactively, then ask to go autonomous.
- Emit tokens under the `[tp-run-full-design/tier-1]` prefix, not `tier-1.5`.

### Default routing

- No `design.md` → invoke `/tp-design {slug}`; once it commits, go to the prompt.
- `design.md` already exists → re-enter `/tp-design` (the skill owns revise-or-fresh), then the prompt.

### Confirmation prompt (blocking)

- When `python3 "$TP_ROOT"/skills/_shared/autonomous_gate.py` exits 0 (the launcher's `TP_DESIGN_RUN=1` marker is set and this is not a `claude -p` child: no `TP_CHILD_SESSION`), ask nothing: append `[tp-run-full-design/tier-1] autonomous-continue (seat launch)` and advance to Tier 2. Exit 1 (no marker, or a child), any other exit, or a gate that cannot run gets the prompt below.
- Ask `Go autonomous from here?` `[y/n]`; no countdown auto-proceed — a human must answer; block on stdin until `y`/`yes` or `n`/`no`, else re-prompt.

### Outcomes

- `y` → append `[tp-run-full-design/tier-1] autonomous-continue`, advance to Tier 2 holding the lock; unattended from here.
- `n` → terminal no-branch state: `design.md` committed, `tp/{slug}` preserved, lock owner back to the invoking human (no `--force-takeover` on the next `/tp-design-detail {slug}`); append `[tp-run-full-design/tier-1] no-autonomous-run`; exit 0.
