# Collaboration Conventions

When multiple developers share a project, two conventions prevent stepping on each other's work:

1. **Branch-per-design** — all work on a design or spike happens on its own branch.
2. **Advisory lock** — `three-pillars-docs/tp-designs/{name}/lock.json` records who holds the design and on which branch.

These conventions apply on solo projects too: the lock catches the "I forgot which spike I was on" class of mistake when switching between designs mid-flight.

For the physical workspace layout (seat, worktree host, bare-hub variant, broken-state catalogue) see `skills/_shared/topology.md`.

## Branch convention

- One design/spike = one long-lived branch, named `tp/{design-name}`.
- Created from the project's base branch (`main` or `master`) when the design is first scaffolded.
- PR merges back to the base branch at `/tp-design-complete` time.

## Lock file

Path: `three-pillars-docs/tp-designs/{design-name}/lock.json` — **committed to git**. The lock is advisory, not a mutex. Its job is to produce a merge conflict at PR time if two people start parallel work off the same base, which forces a conversation instead of silently merging two divergent implementations.

Schema:
```json
{
  "design": "{design-name}",
  "branch": "tp/{design-name}",
  "owner": "<git config user.email>",
  "phase": "design|detail|plan|implement|review|audit|spike-plan|spike-implement|cleanup-pending",
  "acquired_at": "<ISO 8601 UTC>",
  "last_touched": "<ISO 8601 UTC>",
  "previous_owners": []
}
```

`previous_owners` is an append-only array of prior lock records (each with `owner`, `branch`, `acquired_at`, `released_at`) produced by `--force-takeover`. It preserves history without blocking the new holder.

## Scope

The framework handles **ownership enforcement** — who currently holds a design and whether a parallel claim is allowed. It does **not** handle **assignment** — who should be working on what in the first place. That decision lives in your existing planning tool (Jira, Asana, Linear, GitHub Projects, a whiteboard, Slack, whatever). As long as your team has coordinated assignments there, the lock here catches accidental overlap and abandoned work without trying to replace the planning system.

