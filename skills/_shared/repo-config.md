# Repo Config (`.three-pillars/config.json`)

The single per-repo state file the framework reads on every skill invocation. Stores the small pieces of context that have to survive across invocations and across machines but don't belong inside any particular design.

## Location

`.three-pillars/config.json` at the project root. **Committed to git** — this is shared state, not per-developer state. The directory is bootstrapped at `.gitkeep` time and must NOT be gitignored. If a parent `.gitignore` rule (e.g. `.*`) catches the directory, add an explicit un-ignore: `!.three-pillars/`.

The file is created lazily by the first skill that needs to write to it. A repo with no `.three-pillars/config.json` is treated as a fresh repo (see `## Fail-open behavior`).

## Schema

The shape and constraints are defined by [`repo-config.schema.json`](repo-config.schema.json) (JSON Schema draft-2020-12). Subsections under a top-level `schema_version: 1`:

- `migration` — `completed_at` (ISO-8601 UTC | null), `from_layout` (enum: `"docs+tdd"` | null). Sole writer of `completed_at` is `migrate.py --apply`; SKILL.md wrappers must never set this independently.
- `branch_protection` — `offered_at`, `applied_at` (ISO | null), `declined` (bool, default false), `profile` (enum: `"team-pr-1approval-noforce"` | null).
- `worktree_immunization` — `offered_at`, `applied_at` (ISO | null), `declined` (bool, default false). Tracks whether the `heal-core-bare` hook + `extensions.worktreeConfig=true` have been offered, applied, or declined. Mirrors the `branch_protection` block shape; `first-run.md`'s cheap-path condition reads it in one config-read. Written by `skills/_shared/bootstrap_immunization.py` (`mark_applied()` / `mark_declined()` / `mark_offered()`). Never re-asked after a recorded `declined=true` or non-null `applied_at`.
- `review` — code-review / merge-gate posture. Includes `approval_survives_safe_base_sync` and `base_sync_carry_max_chain` (documented below), plus `expects_copilot`, `require_human_approval`, `automation_identities` (see `repo-config.schema.json` for those).

`additionalProperties: false` at every level. Unknown keys are a hard validation error — a typo in a write path fails closed rather than silently storing junk.

### `review.approval_survives_safe_base_sync` + `review.base_sync_carry_max_chain`

The **base-sync approval carry** (`approval-survives-safe-base-sync` design): whether an approval or proof-of-review digest anchored on a head *before* one or more mechanical base-sync merges is still trusted after the head has moved.

- **`approval_survives_safe_base_sync`** (boolean). **Default-off**: absence, a corrupt/non-dict `review` block, or any truthy-non-bool value all fold to `false` — the carry activates ONLY on the literal boolean `true`. This is the deliberate *inverse* of this block's other keys (whose strict default is *on*): here the strict default is *off*, since the carry is a narrow, opt-in relaxation of an otherwise-strict gate.
- **`base_sync_carry_max_chain`** (integer, `1`–`20`, default `5`). Caps how many certified base-sync merges the carry's first-parent walk will cross before giving up; a chain past the cap fails closed with a re-approve-on-current-head remediation.
- **Committed-HEAD read**: both keys are read via the existing `_load_repo_config` path (`git show HEAD:.three-pillars/config.json`), the same mechanism `require_human_approval` already uses — **an uncommitted edit to this file cannot enable the carry**. Flipping the carry on is itself a committed, reviewable change.
- **What "certified" means**: the carry never trusts a PR comment, a local state file, or a producer's claim. Each link in the chain is independently re-derived from git objects alone by `skills/_shared/base_sync_cert.py` — merge shape (first-parent discipline), the second parent's ancestry on the base branch, an allowlisted `merge-tree` recompute, byte-equality outside the conflicted region, and a resolver byte-reproduction over a zero-drop backstop. The `basesync-cert.v1` PR comment posted by `/tp-merge-from-main` step 7 is audit trail only — forging, deleting, or misattributing it changes nothing (the gate never reads it).
- **Seat-locally-ahead over-block (accepted trade-off)**: when the seat carries local commits ahead of the freshly-fetched base tip (e.g. unpushed `three-pillars-docs/tp-designs/orchestration/` commits per `topology.md`'s orchestration-paper-trail allowance), the oracle checkout is no longer an ancestor-or-equal of the fetched base tip, and the carry **fails closed with no carry** even though the underlying chain may in fact be certifiable. This is a deliberate over-block, not a bug: remediate by pushing the seat's base branch (so the fetched tip catches up) or by re-approving on the current head. See `three-pillars-docs/completed-tp-designs/approval-survives-safe-base-sync/detailed-design.md` for the full independent-oracle guard spec.

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
