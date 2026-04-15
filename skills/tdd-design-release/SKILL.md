---
name: tdd-design-release
description: Release your lock on a design without completing it. Use when you're stepping away and want a teammate to pick it up cleanly, without them having to --force-takeover.
argument-hint: "<design-name> [-m \"<reason>\"] [--force]"
---

# Design Release

Release your ownership of a design so another developer can claim it without `--force-takeover`. This is the graceful handoff path — unlike `/tdd-design-complete`, the design is *not* finished; you're just stepping away.

**Arguments**:
- `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.
- `-m "<reason>"` (optional) — short note stored with the released lock record, visible to the next owner (e.g., `"needs help with API design"`, `"on vacation"`).
- `--force` (optional) — release someone else's lock. Requires a confirmation. Use when a teammate clearly abandoned the design and you want to clear it without claiming it yourself.

## Prerequisites
- `docs/tdd-designs/<design-name>/lock.json` must exist. If not, tell the user there's nothing to release and stop.

## Steps

1. **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
2. **Read `lock.json`** from the design directory.
3. **Ownership check**:
   - If `lock.json.owner` is already null (already released): tell the user the lock is already released and show the last `previous_owners[]` entry. Stop.
   - If `lock.json.owner` matches `git config user.email` (you own it): proceed.
   - If `lock.json.owner` differs and `--force` was **not** passed: refuse.
     > This lock is held by `<owner>` on `<branch>`. You can't release someone else's lock without `--force`. If you want to claim it for yourself, use `--force-takeover` on the relevant lock-enforcing skill instead.
     Stop.
   - If `lock.json.owner` differs and `--force` was passed: ask for explicit confirmation, show the current holder and last_touched age, and only proceed on affirmative.
4. **Release procedure**:
   - Append the current lock state to `previous_owners[]` as a new entry:
     ```json
     {
       "owner": "<current lock owner>",
       "branch": "<current lock branch>",
       "acquired_at": "<current lock acquired_at>",
       "released_at": "<now ISO 8601 UTC>",
       "released_by": "<git config user.email>",
       "reason": "<from -m flag, or null>"
     }
     ```
   - Clear top-level fields: set `owner`, `branch`, and `phase` to `null`. Set `acquired_at` to `null`. Set `last_touched` to now.
5. **Write `lock.json`** back to disk.
6. **Report** to the user:
   > Released the lock on `<design-name>`. Anyone can now claim it by running the next lock-enforcing skill — no `--force-takeover` required. Prior holder recorded in `previous_owners[]`.
7. **Suggest next step**: remind the user the design artifacts (`design.md`, `plan.md`, etc.) are still on the branch. They should commit + push the updated `lock.json` so the released state is visible to others.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — you can only release your own lock unless `--force` is passed with explicit confirmation.
- Do NOT delete the design directory or any artifacts. This skill only modifies `lock.json`. To archive a finished design, use `/tdd-design-complete`.
- Do NOT commit on the user's behalf. Remind them to commit + push the updated lock.
- `--force` is a power user option; never use it autonomously (e.g., inside `--auto` modes).
- A released lock leaves `previous_owners[]` as the audit trail. Do not truncate that array.