Aspirationally this may extend — via MCP servers or hooks — to sync lock state with external planning tools (e.g., auto-update a Jira ticket when a design is claimed, or refuse to claim if the ticket's assignee differs). Out of scope for the current protocol.

## Preflight check

Lock-aware skills run this before executing their main work:

1. **Ensure a git repo exists**: run `git rev-parse --is-inside-work-tree` silently. If it fails (cwd is not a git repo), tell the user:
   > This project is not a git repository. The three-pillars collaboration protocol depends on git (branch, lock file, merge conflicts). I'll run `git init` now so design state is version-controlled from the start.

   Then run `git init -b main` (or `git init` if the user's git is too old to support `-b`). Proceed with the rest of the preflight — the user will be on the newly-created default branch, so step 4's branch check will then offer to switch to `tp/{design-name}`.

2. **Refresh remote state** (fail-open): run `git fetch --quiet origin 2>/dev/null || true`. This pulls the latest remote refs so the lock check in step 5 sees peer activity even if the user hasn't pulled recently. If the fetch fails (no remote configured, offline, auth issue), **continue** — local-only mode is acceptable and the merge-conflict-on-`lock.json` property still catches divergent work at PR time. If the fetch succeeded but the user's tracking branch is behind, note it for step 5.

3. **Determine current state**:
   - Current branch: `git branch --show-current`
   - Current user: `git config user.email` (fall back to `git config user.name` if email is empty; if both are empty, tell the user to set `git config --global user.email <you@example.com>` and stop)
   - Current UTC time as ISO 8601

4. **Branch check** — if current branch is `main`, `master`, or the repo's default branch, refuse to proceed on the default branch and prompt:
   > You are on `{branch}`. Design work must happen on `tp/{design-name}` — committing to the default branch is the leading cause of accidental cross-design commits. Create/switch to that branch now? (yes / no)
   - **yes**:
     - If the branch doesn't exist locally: `git checkout -b tp/{design-name}`.
     - If it exists locally: `git checkout tp/{design-name}`.
     - **Then, immediately publish the branch** if it has no upstream (`git rev-parse --abbrev-ref --symbolic-full-name @{u}` returns non-zero): run `git push -u origin tp/{design-name}`. This signals to teammates that someone is actively working on this design — the remote ref is the visibility mechanism, showing up in their `git branch -a` / GitHub UI / `/tp-guide` well before any artifact commits land. **Fail-open**: if the push fails (no remote configured, offline, auth issue, push rejected by a pre-receive hook), don't block — report the failure, proceed in local-only mode, and note that the branch will be published on the next successful push. Do not retry with `--force`.
   - **no**: stop the skill. There is no third "continue on the default branch" option. If work genuinely must continue on the default branch (rare — e.g. an existing project that hasn't adopted the branch-per-design convention yet), the user creates the `tp/{design-name}` branch manually and re-runs the skill.

5. **Lock check** — determine which lock is authoritative:
   - If the fetch in step 2 succeeded, check whether `origin/{default-branch}` contains a `three-pillars-docs/tp-designs/{design-name}/lock.json` that differs from the local file. Use `git show origin/{default-branch}:three-pillars-docs/tp-designs/{design-name}/lock.json 2>/dev/null` to read the remote version without checking it out.
   - If origin has a newer or different lock than local (remote has a commit touching it that local doesn't), tell the user:
     > `origin/{default-branch}` has a newer `lock.json` for this design than your local copy. Someone else may have claimed it. Pull before proceeding? (yes / no / show-diff)
     - **yes**: run `git pull --ff-only origin {default-branch}`. If fast-forward fails, report the conflict and stop — don't attempt a merge from within the skill.
     - **show-diff**: `git diff HEAD origin/{default-branch} -- three-pillars-docs/tp-designs/{design-name}/lock.json`, then ask again.
     - **no**: proceed with local state. Warn that the final merge may conflict.
   - After resolving remote/local alignment, read the effective `lock.json`:

   | State | Action |
   |---|---|
   | No lock file | **Acquire**: write a fresh lock with current values and phase. |
   | Lock exists, `owner` is `null` (previously released) | **Acquire cleanly**: update top-level owner/branch/phase/acquired_at/last_touched to the new holder. The existing `previous_owners[]` is preserved. No `--force-takeover` required — the prior holder explicitly stepped away. |
   | Lock exists, `owner` + `branch` both match current | **Refresh**: update `phase` and `last_touched`. Proceed. |
   | Lock exists, `owner` or `branch` differs, `last_touched` ≤ 14 days old | Show owner/branch/phase/last_touched. Refuse unless `--force-takeover` was passed. |
   | Lock exists, `last_touched` > 14 days old | Warn that the lock looks stale, show its contents, ask whether to take over. |

   **Takeover procedure** — copy the existing lock's `{owner, branch, acquired_at}` into `previous_owners[]` with a new `released_at: {now}`, then overwrite the top-level fields with the new holder's values and reset `acquired_at` to now.

   **In-flight remote collision check (additive)** — the local + `origin/{default-branch}` checks above only see locks that have landed on the default branch. In-flight locks live on `tp/*` branches and never touch the default branch, so they are invisible to those checks until PR-merge time. To close that gap, also consult the in-flight registry built from `origin/tp/*` branches via `skills/_shared/inflight_registry.py`:
   - **Situational-awareness print** — build the registry (`build_registry`) and print `format_table` so the operator sees every in-flight design (owner, phase, branch, age, `⚠ stale`/`· unreadable` flags) before any work begins. This print is awareness-only; different design names never block.
   - **Same-name collision verdict** — run `collision_verdict(entries, {design-name}, {git user.email})` for the design being claimed and act on the verdict:
     - `clear` → proceed (no in-flight `origin/tp/{design-name}` lock, or it was explicitly released).
     - `self` → **non-blocking notice**: the same git email holds `origin/tp/{design-name}` from another machine. Note it (you may be working in two places) but do **not** refuse — refusing would block your own legitimate work.
     - `conflict` → **refuse before any work** unless `--force-takeover` was passed. A `conflict` is either a different owner *or* a same-name `tp/{design-name}` ref whose lock can't be read (ownership unconfirmed — the ref's existence is itself the collision signal). On `--force-takeover`, run the same takeover procedure above (record the prior holder in `previous_owners[]`).
   - This check **augments, does not replace** the existing local and `origin/{default-branch}` lock checks — local semantics are unchanged; the remote same-name check just moves the in-flight collision gate from PR-merge to branch-startup.
   - **Freshness dependency** — the collision read depends on step 2's `git fetch --quiet origin` being **unscoped** (it fetches all heads, including `tp/*`, so the lock objects `read_lock_blob` needs are present locally). If a future change scopes step 2's fetch to exclude `tp/*`, every collision verdict silently degrades to `readable=False → conflict` — i.e. it **fails *closed*** (conservatively refuses rather than missing a real collision; `--force-takeover` overrides), which is safe but noisy. (This is the opposite of the *registry build's* whole-failure behavior, which fails *open* — degrades to the local view and never blocks.) Keep step 2's fetch unscoped, or update this dependency note alongside any change to it.

6. **Stage the lock**: after acquiring / refreshing / taking over, write the updated `lock.json` to disk. The lock update is rolled into the skill's artifact commit per `skills/_shared/commit-after-work.md` — never commit just a lock change on its own (the sole exception is `/tp-design-release`, where the lock change is the work).

## Release

There are three release paths, in order of commonness:

1. **Completion** (`/tp-design-complete`): the lock is released implicitly when the design directory moves to `three-pillars-docs/completed-tp-designs/`. The lock file carries with it as a historical record.
2. **Graceful step-away** (`/tp-design-release`): the current owner explicitly gives up the lock without finishing the design. `owner`/`branch`/`phase` go to `null`; the prior holder is preserved in `previous_owners[]` with a `released_by` and optional `reason`. Anyone else can then claim it by just running the next lock-enforcing skill — no `--force-takeover` needed.
3. **Taken over** (via `--force-takeover` on any lock-enforcing skill): the receiving developer claims a still-held lock. Appropriate when the current owner is unreachable or unresponsive but hasn't explicitly released.

Stale locks (≥ 14 days since `last_touched`) surface as warnings on the next lock check and can be taken over without `--force-takeover` via the "ask whether to take over" prompt.

## When to apply

**Lock-enforcing skills** (acquire or verify, may block):
- `/tp-design`, `/tp-spike` — may acquire the lock for the first time.
- `/tp-design-detail`, `/tp-plan`, `/tp-spike-plan` — verify before writing planning artifacts.
- `/tp-phase-implement`, `/tp-spike-implement` — verify before writing code (highest-risk skills).

**Lock-aware skills** (inspect only, warn on mismatch, never block):
- `/tp-session-restore`, `/tp-guide`, review/audit/learn skills.

**Lock-releasing & teardown skills** (close out or tear down a design at end-of-life — `/tp-post-merge` is grouped here as the final lifecycle step even though it is lock-*aware*, not lock-releasing: it leaves the archived `lock.json` intact):
- `/tp-design-complete` — the directory move carries the lock with it; no separate release needed. Sets `phase = "cleanup-pending"` as part of the archival commit (before opening the PR) so `/tp-post-merge` can identify designs awaiting teardown.
- `/tp-design-release` — graceful step-away. Clears the owner without completing the design, so a teammate can pick it up without `--force-takeover`.
- `/tp-post-merge` — the sole **merge-verified lifecycle** teardown path (other tooling can remove a worktree as a general unverified operation; this is the one that fires, merge-verified, after a completion-PR merge). It is **lock-aware, not lock-enforcing**: `phase == "cleanup-pending"` is the *discovery* signal for the no-arg scan (paired with the branch still existing on origin), but the **merge-verify** (`verify_merged.py`), not the advisory lock, is the safety gate. It verifies the merge, then tears down the design's branch, sibling worktree, and MRU entry. It does **not** update or clear the archived `lock.json` (there is no post-cleanup phase in the enum) — the lock stays alongside the archived design under `completed-tp-designs/` as the historical record, and the branch's absence is the durable "torn down" signal.

## Gitignore

- The lock file IS committed — do not add it to `.gitignore`.
- `three-pillars-docs/tp-designs/*/handoff.md` stays gitignored (per-developer session state; `tp-session-save` handles this on first write).
- `.claude/last-design` stays gitignored (per-developer MRU state; `validate-name.md` handles this on first write).
- **Tracked design artifacts** (committed): `design.md`, `detailed-design.md`, `plan.md`, `spike-results.md`, `decisions.md`, everything under `demos/`, `lock.json`. These form the design's permanent record and must sync across machines, survive archival, and be reviewable.
- **Never `git add`** the truly gitignored state files (`handoff.md`, `.claude/last-design`). Git emits a noisy "paths are ignored" hint and the file would only land in the repo if `-f` is passed. Skills write these files directly; leave staging to the user.

## Inline worktree-driving is unsupported

Running a worktree-operating skill (tp-phase-implement, tp-spike-implement, tp-merge-from-main,
tp-design-complete, and the worktree-management skill) from the **main checkout** while a
`tp/<design>` worktree is live is unsupported and actively guarded. Two controls enforce this:

1. **Fail-closed commit guard** — framework-check invariant #28 calls
   `skills/_shared/worktree_write_guard.py` before every commit. If the commit is on
   a default branch (`main`/`master`), a `tp/*` worktree is live, AND the staged set
   contains framework code or design artifacts, the commit is refused with guidance.
   This is the backstop control — it fires even if the preflight was bypassed.

2. **Fail-open cwd preflight** — each of the five worktree-operating skills runs
   `python3 skills/_shared/cwd_preflight.py <design>` as a numbered preflight step
   (see `skills/_shared/cwd-preflight.md`). If a `tp/<design>` worktree exists and
   the session cwd is not inside it, the skill refuses with a `cd` fix before any
   file is written. This is the ergonomic early-refuse.

The pattern the fleet's interactive launch windows enforce by construction — each window is
`cd`-ed into its own worktree before the skill fires, so the cwd is already correct.

**Fix**: `cd` into the worktree before running the skill.

```
cd ../<repo>-wt/<design>
# then re-run your command
```

The preflight message (exit 3) prints the concrete target worktree path; the
commit-guard guidance (exit 1) prints the live `tp/*` branch name(s) and a generic
`cd ../<repo>-wt/<slug>` re-run pattern (it does not resolve a concrete path).
