---
name: tp-revert
description: "Revert a design landing: probe depth/forecast, apply git revert -m 1, carve out living docs, regenerate amendments, and land as a single-commit PR through the standard gate."
argument-hint: "{pr#|merge-sha}"
---

# tp-revert — Safe Design Revert

Reverts a previously-landed design merge commit. The skill is depth-gated (newest landing,
probe depth 0 only), runs a dry-run forecast, applies `git revert -m 1`, preserves living
docs via carve-out, regenerates amendments, and lands the result through the standard gate.

**Not lock-enforcing.** The target design's lock is already archived; nothing to claim.

---

## Steps

0. **Run first-run preflight** per `skills/_shared/first-run.md`. Resolve `$TP_ROOT` with the canonical form:

```bash
TP_ROOT="$(bash <skill-dir>/../../skills/_shared/resolve_root.sh --skill-dir <skill-dir>)"
```

The `{pr#}` argument requires no design-name validation (it is a PR number or merge sha,
not a design slug). Any `slug` extracted from the PR's `headRefName` is expected to match
`[a-z0-9-]+` per `skills/_shared/validate-name.md` — print a warning if it does not but
continue (the slug is used for labeling, not enforcement here).

### Step 1 — Probe

```bash
python3 "$TP_ROOT"/skills/tp-revert/scripts/revert_probe.py \
    --repo . (--pr {pr#} | --sha {merge-sha}) [--base master] --json
```

On `error` field non-null: print the error and stop.

### Step 2 — Depth gate (hard line)

- `depth > 0` → **REFUSE** with reality. Print the forecast `conflicted[]` set, the
  documented recipe below, and stop. Proceeding past newest landing (probe depth 0) is
  **manual-only** by the operator using the recipe. The skill never automates past
  newest landing (probe depth 0).
- `depth == 0` but `clean == false` (unexpected) → same refusal path. Never pretend it
  is safe.

The depth caveat: a revert is clean only while newest (probe depth 0). Once any later
merge lands, the probability of a clean revert drops sharply (probe result: 1/12 merged
PRs reverted clean overall — the one clean WAS the newest landing (probe depth 0); past
it, zero clean).

### Step 3 — Provision workspace

```bash
git worktree add .claude/worktrees/revert-{slug} -b revert/{slug} origin/{base}
```

**Slug derivation**: `{slug}` is taken from the probe JSON `slug` field. When `slug` is null (--sha path, or a re-land where the head is `revert/{slug}`), derive it from the original landing PR's `headRefName` via `gh pr view` on the commit's associated PR (strip `tp/`); for a re-land, strip `revert/` from the reverted PR's head to recover the original slug. If the slug remains underivable, ask the operator.

