# First-Run Preflight

Every `tp-*` SKILL.md invokes this protocol as its **first step**. It is the single place where the framework decides whether the current repo needs migration, branch protection, or release configuration before the skill can do its real work.

The protocol is **idempotent and fail-fast on the cheap path**: in the steady state where everything is configured and the user has already answered the aider-install offer, it costs two file reads (per-repo `config.json` + per-user `aider-install.json`) plus one PATH probe + one constant-time `git rev-parse` (seat probe), and zero prompts. Cost only grows when the repo or the user is in a state that demands attention.

## Cheap-path early-exit

Before any other check, run the cheap-path probe:

1. Read `.three-pillars/config.json` per [`repo-config.md`](repo-config.md). It must exist, parse, and validate against the schema.
2. `migration.completed_at` must be non-null (or `migration.from_layout` is null, indicating no migration was ever needed).
3. `branch_protection.applied_at` must be non-null OR `branch_protection.declined` must be true OR no `origin` remote is configured.
4. **Aider-install is settled** — invoke `aider_install_check.aider_on_path()`; if it returns True, this condition is satisfied (the user already has aider, no offer needed). Otherwise invoke `aider_install_check.cheap_check()` and accept either `skip-decided` (user accepted/declined — sticky) or `skip-remind-pending` (remind-later target hasn't elapsed) as satisfying.
5. **Seat is a confirmed-healthy coordination point** — invoke `seat_resolve.sh --am-i-seat --repo .`. **Exit 0 satisfies the condition** (path-shape says seat AND the bare-bit is false → not the footgun, not a design worktree masquerading as the seat). This adds one constant-time subprocess (`git rev-parse --is-bare-repository` + a path-string test — no `worktree list`, no network) to the hot path. **Exit 1 (uncertain) does NOT early-exit** — it falls through to the `## Seat-state detection` section below, which runs the full `--detect`.

If **all five** conditions hold, **return immediately**. The skill proceeds with no prompts. This is the hot path on every invocation in a healthy repo for a settled user; it must stay bounded by two file reads + one PATH probe + one constant-time `git rev-parse` (seat probe), no network.

If any condition fails, fall through to the relevant detection section below, in the order listed (migration → branch protection → aider-install → seat-state). Conditions 1–3 failing routes to migration/branch-protection; condition 4 failing (aider absent + state is `needs-prompt` or `needs-prompt-remind-elapsed`) routes to the aider-install section; condition 5 failing (`seat_resolve.sh --am-i-seat` exits 1) routes to the `## Seat-state detection` section.

There is no release detection: releasing the three-pillars plugin itself is a dev-only flow documented in `three-pillars-docs/RELEASING.md`, not a per-repo concern for installed projects.

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

## Aider-install detection

The optional aider repo-map preamble (see `repo-map-preamble.md`) measurably reduces design-phase tokens when `aider` is on PATH. This detection block surfaces a one-time install offer the first time any `tp-*` skill runs on a machine without aider — mirroring the branch-protection shape, but state is **per-user**, not per-repo.

The cheap, programmable branches are implemented by `aider_install_check.py`; the interactive path (prompt the user, run `uv tool install` / `pipx install` / `<venv>/bin/pip install`) is the agent's responsibility.

- **Skip silently** if `aider_install_check.aider_on_path()` returns True. The user already has aider; nothing to offer. Record nothing.
- **Skip silently** if `aider_install_check.cheap_check()` returns `action == "skip-decided"` (the user has accepted or declined — sticky) OR `action == "skip-remind-pending"` (remind-later state, target time hasn't elapsed).
- **Prompt** if `action == "needs-prompt"` or `action == "needs-prompt-remind-elapsed"`. The agent renders one of the three scenarios below:

  | Scenario | Trigger | Prompt shape |
  |---|---|---|
  | (i) aider present | `aider_on_path() == True` | No prompt fires. |
  | (ii) aider absent, `.venv/` detected | `detect_project_venv(repo) is not None` | **Twin-path prompt**. Both "install into project venv" and "install user-level (uv/pipx)" rendered as labeled choices. Decline + "remind me later" also offered. |
  | (iii) aider absent, no `.venv/` | `detect_project_venv(repo) is None` | **User-level-only prompt**. "Install user-level (uv/pipx)", decline, "remind me later". No venv option shown (would be a confusing no-op). |

  See `repo-map-preamble.md` for the cost framing the agent quotes in the prompt copy ("typically saves 15–42% of design-phase tokens"). Render copy as **offering**, not nagging — the user is being told they have a choice, not pressured to take it.

- **Capture the user's response**:
  - "install into project venv" → call `install_project_venv(venv_path)`; on success `mark_installed("project-venv:<name>")`, on failure log to `decisions.md` (auto) or surface error (interactive).
  - "install user-level" → call `install_user_level()`; mark `mark_installed("uv-tool")` / `mark_installed("pipx")` / `mark_installed("manual")` depending on which path succeeded.
  - "decline" → `mark_declined()`. Sticky.
  - "remind me later" → `mark_remind_later()`. Default 7 days; re-fires at next `tp-*` invocation after that timestamp.

The prompt fires at most once per `(user, decision)` pair — the `decided` and `remind_after` fields together suppress repeats. Because state is per-user (not per-repo), a user who declines once is never prompted again on this machine, regardless of how many repos they touch.

## Seat-state detection

Runs when condition 5 fails (i.e., `seat_resolve.sh --am-i-seat` exited 1), OR when conditions 1–4 already routed here. Call `seat_resolve.sh --detect --repo .`.

**On a benign verdict** (`seat-healthy` / `design-worktree` / `unknown-worktree` / `indeterminate`): silent no-op — no prompt, no record. (`--am-i-seat` returns exit 1 from inside a `design-worktree` too — correct: a design worktree is *not* the seat, so it should not early-exit the seat gate, but `--detect` then confirms it is benign.)

**On a broken verdict** (`core-bare-flip` / `missing-seat` / `redundant-base-worktree`) or `bare-hub-variant`: surface the condition and **point the operator at the worktree-management skill's `seat` verb** (i.e. `seat [--apply]`) to repair. This preflight is **detect-only** — no repair verbs (`git config core.bare`, `git reset --hard`, `git worktree remove`) are run here. All repair lives behind the `seat --apply` offer + operator yes.

**`--auto`**: log the verdict to `decisions.md` per the `--auto deferral` format below; never prompt.

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
| Aider absent + no prior decision | Skip the prompt; leave `~/.three-pillars/aider-install.json` untouched (so the next interactive run still gets to ask). The skill's optional aider preamble will be no-ops for this run. | Medium |

The `decisions.md` lives in the design directory the skill is operating on (`three-pillars-docs/tp-designs/{name}/decisions.md`). If the file does not exist, create it with the Run Metadata header per `auto-mode.md` §Initialization. The first-run entry is appended chronologically alongside the calling skill's own entries.

**Note**: worktree-operating skills (tp-phase-implement, tp-spike-implement, tp-merge-from-main,
tp-design-complete, and the worktree-management skill) additionally run the cwd preflight after this preflight.
See the "Inline worktree-driving is unsupported" section of `collaboration.md` for the two controls
(fail-closed commit guard + fail-open cwd preflight) and the one-line fix.
