# Commit After Work

When a skill produces a substantial artifact, it commits that artifact at the end of the skill. The working tree should be clean (for paths the skill touched) when the skill returns control to the user. This eliminates the "constant untracked changes across phases" problem — every phase boundary is a commit boundary.

## Which skills apply this protocol

**Opt-in** (commit at the end):
- Setup: `/tdd-setup`, `/tdd-docs-init`, `/tdd-test-setup`
- Design pipeline: `/tdd-design`, `/tdd-design-detail`, `/tdd-plan`
- Implementation: `/tdd-task-cycle` (one commit per full red-green-refactor cycle), `/tdd-phase-implement` (stragglers only), `/tdd-phase-review`, `/tdd-implementation-audit`
- Spike pipeline: `/tdd-spike`, `/tdd-spike-plan`, `/tdd-spike-implement` (one commit per experiment), `/tdd-spike-results`
- Learn / docs: `/tdd-design-learn`, `/tdd-spike-learn`, `/tdd-docs-update`
- Release: `/tdd-design-release` (the lock change is the substantial work)

**Do not apply** (skills don't commit):
- Audit-only skills that don't write files: `/tdd-design-audit`, `/tdd-plan-audit`
- Session state on gitignored paths: `/tdd-session-save`, `/tdd-session-restore`, `/tdd-session-clear`
- Read-only guides: `/tdd-guide`

**Handles its own commit** (does not reference this doc):
- `/tdd-design-complete` — commits the archival + opens the PR. See that skill's SKILL.md for the full flow.

## The protocol

Run this at the end of the skill, after all artifact files are written.

### 1. Identify the artifact paths

Each calling skill must pass a concrete, enumerable list of paths it just produced — e.g., `docs/tdd-designs/<name>/design.md` and `docs/tdd-designs/<name>/lock.json`. Never stage a broad directory.

### 2. Check for unrelated WIP

Run `git status --short`. If any changed path is **outside** the artifact list above, stop and tell the user:

> I'm about to commit `<skill-name>`'s artifacts but the working tree has unrelated changes: `<paths>`. Commit or stash them first so the completion commit stays focused.

Do not proceed until the user resolves it. The skill never sweeps unrelated WIP into its commit.

### 3. Stage only the artifact paths

Stage the specific paths the skill produced. **Never** use `git add -A`, `git add .`, or `git add <wide-dir>`.

```bash
git add <path1> <path2> ...
```

### 4. Commit with a scoped, conventional message

See the message table below. The message follows `<Verb>: <design-name> <detail>` so `git log --oneline` reads like a changelog of the design's lifecycle.

```bash
git commit -m "<message>"
```

**Do not add any Co-Authored-By trailer.**

### 5. Handle hook failures

If `git commit` fails (pre-commit hook, lint, type check, etc.), stop and surface the output to the user. **Never** retry with `--no-verify`. The user must fix the underlying issue — a blocked commit means something's wrong with the work, not with the hook.

### 6. Do not push

Skills never push from inside the run. Pushing + opening a PR is reserved for `/tdd-design-complete`. The user can push on their own schedule; the branch-per-design convention keeps their local branch isolated.

## Commit message conventions

| Skill | Message template |
|---|---|
| `/tdd-setup` | `Setup: vision` |
| `/tdd-docs-init` | `Docs: init project docs` |
| `/tdd-test-setup` | `Setup: test infrastructure` |
| `/tdd-design <name>` | `Design: <name> high-level` |
| `/tdd-design-detail <name>` | `Design: <name> detailed` |
| `/tdd-plan <name>` | `Plan: <name>` |
| `/tdd-task-cycle` | `Implement: <design-name> <phase>.<task> — <task-title>` |
| `/tdd-phase-implement <name>` | `Implement: <name> phase-<n> cleanup` (only if stragglers remain after per-task commits) |
| `/tdd-phase-review <name>` | `Review: <name> phase-<n>` |
| `/tdd-implementation-audit <name>` | `Audit: <name> implementation` |
| `/tdd-spike <name>` | `Spike: <name> design` |
| `/tdd-spike-plan <name>` | `Spike: <name> plan` |
| `/tdd-spike-implement <name>` | `Spike: <name> <phase>.<experiment>` (one per experiment) |
| `/tdd-spike-results <name>` | `Spike: <name> results` |
| `/tdd-design-learn <name>` | `Learn: <name> design` |
| `/tdd-spike-learn <name>` | `Learn: <name> spike` |
| `/tdd-docs-update` | `Docs: update <file1>,<file2>` (comma-separate; omit repeated "docs/" prefix) |
| `/tdd-design-release <name>` | `Release: <name>` (or `Release: <name> (force)` if `--force` was used) |
| `/tdd-design-complete <name>` | `Complete design: <name>` (owned by that skill — not this protocol) |

## Lock file handling

If the skill acquires or refreshes `docs/tdd-designs/<name>/lock.json` during its preflight (per `skills/_shared/collaboration.md`), include the lock file in the **same** commit as the content artifact. Don't produce a separate "update lock" commit.

The exception: `/tdd-design-release` commits only `lock.json` — the lock change *is* the substantial work.

## User-initiated opt-out

If during a skill run the user explicitly asks to skip the commit ("don't commit that", "I'll commit it myself"), honor it. Leave the artifacts in the working tree (unstaged) and tell the user what's there. Do not prompt again — one ask is enough for the rest of that skill run.

## Autonomous mode

In `--auto` modes (e.g., `/tdd-spike-auto`), commits are **required** — the whole point is unattended execution. If a commit fails (hook rejection, unrelated WIP detected), the skill logs the failure to `decisions.md` and stops the autonomous pipeline rather than bypassing. See `skills/_shared/auto-mode.md` for failure-handling conventions.

## Orchestrator skills

Orchestrator skills (`/tdd-phase-implement`, `/tdd-spike-implement`, `/tdd-spike-auto`) delegate the bulk of their commits to the inner skills they invoke (`/tdd-task-cycle`, etc.). At the end of the orchestrator run, check for stragglers: if `git status --short` shows any staged or unstaged changes remaining, the orchestrator commits them with a "cleanup" message. If the tree is clean, the orchestrator skips its own commit.

## Rationale

Frequent, scoped commits produce a clean audit trail at every design phase and prevent the "I have 40 files of uncommitted work across design + implementation" failure mode. Combined with branch-per-design, this means every phase of every design is recoverable, reviewable, and mergeable independently. `/tdd-design-complete` then squashes/merges the branch to base, so downstream repos see a clean history if they prefer.
