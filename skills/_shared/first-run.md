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
6. **Worktree immunization is settled** — read `worktree_immunization` from the already-loaded config. Condition is satisfied if `worktree_immunization.applied_at` is non-null OR `worktree_immunization.declined` is true. This is a single config-read condition (no network, no subprocess) that rides the config read from condition 1. Cost: zero additional I/O on the hot path.
7. **GitHub PR-author is settled** — read `github` from the already-loaded config. Condition is satisfied if `github.pr_author_account` is non-null OR `github.declined` is true OR no `origin` remote is configured. Like condition 6, this rides condition 1's config read — a single config-read condition, zero extra I/O.

If **all seven** conditions hold, **return immediately**. The skill proceeds with no prompts. This is the hot path on every invocation in a healthy repo for a settled user; it must stay bounded by two file reads + one PATH probe + one constant-time `git rev-parse` (seat probe), no network.

If any condition fails, fall through to the relevant detection section below, in the order listed (migration → branch protection → aider-install → seat-state → worktree-immunization → GitHub PR-author). Conditions 1–3 failing routes to migration/branch-protection; condition 4 failing (aider absent + state is `needs-prompt` or `needs-prompt-remind-elapsed`) routes to the aider-install section; condition 5 failing (`seat_resolve.sh --am-i-seat` exits 1) routes to the `## Seat-state detection` section; condition 6 failing routes to the `## Worktree-immunization offer` section below; condition 7 failing routes to the `## GitHub PR-author offer` section below.

## Worktree-immunization offer

Runs when condition 6 fails (i.e., `bootstrap_immunization.cheap_check(repo)` returns `needs-prompt`). The offer installs `extensions.worktreeConfig=true` and the `heal-core-bare` hook to prevent the harness `core.bare` bleed (see M16 in `three-pillars-docs/known_issues.md`).

Invoke `python3 "$TP_ROOT"/skills/_shared/bootstrap_immunization.py` status, then offer:

> "Seat immunization protects your repo from the harness `core.bare` bleed (M16). Apply now? [yes/no]"

- **yes**: call `bootstrap_immunization.apply(repo)` then `mark_applied(repo)`. Confirm success in one line.
- **no**: call `mark_declined(repo)`. Never re-asks (declined is sticky per config record).
- **`--auto`**: skip the prompt; append a `[first-run]` entry to `decisions.md` (same format as branch-protection auto-skip). Never mutate.

The offer fires at most once per repo (the `worktree_immunization.applied_at` / `declined` fields suppress repeats). It never fires on a second invocation if the user already answered.

## GitHub PR-author offer

Runs when condition 7 fails (i.e., `github_auth_check.check(repo)` returns `needs-prompt`). The offer sets up a secondary bot GitHub account as the PR author on this repo's completion PRs, so the operator's own account is free to submit the APPROVED review the merge gate's human-approval predicate requires — see `skills/_shared/github_pr_author.py` for the chokepoint that reads this configuration.

Invoke `python3 "$TP_ROOT"/skills/_shared/github_auth_check.py --repo .` (or call `check()` directly), then branch on `action`:

