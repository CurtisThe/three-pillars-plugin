---
name: tp-migrate
description: Migrate a three-pillars repo from the legacy docs/tdd-* layout to the current three-pillars-docs/tp-* layout. Wraps skills/_shared/migrate.py.
argument-hint: "[--repo {path}]"
---

# Migrate

Move a repo from the legacy `docs/tdd-*` layout to the current `three-pillars-docs/tp-*` layout. This skill is a thin wrapper around `skills/_shared/migrate.py` — it handles the dry-run preview and user confirmation, then delegates the actual work to `migrate.py --apply`.

**Argument**: `--repo {path}` (optional) — defaults to current working directory.

## Prerequisites

- The repo's working tree must be clean (no uncommitted changes). `migrate.py --apply` refuses to proceed otherwise.
- Python 3 must be available (same dependency as `release.sh`).

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md. **Exception**: this skill is the explicit exception to first-run's old-layout-detected refusal — the refusal does NOT apply when the calling skill is `tp-migrate`, since the whole point of this skill is to migrate. Branch-protection and release checks still apply normally.

1. **Show the plan**: run `python3 "$TP_ROOT"/skills/_shared/migrate.py --dry-run --repo {repo}` and print its output verbatim.
2. **Branch on the dry-run output**:
   - If the output says the repo is already migrated: report and stop. No work needed.
   - If the output says the repo is already on the current layout: report and stop. No work needed.
   - Otherwise, the output is a list of moves and rewrites. Continue.
3. **Confirm with the user**: ask `"Apply this migration plan? (yes/no)"`. Stop on `no`.
4. **Apply the migration**: run `python3 "$TP_ROOT"/skills/_shared/migrate.py --apply --repo {repo}`. This delegates everything to migrate.py — moves, rewrites, the new commit, and the config stamp. This skill itself must not stamp the migration field; ownership of that field belongs to migrate.py alone.
5. **Read back and report**:
   - Read `.three-pillars/config.json` and confirm `migration.completed_at` is non-null and `migration.from_layout` is `"docs+tdd"`.
   - Print the MEMORY.md advisory that migrate.py emitted, plus a one-line summary: `"Migrated repo in commit {sha}. Run /tp-guide to see what's next."`

## Rules

- **No design-name argument.** Unlike most `tp-*` skills, this one operates on the whole repo, not a single design directory, so the `skills/_shared/validate-name.md` convention does not apply here.
- **Migration field ownership**: `migrate.py --apply` is the sole authority for the migration completion field. This skill never touches it directly — it only reads back to confirm.
- **Atomicity is migrate.py's responsibility.** If migrate.py exits non-zero, do not attempt to repair state — report the stderr output and stop. The user can re-run after fixing the root cause (e.g., committing uncommitted work).
- **Branch grandfathering** — migrate.py never renames the in-flight `tdd/{name}` git branches or rewrites `lock.json` branch fields. Those stay as historical record until each design completes. This skill does not override that behavior.
- **No --auto mode.** Migration is a one-time, destructive-on-disk operation that must be human-reviewed. Refuse if `--auto` is passed.
- **MEMORY.md is out of scope**. migrate.py prints an advisory pointing at it; this skill surfaces that advisory to the user but does not attempt to rewrite memory files.
