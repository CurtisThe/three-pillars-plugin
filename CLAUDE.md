# ⚠️ This file is generated — do not edit directly

This `CLAUDE.md` is shipped from a private dev repo via `release.sh`. Direct edits to this file (or any other file in this repo's allowlist: `skills/`, `agents/`, `.claude-plugin/`, `settings.json`, `statusline.sh`, `LICENSE`, `CONTRIBUTING.md`, etc.) will be **overwritten on the next release**.

**To contribute**: open an issue or PR describing the change. The maintainer will apply it upstream and re-release. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

# Three Pillars Framework

This machine uses the **three-pillars** skill framework for structured software development with Claude Code.

## Project Docs

Every project should maintain four living docs in `three-pillars-docs/`:

- **`vision.md`** — Problem, users, principles, non-goals, success signals. Source of truth for **why** the project exists. Read first by every other TDD skill — it is the filter for what work matters and the tie-breaker when technical options are equivalent. Created by `/tp-setup` as its first conversational step.
- **`architecture.md`** — System architecture, key decisions, constraints. Source of truth for **how** the system is built.
- **`product_roadmap.md`** — Current state, design inventory, implementation sequence. Source of truth for **what to build next**. Links to `vision.md` rather than duplicating the why.
- **`known_issues.md`** — Open bugs and limitations by severity. Source of truth for **what's broken**.

Use `/tp-setup` first to establish the vision. Then `/tp-docs-init` to scaffold architecture, roadmap, and known-issues from codebase analysis. Use `/tp-docs-update` to maintain them after milestones.

## Getting Started

Fresh project setup follows a deliberate order — **why** before **how**, **how** before **tests**:

1. **`/tp-setup`** — Draws out the project's "why" into `three-pillars-docs/vision.md` (conversational). Vision only; no test-runner decisions here. Run first on any new project.
2. **`/tp-docs-init`** — Scaffolds `architecture.md`, `product_roadmap.md`, and `known_issues.md` from codebase analysis. Uses `vision.md` as context.
3. **`/tp-test-setup`** — Configures test infrastructure (test runner, layout, permissions, starter test). Runs *after* architecture so test-runner and layout choices are informed by the documented structure, not guessed at before.

- **`/tp-guide [intent]`** — Read project docs and recommend the highest-impact next step. Accepts optional freeform intent (e.g., `/tp-guide auth feels fragile`). Helps choose the right approach: just do it, spike, or full design. Weighs recommendations against `three-pillars-docs/vision.md`.

## First-Run Preflight

Every `/tp-*` skill begins with a shared preflight defined in `skills/_shared/first-run.md`. On a fresh repo it can:

1. **Detect legacy layout** — if the repo still uses the pre-`tp-*` namespace layout (`docs/` instead of `three-pillars-docs/`, `tdd-` skill names), refuse and direct the user to `/tp-migrate` (the only skill exempt from this check, since migrating *is* its work). See `skills/_shared/first-run.md` for the exact triggers. The migration tool is reversible until you commit; `/tp-migrate --dry-run` shows the plan first.
2. **Offer branch protection** — for repos with a GitHub `origin`, propose a one-time `gh api` call that requires one PR review and blocks force-pushes on the default branch. See `skills/_shared/branch-protection.md` for the protocol and the manual fallback when `gh` is missing. The prompt fires at most once per repo.

State is persisted in `.three-pillars/config.json` (committed) per `skills/_shared/repo-config.md`. Once configured, the preflight is a single file read — no further prompts.

## TDD Pipeline

For structured implementations with full confidence:

```
/tp-design         → high-level design (design.md)
/tp-design-detail  → concrete blueprint (detailed-design.md)
/tp-design-audit   → verify design against codebase
/tp-plan           → phased task list (plan.md)
/tp-plan-audit     → verify plan consistency (script + council)
/tp-phase-implement → execute a phase (red-green-refactor)
/tp-phase-review   → review completed phase
/tp-implementation-audit → final audit
/tp-design-complete → archive to three-pillars-docs/completed-tp-designs/ (offers PR to base)
```

## Spike Pipeline

For experiments that validate unknowns before committing to a full design:

```
/tp-spike          → frame hypothesis + success criteria (design.md)
/tp-spike-plan     → lightweight experiment plan (plan.md)
/tp-plan-audit     → verify plan (use --spike for spike-flavored plans)
/tp-spike-implement → execute experiments (serial, human review gates)
/tp-spike-results  → capture findings + verdict (spike-results.md)
/tp-spike-learn    → synthesize learnings into project docs
```

Spikes can link to a parent design: `/tp-spike my-spike --parent my-design`

**When to spike vs full design**: Spike when you're unsure if an approach works. Full design when the approach is known and you're building for real.

## Autonomous Spike Pipeline

Run an entire spike hands-off after an interactive design conversation:

```
/tp-spike-auto {spike-name}  → interactive design, then autonomous execution
```

Phase 1 is interactive (design Q&A). After you confirm "go autonomous," it chains:
`spike-plan --auto` → `plan-audit --spike --auto` → `spike-implement --auto` → `spike-results --auto`

All decisions are logged to `decisions.md` in the spike directory for morning review.
Run `/tp-spike-learn` manually after reviewing results.

### `--auto` flag

Most spike skills support `--auto` for autonomous execution:
- Replaces human Q&A with self-assessment
- Logs every decision to `decisions.md` (see `skills/_shared/auto-mode.md` for format)
- Never blocks on user input
- On task failure: simplifies and retries (max 3 attempts)

### `--spike` flag (plan-audit only)

`/tp-plan-audit {name} --spike` audits spike-flavored plans:
- Expects Hypothesis/Try/Evaluate fields (not File/Test/Red/Green)
- Skips detailed-design.md requirement
- Council prompts evaluate experiment quality instead of implementation specs

## Session Management

```
/tp-session-save    → save context for continuity across conversations
/tp-session-restore → load context at start of new conversation
/tp-session-clear   → clear stale context when switching tasks
```

**Context window hygiene**: When context exceeds 200k tokens (visible in the status line as `>200k`), proactively recommend the user save and restart:
1. Run `/tp-session-save {active-design}` to capture current state
2. Suggest the user run `/clear` or start a new conversation
3. After restore: `/tp-session-restore {design-name}` to pick up where they left off

This preserves continuity while keeping context lean. Don't wait until context is critical — recommend at 200k so the user has room to finish their current thought.

**After `/clear`**: Check if `.claude/last-design` exists (project root). If it does, read the design name and proactively offer to restore: "You were working on `{name}`. Want me to run `/tp-session-restore`?"

## File Size Limits

Keep individual files under **600–800 lines** where possible. This ensures files fit within Claude Code's Read tool context (~10k characters) without truncation, which matters for reliable code review, design analysis, and council deliberation. If a file grows beyond this range, consider splitting it by responsibility.

## Commits

Every skill that produces substantial work commits at the end — scoped `git add`, conventional message, no Co-Authored-By trailer, no `--no-verify`, no auto-push. One commit per task during `/tp-phase-implement`. One commit per artifact for design/plan/review/audit/learn steps. See `skills/_shared/commit-after-work.md` for the protocol and the full message-template table. Pushing and opening a PR happens only at `/tp-design-complete`.

## Collaboration

When multiple developers share a project, two conventions prevent stepping on each other's work:

1. **Branch-per-design** — one design or spike = one branch named `tp/{design-name}`, cut from the base branch and merged back at `/tp-design-complete` time. The branch is pushed to `origin` on creation so teammates see in-flight work immediately, not only after the first commit lands.
2. **Advisory lock** — `three-pillars-docs/tp-designs/{name}/lock.json` records who holds the design and on which branch. Committed to git so a parallel attempt produces a merge conflict at PR time.

Lock-enforcing skills (`/tp-design`, `/tp-spike`, `/tp-design-detail`, `/tp-plan`, `/tp-spike-plan`, `/tp-phase-implement`, `/tp-spike-implement`) run a preflight that:
- Warns if you're on `main`/`master` and offers to create `tp/{design-name}`.
- Refuses to proceed if another developer holds the lock. Pass `--force-takeover` to claim it (the prior holder is recorded in `previous_owners[]`).

Graceful handoff: run `/tp-design-release {name}` to step away cleanly — `owner` goes to `null` and the next person claims the design without needing `--force-takeover`.

Read-only skills (`/tp-session-restore`, review/audit/learn) inspect the lock and warn, but never block.

See `skills/_shared/collaboration.md` for the full protocol, lock.json schema, and stale-lock handling.

## Council

`/council` convenes multi-persona deliberation for complex decisions. Used automatically by `/tp-plan-audit`.
