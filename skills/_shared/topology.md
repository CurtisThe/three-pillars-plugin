# Workspace Topology

Canonical reference for the three-pillars physical workspace layout — the seat, the worktree host, the design worktrees, and the broken states the seat-resolution helper can detect. Other skills reference this doc rather than re-describing the topology inline.

For collaboration conventions (branch-per-design, advisory locks, preflight) see `skills/_shared/collaboration.md`.

---

## The Seat

**A checkout is the seat iff it is a non-bare clone whose working tree is the base checkout / worktree host, not under a sibling `*-wt/` dir.**

More precisely: given a repo at `<toplevel>`, it is the seat when all three hold:

1. `git rev-parse --is-bare-repository` returns `false` (non-bare — the `.git/config` `core.bare` bit is not set).
2. The path of `<toplevel>` is **not** under a sibling `*-wt/` directory (it is the worktree host, not one of its hosted worktrees).
3. It is the checkout that hosts the design worktrees — i.e. `git worktree list` shows it as the primary worktree.

The seat is **derived, not declared**: no marker file or committed config records it. Resolution reads observable git state (`core.bare`, `worktree list`, path shape) and is idempotent. See `skills/_shared/seat_resolve.sh` for the canonical derivation.

**Seat-ness is a property of the checkout, not of its current HEAD.** The operator may transiently be on a branch other than `{base}` while in the seat (e.g. viewing history). Resolution does not require `HEAD == {base}`.

---

## Canonical Layout

```
<repo>/              ← the seat (non-bare, on {base} by convention)
  .git/              ← git internals live here as a subdir (normal checkout)
  skills/
  three-pillars-docs/
  ...

<repo>-wt/           ← sibling worktree root (all design worktrees live here)
  <name1>/           ← worktree for tp/<name1>   (on branch tp/<name1>)
  <name2>/           ← worktree for tp/<name2>   (on branch tp/<name2>)
  ...
```

- `<repo>/` is on `{base}` (master or main) and is the **orchestration seat** — where fleet launches, merge-queue drains, and cross-design orchestration happen.
- `<repo>-wt/<name>/` are the **design worktrees**, each on its own `tp/<name>` branch.
- The seat and its worktrees share a single object store; branches are independent.

---

## Cross-Machine Bootstrap

When setting up on a new machine, clone normally — **do not use `--bare`**:

```bash
git clone <url> <repo>          # plain clone — results in a non-bare seat by default
cd <repo>                       # this checkout IS the seat
git worktree add ../<repo>-wt/<name> tp/<name>   # add a design worktree
```

**Why `git clone` and not `git clone --bare`:** `core.bare` lives in local `.git/config` and does not travel via `git push`. A `git clone` without `--bare` produces a non-bare checkout by default, so following this bootstrap avoids the `core.bare=true` footgun entirely. A bare clone would require a `git config core.bare false` fixup before any skill can treat the checkout as the seat.

If you arrived at a bare checkout accidentally (see `core-bare-flip` below), the repair is:

```bash
git config core.bare false
git reset --hard origin/{base}   # only if the working tree is stale / unpopulated
```

Or run the worktree management skill's `seat --apply` command to have the framework detect the state and offer the exact command.

### Dynamic Bleed Immunization

The static `--bare` footgun above is a **one-time bootstrap mistake**. There is a second, harder-to-detect class: **dynamic bleed**.

When Claude Code's `isolation=worktree` harness creates or tears down agent worktrees, it sets `core.bare=true` in the seat's **shared** `.git/config` as a side effect. This is a harness bug (M16 in `three-pillars-docs/known_issues.md`) that re-occurs on every fleet or supervised run — the seat reverts to `(bare)` silently mid-session even on a correctly-bootstrapped repo. Instrumented evidence: 25 heals in one run (2026-06-09).

**Root fix (two-part):** install once via the worktree management skill's first-run offer or `seat --apply` (missing-immunization repair):

1. **`extensions.worktreeConfig=true`** — isolates per-worktree git config from the seat's shared `.git/config`, so the harness writes land in the worktree's local config instead of bleeding into the seat.
2. **`heal-core-bare` hook** — installed via `skills/_shared/bootstrap_immunization.py` into `.git/hooks/post-checkout` and `.git/hooks/post-merge`. Detects the bleed state (`core.bare=true` + `.git/` subdir present) and flips `core.bare=false`. No-op on a healthy repo.

