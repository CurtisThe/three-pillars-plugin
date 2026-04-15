# Collaboration Conventions

When multiple developers share a project, two conventions prevent stepping on each other's work:

1. **Branch-per-design** — all work on a design or spike happens on its own branch.
2. **Advisory lock** — `docs/tdd-designs/<name>/lock.json` records who holds the design and on which branch.

These conventions apply on solo projects too: the lock catches the "I forgot which spike I was on" class of mistake when switching between designs mid-flight.

## Branch convention

- One design/spike = one long-lived branch, named `tdd/<design-name>`.
- Created from the project's base branch (`main` or `master`) when the design is first scaffolded.
- PR merges back to the base branch at `/tdd-design-complete` time.

## Lock file

Path: `docs/tdd-designs/<design-name>/lock.json` — **committed to git**. The lock is advisory, not a mutex. Its job is to produce a merge conflict at PR time if two people start parallel work off the same base, which forces a conversation instead of silently merging two divergent implementations.

Schema:
```json
{
  "design": "<design-name>",
  "branch": "tdd/<design-name>",
  "owner": "<git config user.email>",
  "phase": "design|detail|plan|implement|review|audit|spike-plan|spike-implement",
  "acquired_at": "<ISO 8601 UTC>",
  "last_touched": "<ISO 8601 UTC>",
  "previous_owners": []
}
```

`previous_owners` is an append-only array of prior lock records (each with `owner`, `branch`, `acquired_at`, `released_at`) produced by `--force-takeover`. It preserves history without blocking the new holder.

## Preflight check

Lock-aware skills run this before executing their main work:

1. **Ensure a git repo exists**: run `git rev-parse --is-inside-work-tree` silently. If it fails (cwd is not a git repo), tell the user:
   > This project is not a git repository. The three-pillars collaboration protocol depends on git (branch, lock file, merge conflicts). I'll run `git init` now so design state is version-controlled from the start.

   Then run `git init -b main` (or `git init` if the user's git is too old to support `-b`). Proceed with the rest of the preflight — the user will be on the newly-created default branch, so step 3's branch check will then offer to switch to `tdd/<design-name>`.

2. **Determine current state**:
   - Current branch: `git branch --show-current`
   - Current user: `git config user.email` (fall back to `git config user.name` if email is empty; if both are empty, tell the user to set `git config --global user.email <you@example.com>` and stop)
   - Current UTC time as ISO 8601

3. **Branch check** — if current branch is `main`, `master`, or the repo's default branch, warn:
   > You are on `<branch>`. The collaboration convention is to work on `tdd/<design-name>`. Would you like to create/switch to that branch now? (yes / no / continue-anyway)
   - **yes**: `git checkout -b tdd/<design-name>` if it doesn't exist, else `git checkout tdd/<design-name>`.
   - **continue-anyway**: proceed; the lock records the current branch as-is.
   - **no**: stop the skill.

4. **Lock check** — read `docs/tdd-designs/<design-name>/lock.json` if present.

   | State | Action |
   |---|---|
   | No lock file | **Acquire**: write a fresh lock with current values and phase. |
   | Lock exists, `owner` + `branch` both match current | **Refresh**: update `phase` and `last_touched`. Proceed. |
   | Lock exists, `owner` or `branch` differs, `last_touched` ≤ 14 days old | Show owner/branch/phase/last_touched. Refuse unless `--force-takeover` was passed. |
   | Lock exists, `last_touched` > 14 days old | Warn that the lock looks stale, show its contents, ask whether to take over. |

   **Takeover procedure** — copy the existing lock's `{owner, branch, acquired_at}` into `previous_owners[]` with a new `released_at: <now>`, then overwrite the top-level fields with the new holder's values and reset `acquired_at` to now.

5. **Stage the lock**: after acquiring / refreshing / taking over, write the updated `lock.json` to disk. Skills don't create commits on the user's behalf — the next commit produced by the skill's normal flow (or the user) will include it.

## Release

The lock is released implicitly when `/tdd-design-complete` moves the design directory to `docs/completed-tdd-designs/`. There is no separate release step during normal use. A completed design in the archive still carries its lock file as a historical record.

If a developer wants to hand off a design mid-flight, they should commit + push with the lock as-is. The receiving developer runs the next skill with `--force-takeover` to claim it.

## When to apply

**Lock-enforcing skills** (acquire or verify, may block):
- `/tdd-design`, `/tdd-spike` — may acquire the lock for the first time.
- `/tdd-design-detail`, `/tdd-plan`, `/tdd-spike-plan` — verify before writing planning artifacts.
- `/tdd-phase-implement`, `/tdd-spike-implement` — verify before writing code (highest-risk skills).

**Lock-aware skills** (inspect only, warn on mismatch, never block):
- `/tdd-session-restore`, `/tdd-guide`, review/audit/learn skills.

**Lock-releasing skills**:
- `/tdd-design-complete` — the directory move carries the lock with it; no separate release needed.

## Gitignore

- The lock file IS committed — do not add it to `.gitignore`.
- `docs/tdd-designs/*/handoff.md` and `docs/tdd-designs/*/decisions.md` stay gitignored (per-developer session state; `auto-mode.md` handles these on first write).
- `.claude/last-design` stays gitignored (per-developer MRU state; `validate-name.md` handles this on first write).
- **Never `git add`** gitignored state files (`handoff.md`, `decisions.md`, `.claude/last-design`, `demos/`). Git emits a noisy "paths are ignored" hint and the file would only land in the repo if `-f` is passed. Skills write these files directly; leave staging to the user.