Placement under `.claude/worktrees/` and non-`tp/` branch keep the isolation guards
green: not the seat, not a tp/* worktree.

### Step 4 — Revert

```bash
cd .claude/worktrees/revert-{slug}
git revert -m 1 --no-commit {merge_sha}
```

Step 2 verified forecast clean. If a conflict occurs anyway: abort + refuse loudly.

```bash
git revert --abort   # on conflict
```

### Step 5 — Living-doc carve-out (amendment-only constraint)

Run the following three commands in order, checking exit status after each (stop loudly on failure):

```bash
# 1. Unstage ALL doc-tree changes (including re-added in-flight files like
#    tp-designs/{slug}/lock.json, candidates/, telemetry.json)
git reset -q HEAD -- three-pillars-docs/

# 2. Restore tracked doc files to HEAD — living docs are never textually unwound;
#    the archive is kept so cites remain live and the amendment has a home
git restore --worktree --source=HEAD -- three-pillars-docs/

# 3. Delete resurrected now-untracked in-flight files — the lock is NOT resurrected;
#    the in-flight registry stays clean
git clean -fdq three-pillars-docs/
```

**Rationale**: `git revert -m 1` re-creates tp-designs/{slug}/lock.json, telemetry.json, and
candidates/* (the archive move is undone). The whole-tree carve-out drops all of these in one
pass: reset unstages them, restore brings tracked doc content back to HEAD (living docs are
**never textually unwound** — they evolve forward; the design archive is **kept**), and clean
removes the resurrected untracked in-flight files. The carve-out covers the entire
`three-pillars-docs/` tree so no artifact can slip through.

### Step 6 — Regenerate doc state

Append the dated amendment to `three-pillars-docs/completed-tp-designs/{slug}/decisions.md`
per `skills/_shared/reconcile-protocol.md`. Use the template verbatim:

```markdown
### [amendment YYYY-MM-DD] Reverted PR #NN ({slug})
**Supersedes**: the Done row in the roadmap and the original landing
**Change**: landing backed out; revert PR #RR created
**Commit**: {revert-sha} / PR #RR
**Why**: <reason>
```

**6b.** Flip the roadmap status cell per `skills/_shared/living-doc-format.md`:

```
Done — PR #NN — [design](…)
  → Reverted — PR #NN → revert PR #RR — [design](…)
```

Bump `*Last updated:*` and add one History line.

**6c.** Add one `three-pillars-docs/known_issues.md` entry (the revert ledger): what
landed bad, what was reverted, links to both PRs.

**6d.** Verify with the reporter (never `--apply` in the revert path):

```bash
python3 "$TP_ROOT"/skills/_shared/reconcile_docs.py --slug {slug} --json
```

### Step 7 — Commit

Single commit scoped to the revert + doc amendments:

```
Revert: {slug} (PR #NN)
```

Never edit `deterministic_gate.py` — gate code is untouched.

### Step 8 — Land through standard gate

Push `revert/{slug}`, open a single-commit PR (body links original PR + forecast
evidence). The operator lands via `/tp-merge` — all six predicates (including
`pred_human_approved`, surfaced as the `tp:human-approved` label) apply unchanged.
No direct master commit (hot-patch anomaly flag).

The standard gate applies: the PR must PASS before `gh pr merge` is called.

### Step 9 — Bookkeeping (annotate-and-link)

Comment on the original PR ("reverted by #RR") and on the revert PR ("reverts #NN").

Note: merged PRs cannot be reopened on GitHub — reopen semantics are off the table
by platform fact.

Apply label `tp:reverted` on the original PR via the **REST labels API**, fail-open:

```bash
gh api repos/{owner}/{repo}/issues/{pr#}/labels --method POST \
    --field 'labels[]=tp:reverted'
```

Caveat: `gh pr edit --add-label` silently no-ops on this repo — use the REST labels
API above instead.

Design stays archived; lock and branch are **not resurrected**; MRU is untouched
(already cleared at post-merge).

### Step 10 — Re-land path

The revert PR is itself a landing — it creates a true merge commit on master. While
it is the newest landing (probe depth 0), `/tp-revert <revert-pr#>` re-lands the
original work through the same machinery (revert-of-a-revert).

Before re-entering Step 3 for a revert-of-a-revert, remove the leftover `revert/{slug}`
worktree and branch from the original revert (fail-open if absent):

```bash
git worktree remove .claude/worktrees/revert-{slug} --force  # fail-open
git branch -D revert/{slug}                                    # fail-open
```

Alternatively, use the distinct branch name `revert/{slug}-reland` for the re-land
workspace to avoid the collision entirely.

Past newest landing (probe depth 0), re-landing is a **new design cycle**.

---

## Bookkeeping

See Step 9 above. Summary:

- Comment both PRs (original ← reverted by #RR; revert ← reverts #NN).
- Label `tp:reverted` via REST labels API (fail-open).
- Design archive stays in place; no lock resurrection.

---

## Re-land path

The revert PR lands as a true merge. While newest landing (probe depth 0), run
`/tp-revert <revert-pr#>` to re-land the original work. Past newest landing
(probe depth 0), open a new design cycle.

---

## Documented recipe

Copy-pasteable for manual operator use (when the skill refuses past newest landing
(probe depth 0)):

```bash
git revert -m 1 <merge-sha>   # -m 1 selects the mainline parent — REQUIRED
                               # design PRs land as true merges; naive
                               # `git revert <merge-sha>` errors out:
                               # "is a merge but no -m option was given"
```

Depth caveat: the revert is clean only while newest (probe depth 0 = newest landing).

After reverting manually, apply the living-doc carve-out and amendment obligations
(Steps 5–6 above). The conflicted[] set from the probe is printed to help triage.

**Carve-out safety (manual checkout only)**: `git clean -fdq three-pillars-docs/`
deletes untracked files under the doc tree — including uncommitted orchestration notes
or any operator files not yet committed. In a personal checkout, run
`git clean -nd three-pillars-docs/` first (dry-run) and stash or move anything you
need to keep before running the `-f` form. (The skill's own automated flow is safe —
it always runs in a fresh worktree where no pre-existing untracked files are present.)