The installer (`skills/_shared/bootstrap_immunization.py`) is **consent-gated**: it runs only via the recorded first-run offer (condition 6 of `skills/_shared/first-run.md`'s cheap-path) or an explicit `yes` in the worktree management skill's `seat --apply` missing-immunization repair. The config record (`worktree_immunization` block in `.three-pillars/config.json`) suppresses re-offers after applied or declined.

---

## Bare-Hub Variant

Some operators prefer a `git clone --bare` hub at `<repo>/` with design worktrees checked out via `git worktree add`. This layout is **supported but warned** — it works, but it is non-canonical:

```
<repo>.git/          ← bare hub (git internals at toplevel, no .git/ subdir)
<repo>/              ← a git worktree add for {base} (the "seat" in this variant)
<repo>-wt/<name>/    ← design worktrees
```

When the seat resolver detects a genuine bare hub **plus** a standing `{base}` worktree, it classifies the state as `bare-hub-variant` and emits a single note. Consolidation paths (offered, not auto-applied):

1. Flip the hub to non-bare: `git config core.bare false` (makes the hub the canonical seat).
2. Keep the standing `{base}` worktree as the canonical seat (leave the bare hub as-is; treat the worktree as the coordination point).

Neither is auto-applied; the operator picks one and the worktree management skill's `seat --apply` command will route accordingly.

---

## Broken-State Catalogue

The seat-resolution helper (`seat_resolve.sh`) classifies every reachable git state into one of **eight** closed verdicts. Three of those are broken states that warrant repair:

| Verdict | What happened | Repair |
|---|---|---|
| `core-bare-flip` | The seat checkout has `core.bare = true` in `.git/config` while still having a real working tree (`.git/` subdir present). Git reports it as `(bare)`, refuses `git status`, and makes every "run from the main checkout" step silently inapplicable. | `git config core.bare false` (+ `git reset --hard origin/{base}` if the tree is stale). The worktree management skill's `seat --apply` command offers this repair interactively. |
| `missing-seat` | No non-bare `{base}` checkout / worktree host is reachable. Either a genuine bare hub with no standing `{base}` worktree, or the seat worktree was removed after teardown. `repair_hint: add-worktree`. | `git worktree add <repo>-host {base}`. The worktree management skill's `seat --apply` command routes on the `repair_hint` field. Cross-machine bootstrap (no local repo at all) uses `git clone` per the Bootstrap section above. |
| `redundant-base-worktree` | A `*-wt/{base}` worktree (e.g. `*-wt/master`) shadows the base checkout, creating an ambiguous "seat." | `git worktree remove <repo>-wt/{base}` after the standard cleanliness gate. The worktree management skill's `seat --apply` command offers this repair after a cleanliness check. |

The remaining five verdicts in the closed set:

| Verdict | Meaning |
|---|---|
| `seat-healthy` | The canonical state: non-bare, seat is the worktree host, no redundant `{base}` worktree. |
| `design-worktree` | The cwd is inside a `*-wt/` worktree — normal, not the seat. |
| `bare-hub-variant` | Genuine bare hub + a standing `{base}` worktree. Supported-but-warned (see above). |
| `unknown-worktree` | A registered worktree that fits none of the above (e.g. outside `*-wt/`, not the host). Reported, not repaired. |
| `indeterminate` | A git command errored (not a repo, corrupt). Fail-open: the resolver emits `state=indeterminate` and exits 0. |

### The `core-bare-flip` discriminator

The most error-prone distinction is `core-bare-flip` (a real checkout wrongly flagged bare) vs. a genuine `git clone --bare` hub. The helper uses a single reliable test:

- **`[ -d <toplevel>/.git ]`** — a normal checkout (even if `core.bare=true` was set after the fact) keeps its git metadata in a `.git/` **subdirectory** at toplevel. A genuine `git clone --bare` hub has the git internals **directly at** toplevel with no `.git/` subdir.

Therefore:
- `is-bare-repository == true` **AND** `[ -d <toplevel>/.git ]` → `core-bare-flip`
- `is-bare-repository == true` **AND NOT** `[ -d <toplevel>/.git ]` → genuine bare hub → `missing-seat` or `bare-hub-variant`

Do NOT use `git rev-parse --show-toplevel` or `git ls-files` to establish physical-tree presence: `--show-toplevel` exits 128 on the `core-bare-flip` case (proving why the resolver cannot use it), and `ls-files` reads index content, not on-disk presence.

The `<toplevel>` value itself is obtained from the first `worktree <toplevel>` line of `git worktree list --porcelain` — this line is present **even when `core.bare=true`**, making it the reliable source even on the footgun case.

---

## The Orchestration Session

The orchestration Claude session lives in the seat and stays on `{base}` by convention. From the seat it:

- Launches design worktrees (fleet and worktree management skills).
- Drives merge-queue drains (`/tp-post-merge`).
- Coordinates cross-design campaigns.

Individual designs and spikes are spun into per-design worktrees (`<repo>-wt/<name>/` on `tp/<name>`). The orchestrator never moves into a design worktree — it remains in the seat, which is why the seat's health is a precondition for any orchestrated fleet operation.

Two protocol consequences: design worktrees are provisioned by the collaboration preflight's seat-aware branch-offer (`collaboration.md` §Preflight step 4) — never by an in-place `git checkout -b` on the seat; and the seat's own paper trail stays committable mid-fleet — the worktree-isolation guard passes a seat commit whose staged paths are exclusively under `three-pillars-docs/tp-designs/orchestration/**` (one staged path outside refuses as usual).

For the actor-identity half (who is the orchestration session, session handoffs), see the `orchestration` slot handoff in `three-pillars-docs/tp-designs/orchestration/`.

---

## Quick-Reference Cheatsheet

```bash
# Detect the current seat state (from anywhere in the repo):
seat_resolve.sh --detect

# Confirm you are in the seat (cheap boolean — exit 0 = yes, exit 1 = uncertain):
seat_resolve.sh --am-i-seat

# Print the resolved seat path (or NONE):
seat_resolve.sh --where

# Offer to repair any broken state (interactive):
# Use the worktree management skill's `seat --apply` command.

# Bootstrap on a new machine:
git clone <url> <repo>
cd <repo>
git worktree add ../<repo>-wt/<name> tp/<name>
```