- `skip-no-origin` — no GitHub remote; nothing to offer. No write.
- `skip-decided` — `github.pr_author_account` is set OR `github.declined` is true. The operator has already answered.
- `skip-gh-missing` — `gh` is not on PATH; the offer is moot (no `gh`, no PR creation at all). Silent, no write, re-checks next run.
- `auto-skip` — under `--auto`, a `[first-run]` entry was appended to `decisions.md`. Continue.
- `needs-prompt` — offer interactively:

  > "Open design PRs as a secondary bot account so your main account can approve them? A machine account (e.g. `YourNameBot`) authors the PRs; you approve as yourself, which satisfies the merge gate's human-approval predicate. [account-name / no / skip]"

  - **account-name**: run `github_auth_check.verify_account(login)` to probe the `gh` keyring. On success, call `mark_configured(repo, login, review_requests=[...])` (optionally ask for a reviewer list in the same prompt), then **commit `.three-pillars/config.json` immediately** (`config: PR-author bot account (<login>)`) — the merge gate reads config from committed HEAD (`git show HEAD:.three-pillars/config.json`), so an uncommitted write is inert to the gate. On failure (the account isn't in the keyring), print the `gh auth login` instruction and do **not** write the config — the offer re-fires next run.
  - **no**: call `mark_declined(repo)`. Sticky — never re-asks.
  - **skip**: no write; re-offers next run.

The offer fires at most once per repo (the `github.pr_author_account` / `declined` fields suppress repeats).

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
| GitHub PR-author unconfigured, `origin` present, `gh` available | Skip the prompt; leave `github.pr_author_account` untouched. PRs open with ambient `gh` auth this run; the next interactive run still gets to offer the bot-account setup. | Medium |

The `decisions.md` lives in the design directory the skill is operating on (`three-pillars-docs/tp-designs/{name}/decisions.md`). If the file does not exist, create it with the Run Metadata header per `auto-mode.md` §Initialization. The first-run entry is appended chronologically alongside the calling skill's own entries.

**Note**: worktree-operating skills (tp-phase-implement, tp-spike-implement, tp-merge-from-main,
tp-design-complete, and the worktree-management skill) additionally run the cwd preflight after this preflight.
See the "Inline worktree-driving is unsupported" section of `collaboration.md` for the two controls
(fail-closed commit guard + fail-open cwd preflight) and the one-line fix.

## Resolve-root preamble

Every `tp-*` SKILL.md already reads this file as its first step, making this the single canonical home for the resolve-root snippet. Agents resolve `TP_ROOT` once per session and cache it; every helper invocation is then prefixed with `python3 "$TP_ROOT"/skills/…` or `bash "$TP_ROOT"/skills/…`.

### Bootstrap

```bash
TP_ROOT="$(bash <skill-dir>/../../skills/_shared/resolve_root.sh --skill-dir <skill-dir>)"
```

Replace `<skill-dir>` with the directory of the SKILL.md the agent loaded (the agent always knows this path). This uses probe 2 (skill-dir grandparent) as the bootstrap path — the agent always has it. Subsequent helper calls use the cached `$TP_ROOT`.

Example invocation after bootstrap:

```bash
python3 "$TP_ROOT"/skills/_shared/deterministic_gate.py "$PR_URL"
```

### Probe chain

`resolve_root.sh` tries four probes in order, first hit wins:

1. `$CLAUDE_PLUGIN_ROOT` — set by Claude Code for plugin skills; sentinel-checked.
2. `--skill-dir` grandparent (`<dir>/../..`) — agent-supplied; sentinel-checked.
3. Plugin-cache glob: `$HOME/.claude/plugins/cache/*/three-pillars*` — newest mtime wins among qualifying entries.
4. Dev-checkout fallback: `git rev-parse --show-toplevel` of the cwd — sentinel-checked (covers running inside the framework repo itself).

Sentinel: a candidate qualifies iff `<cand>/skills/_shared/first-run.md` exists.

On failure (all probes miss), the script prints one loud line to stderr and exits 1:

```
three-pillars: cannot locate the framework root — probed $CLAUDE_PLUGIN_ROOT, the skill directory, ~/.claude/plugins/cache/*/three-pillars*, and the current repo. Set CLAUDE_PLUGIN_ROOT to the plugin install root and re-run.
```

### Failure split (behavior 9)

When `TP_ROOT` cannot be resolved, the helper's failure class determines what to do:

- **Enforcement-path helpers** (`deterministic_gate.py`, `diff_balloon_guard.py`, `validate_design_floor.py`, file-size and worktree guards): **stop and surface the failure line**. These are blocking gates; running without a valid root would silently skip enforcement.
- **Fail-open convenience helpers** (`cwd_preflight.py`, `detect_unarchived.py`, registry print commands): emit exactly one loud skip line and continue:

  ```
  three-pillars: skipping <helper> (framework root not found) — fail-open
  ```

No helper's failure class flips — enforcement helpers stay blocking, convenience helpers stay fail-open. Only the skip line changes (silent skip → loud skip).

### Resolve a FREE _shared script

`$TP_ROOT` answers "where is *a* framework root", but on a FREE+PRO install it can land on the PRO cache, which does **not** carry FREE-only `_shared` modules — so a bare `python3 "$TP_ROOT"/skills/_shared/<name>` dies with `No such file or directory` (this failed live in PR #126). Resolve FREE `_shared` scripts through `resolve_script.py`, which prefers the repo's own copy when this checkout *is* a framework repo and falls back to the versioned plugin cache otherwise.

Reach `resolve_script.py` **git-toplevel-first**, because the pro cache **lags** — a brand-new FREE module (even `resolve_script.py` itself) is absent from an already-released pro cache, so it may not exist under `"$TP_ROOT"` on a dogfood machine:

```bash
NAME=github_pr_author.py   # basename of the FREE _shared script to invoke
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then
  RS="$TOP"/skills/_shared/resolve_script.py       # dogfood: repo copy is authoritative
else
  RS="$TP_ROOT"/skills/_shared/resolve_script.py   # consumer install
fi
TARGET="$(python3 "$RS" "$NAME")"                  # abs path on stdout, or exit 1 (fail-loud)
python3 "$TARGET" "$@"                              # invoke the resolved script with your args
```

`resolve_script.py` prints the resolved absolute path on stdout (exit 0) or a fail-loud diagnostic naming every probed root on stderr (exit 1) — never a silent wrong path. Adopt this at any FREE `_shared` call site with the `$TP_ROOT`-vs-repo ambiguity (the `github_pr_author.py` PR-author chokepoint is the primary one).

The snippet resolves off the **current cwd's** git toplevel (`git rev-parse --show-toplevel`), so a caller must run it from inside the framework checkout for the dogfood-first win — invoked from an unrelated directory the `if` branch fails and resolution falls back to `$TP_ROOT` / the versioned cache.
