# First-Run Preflight

Every `tp-*` SKILL.md invokes this protocol as its **first step**. It is the single place where the framework decides whether the current repo needs migration, branch protection, or release configuration before the skill can do its real work.

The protocol is **idempotent and fail-fast on the cheap path**: in the steady state where everything is configured, it costs one file read and zero prompts. Cost only grows when the repo is in a state that demands attention.

## Cheap-path early-exit

Before any other check, attempt to read `.three-pillars/config.json` per [`repo-config.md`](repo-config.md):

1. If the file exists, parses, and validates against the schema, AND
2. `migration.completed_at` is non-null (or `migration.from_layout` is null, indicating no migration was ever needed), AND
3. `branch_protection.applied_at` is non-null OR `branch_protection.declined` is true OR no `origin` remote is configured,

then **return immediately**. The skill proceeds with no prompts. This is the hot path on every invocation in a healthy repo and must stay a single file read.

Any failure of the three conditions above falls through to the relevant detection section below, in the order listed (migration → branch protection). There is no release detection: releasing the three-pillars plugin itself is a dev-only flow documented in `three-pillars-docs/RELEASING.md`, not a per-repo concern for installed projects.

## Old-layout detection

The migration subsystem owns this check. The preflight calls `migrate.detect()` from `skills/_shared/migrate.py`:

- **Triggers**: presence of `docs/vision.md` OR `docs/tdd-designs/` OR `docs/completed-tdd-designs/` OR `docs/tdd-designs/*/lock.json` keyed with old `tdd-*` skill names.
- **Action when detected**: refuse the calling skill's main work and tell the user:
  > This repo uses the legacy three-pillars layout (`docs/tdd-designs/`). Run `/tp-migrate` to migrate to the current layout (`three-pillars-docs/tp-designs/`) before continuing. The migration is reversible until you commit; `/tp-migrate --dry-run` shows the plan.
- **Action when clean**: continue to the next section.
- **`--auto` behavior**: refuse and log per `## --auto deferral` below — never silently migrate from inside another skill.

## Branch-protection detection

The full protocol is in [`branch-protection.md`](branch-protection.md). The cheap, programmable branches are implemented by [`branch_protection_check.py`](branch_protection_check.py); the interactive path (prompt the user, run `gh api`) is the agent's responsibility.

- **Skip silently** if `git remote get-url origin` fails (no GitHub remote → no protection to apply). Record nothing in config; do not prompt. The helper's `action == "skip-no-origin"` covers this case.
- **Skip** if `branch_protection.declined` is true OR `branch_protection.applied_at` is non-null. The user has already answered.
- **Otherwise**, invoke `branch_protection_check.check(repo, auto=...)`. The helper's `action` field tells you what happened:
  - `skip-no-origin` — nothing to do.
  - `fail-open-gh-missing` — config was written with `declined=false`, `applied_at=null`, `offered_at=now`; the manual `gh api` command from `branch-protection.md` was printed to stdout. Continue with the calling skill.
  - `auto-skip` — under `--auto`, a `[first-run]` entry was appended to `decisions.md`. Continue.
  - `needs-prompt` — `gh` is available and the user has not yet decided. The agent runs the prompt from `branch-protection.md` (yes / no / skip), then writes the appropriate config block.

The prompt fires at most once per `(repo, decision)` pair — the offered_at/applied_at/declined fields together suppress repeats.

## --auto deferral

When the calling skill was invoked with `--auto`, **no prompts fire**. The preflight makes the safest available decision and appends a `decisions.md` entry per the format in [`auto-mode.md`](auto-mode.md):

```markdown
### [first-run] <decision title>
**Question**: What would have been asked of the user
**Decided**: What was chosen
**Reasoning**: Why this choice was made
**Confidence**: High | Medium | Low
```

Concrete defaults under `--auto`:

| Detection | Auto decision | Confidence |
|---|---|---|
| Old-layout detected | Refuse the main work; log and stop. Do **not** auto-run `/tp-migrate` — migration is destructive and a human-in-the-loop is required. | High |
| Branch protection unset, `origin` present, `gh` available | Skip the prompt; leave config untouched. The next interactive run will offer setup. | Medium |

The `decisions.md` lives in the design directory the skill is operating on (`three-pillars-docs/tp-designs/{name}/decisions.md`). If the file does not exist, create it with the Run Metadata header per `auto-mode.md` §Initialization. The first-run entry is appended chronologically alongside the calling skill's own entries.
