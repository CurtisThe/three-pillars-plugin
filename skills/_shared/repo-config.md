# Repo Config (`.three-pillars/config.json`)

The single per-repo state file the framework reads on every skill invocation. Stores the small pieces of context that have to survive across invocations and across machines but don't belong inside any particular design.

## Location

`.three-pillars/config.json` at the project root. **Committed to git** — this is shared state, not per-developer state. The directory is bootstrapped at `.gitkeep` time and must NOT be gitignored. If a parent `.gitignore` rule (e.g. `.*`) catches the directory, add an explicit un-ignore: `!.three-pillars/`.

The file is created lazily by the first skill that needs to write to it. A repo with no `.three-pillars/config.json` is treated as a fresh repo (see `## Fail-open behavior`).

## Schema

The shape and constraints are defined by [`repo-config.schema.json`](repo-config.schema.json) (JSON Schema draft-2020-12). Two subsections under a top-level `schema_version: 1`:

- `migration` — `completed_at` (ISO-8601 UTC | null), `from_layout` (enum: `"docs+tdd"` | null). Sole writer of `completed_at` is `migrate.py --apply`; SKILL.md wrappers must never set this independently.
- `branch_protection` — `offered_at`, `applied_at` (ISO | null), `declined` (bool, default false), `profile` (enum: `"team-pr-1approval-noforce"` | null).

`additionalProperties: false` at every level. Unknown keys are a hard validation error — a typo in a write path fails closed rather than silently storing junk.

Release tracking is deliberately not part of this schema. Releasing the three-pillars plugin itself is a dev-only flow documented in `three-pillars-docs/RELEASING.md`; downstream projects that install the plugin have nothing to release, so a `release.*` subsection would be dead weight (and confusing) in their config.

## Atomic write

Every write goes through tmp-file-and-rename, so a partial write (process killed mid-flush, disk full, etc.) leaves the previous valid file intact:

```python
import json, os, tempfile
from pathlib import Path

def write_config(repo_root: Path, data: dict) -> None:
    target = repo_root / ".three-pillars" / "config.json"
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=target.parent, prefix=".config.", suffix=".tmp", delete=False
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, target)
    except Exception:
        os.unlink(tmp.name)
        raise
```

The `tempfile` lives in the same directory as the target so `os.replace` is a same-filesystem atomic rename (POSIX guarantee). Never write to `/tmp/` and then move — that crosses filesystems on many systems and falls back to a non-atomic copy.

## Schema version upgrades

`schema_version` is a hard `const: 1` today. The forward/backward compatibility rule is:

- **Newer code reading older config**: must handle. If a v2-aware code release reads a v1 file, it migrates the v1 shape to v2 before any further work and writes the upgraded config back atomically.
- **Older code reading newer config**: must fail closed. If a v1-only code release reads a v2 file, JSON Schema validation rejects it (`schema_version: 2` doesn't satisfy `const: 1`). The skill stops with a clear "this repo's config is from a newer framework version; upgrade your installed framework" message rather than running with partial understanding.

Adding a `schema_version: 2` requires a new schema file (`repo-config.v2.schema.json`), a documented v1→v2 migration function, and code that reads either version.

## Fail-open behavior

The framework prefers to keep working when the config is missing or unreadable, **for cheap-path operations**:

- **Missing file**: treat as a fresh repo; `first-run.md` triggers its detection paths and prompts the user. No error.
- **Parse error / invalid JSON**: log a one-line warning, treat as missing, fall through to `first-run.md`. Do not delete or rename the broken file — leave it for the user to inspect.
- **Schema validation error**: same as parse error. The user's broken file is preserved; the framework proceeds as though it were absent.

The exception is **write paths**: a skill that needs to *update* config (e.g. `migrate.py --apply` setting `completed_at`) reads-validates-mutates-writes. A read failure mid-update is a hard error — the skill stops rather than overwriting an unreadable file with a partial guess.

`first-run.md` codifies the cheap-path early-exit (`if config exists and all three subsections are non-null, return`) so the hot path stays a single read.
