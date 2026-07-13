# Commit After Work

When a skill produces a substantial artifact, it commits that artifact at the end of the skill. The working tree should be clean (for paths the skill touched) when the skill returns control to the user. This eliminates the "constant untracked changes across phases" problem — every phase boundary is a commit boundary.

## Which skills apply this protocol

**Opt-in** (commit at the end):
- Setup: `/tp-setup`, `/tp-docs-init`, `/tp-test-setup`
- Design pipeline: `/tp-design`, `/tp-design-detail`, `/tp-plan`
- Implementation: `/tp-task-cycle` (one commit per full red-green-refactor cycle), `/tp-phase-implement` (stragglers only), `/tp-phase-review`, `/tp-implementation-audit`
- Spike pipeline: `/tp-spike`, `/tp-spike-plan`, `/tp-spike-implement` (one commit per experiment), `/tp-spike-results`
- Learn / docs: `/tp-design-learn`, `/tp-spike-learn`, `/tp-docs-update`
- Release: `/tp-design-release` (the lock change is the substantial work)

**Do not apply** (skills don't commit):
- Audit-only skills that don't write files: `/tp-design-audit`, `/tp-plan-audit`
- Session state on gitignored paths: `/tp-session-save`, `/tp-session-restore`, `/tp-session-clear`
- Read-only guides: `/tp-guide`

**Handles its own commit** (does not reference this doc):
- `/tp-design-complete` — commits the archival + opens the PR. See that skill's SKILL.md for the full flow.

## The protocol

Run this at the end of the skill, after all artifact files are written.

### 1. Identify the artifact paths

Each calling skill must pass a concrete, enumerable list of paths it just produced — e.g., `three-pillars-docs/tp-designs/{name}/design.md` and `three-pillars-docs/tp-designs/{name}/lock.json`. Never stage a broad directory.

### 2. Check for unrelated WIP

Run `git status --short`. If any changed path is **outside** the artifact list above, stop and tell the user:

> I'm about to commit `{skill-name}`'s artifacts but the working tree has unrelated changes: `{paths}`. Commit or stash them first so the completion commit stays focused.

Do not proceed until the user resolves it. The skill never sweeps unrelated WIP into its commit.

### 3. Stage only the artifact paths

Stage the specific paths the skill produced. **Never** use `git add -A`, `git add .`, or `git add {wide-dir}`.

```bash
git add {path1} {path2} ...
```

### 4. Commit with a scoped, conventional message

See the message table below. The message follows `{Verb}: {design-name} {detail}` so `git log --oneline` reads like a changelog of the design's lifecycle.

```bash
git commit -m "{message}"
```

**Do not add any Co-Authored-By trailer.**

### 5. Handle hook failures

If `git commit` fails (pre-commit hook, lint, type check, etc.), stop and surface the output to the user. **Never** retry with `--no-verify`. The user must fix the underlying issue — a blocked commit means something's wrong with the work, not with the hook.

### 6. Push after each commit

After a commit succeeds, push it to `origin` on the design's `tp/*` branch:

```bash
git push origin {branch}
```

**Fail-open**: if the push fails (no network, diverged remote, auth issue, etc.), print one concise line reporting the failure and move on — the commit stays local. **Never** retry, and **never** pass `--force`; a failed push never blocks or reverts the commit that was just made. Autonomous / orchestrator skills report the failed push the same way (a logged line, not a fatal error) and keep running.

The **PR boundary is unchanged**: opening a PR is still reserved for `/tp-design-complete`. Push-after-commit only means each artifact commit becomes visible on `origin/tp/*` as it happens, closing the window (per `skills/_shared/collaboration.md`'s branch-creation push) where the remote branch existed but sat empty until completion. It does not change who opens the PR or when.

Orchestrated proof-currency flows (e.g. `/tp-run-full-design` Tier 7's head-bound proof comment) still own their own final-push ordering — push-after-commit is a commit-time convention and is orthogonal to the "proof must be the last branch action" rule those flows enforce.

## Commit message conventions

| Skill | Message template |
|---|---|
| `/tp-setup` | `Setup: vision` |
| `/tp-docs-init` | `Docs: init project docs` |
| `/tp-test-setup` | `Setup: test infrastructure` |
| `/tp-design {name}` | `Design: {name} high-level` |
| `/tp-design-detail {name}` | `Design: {name} detailed` |
| `/tp-plan {name}` | `Plan: {name}` |
| `/tp-task-cycle` | `Implement: {design-name} {phase}.{task} — {task-title}` |
| `/tp-phase-implement {name}` | `Implement: {name} phase-{n} cleanup` (only if stragglers remain after per-task commits) |
| `/tp-phase-review {name}` | `Review: {name} phase-{n}` |
| `/tp-implementation-audit {name}` | `Audit: {name} implementation` |
| `/tp-spike {name}` | `Spike: {name} design` |
| `/tp-spike-plan {name}` | `Spike: {name} plan` |
| `/tp-spike-implement {name}` | `Spike: {name} {phase}.{experiment}` (one per experiment) |
| `/tp-spike-results {name}` | `Spike: {name} results` |
| `/tp-design-learn {name}` | `Learn: {name} design` |
| `/tp-spike-learn {name}` | `Learn: {name} spike` |
| `/tp-docs-update` | `Docs: update {file1},{file2}` (comma-separate; omit repeated "three-pillars-docs/" prefix) |
| `/tp-design-release {name}` | `Release: {name}` (or `Release: {name} (force)` if `--force` was used) |
| `/tp-design-complete {name}` | `Complete design: {name}` (owned by that skill — not this protocol) |

## Lock file handling

If the skill acquires or refreshes `three-pillars-docs/tp-designs/{name}/lock.json` during its preflight (per `skills/_shared/collaboration.md`), include the lock file in the **same** commit as the content artifact. Don't produce a separate "update lock" commit.

The exception: `/tp-design-release` commits only `lock.json` — the lock change *is* the substantial work.

## User-initiated opt-out

If during a skill run the user explicitly asks to skip the commit ("don't commit that", "I'll commit it myself"), honor it. Leave the artifacts in the working tree (unstaged) and tell the user what's there. Do not prompt again — one ask is enough for the rest of that skill run.

## Autonomous mode

In `--auto` modes (e.g., `/tp-spike-auto`), commits are **required** — the whole point is unattended execution. If a commit fails (hook rejection, unrelated WIP detected), the skill logs the failure to `decisions.md` and stops the autonomous pipeline rather than bypassing. See `skills/_shared/auto-mode.md` for failure-handling conventions. The push in step 6 stays fail-open even here: a failed push is logged to `decisions.md` as a reported line, not treated as a pipeline-stopping failure — only a failed *commit* stops the pipeline.

## Orchestrator skills

Orchestrator skills (`/tp-phase-implement`, `/tp-spike-implement`, `/tp-spike-auto`) delegate the bulk of their commits to the inner skills they invoke (`/tp-task-cycle`, etc.), each of which pushes per step 6. At the end of the orchestrator run, check for stragglers: if `git status --short` shows any staged or unstaged changes remaining, the orchestrator commits them with a "cleanup" message and pushes it the same fail-open way. If the tree is clean, the orchestrator skips its own commit (and push).

## Hot-patch lane

The hot-patch lane sits *below* `just-do-it` and **outside** the weight-class set
(see `weight-class.md` §Hot-patch lane cross-note). It is not a design class —
it has no scope-time because the patch is the scope. Use it for urgent, narrow
fixes that cannot wait for a full branch + design cycle.

**Lane shape:** seat-exempt single-commit PR on a throwaway worktree.

```
git worktree add -b hot-patch/<slug> .claude/worktrees/hot-patch-<slug>
# stage fix + ledger append in the worktree
git -C .claude/worktrees/hot-patch-<slug> commit \
    --trailer "hot-patch: <trigger>" \
    -m "Hotfix: <summary>"
gh pr create --base master --head hot-patch/<slug>
# operator merges:
gh pr merge --merge <PR-NUMBER>
git worktree remove .claude/worktrees/hot-patch-<slug> && git branch -d hot-patch/<slug>
```

**Commit message row** (message-template table):

| Lane | Message template |
|---|---|
| hot-patch lane | `Hotfix: <summary>` + trailer `hot-patch: <trigger>` |

**Eligibility (all required):**

1. Trailer self-declaration: commit carries `hot-patch: <trigger>` (non-empty trigger).
2. Hard mechanical exclusions enforced at commit time: the commit must not touch
   `.three-pillars/`, gate/enforcement files (`framework-check.sh`,
   `deterministic_gate.py`, `land.py`, `gate_cli.py`, `merge_gate.py`, etc.), or
   the lane's own modules and their tests (`hot_patch_check.py`, `hot_patch.py`,
   `hot_patch_ledger.py`, `test_hot_patch_check.py`, `test_hot_patch_ledger.py`,
   `test_hot_patch_anomaly.py`, `test_hot_patch.py`, `test_hot_patch_stanza.py`).
3. Diff cap: ≤150 changed lines (adds + dels over `git show --numstat`), with the
   ledger append (`hot-patches.md`) excluded from the sum. Binary files fail.

**Trailer grammar:** `hot-patch: <trigger>` where `<trigger>` is free-text
describing the trigger event (e.g., `fix teardown order after fleet launch`).

**Ledger obligation:** append a ~5-line entry to
`three-pillars-docs/tp-designs/orchestration/hot-patches.md` with format:

```
- <sha> | <date> | trigger: <trigger> | broke: <what-broke> | fix: <why-this-fix> | touched: <surface>
```

Preferred path: the entry **rides in the same commit** as the fix (paper arrives
with the patch). Backstop: same-day UTC deadline, enforced fail-closed — the
hot-patch eligibility check hard-fails the next commit while any entry is
overdue. The ledger is size-exempt by location (`three-pillars-docs/tp-designs/` exempt prefix); no
rotation in v1.

**Scan-cost expectation:** the post-baseline `--since` anomaly scan is acceptable
at the observed hot-patch rate. Re-evaluate if master history exceeds ~10k commits
post-baseline.

**Merge:** operator only — never auto-merge. Use `gh pr merge --merge` (merge
commit; squash is out-of-protocol and self-flags the anomaly scan). The standard
merge gate runs un-bypassed; hooks always fire on every worktree commit. Gate
bypass is denied.

**What the hot-patch eligibility check catches:** (a) overdue ledger entry; (b) trailered commits
violating the exclusion list or diff cap; (c) post-baseline non-merge master
commits touching framework code — these are anomalies. Arm (c) keys on
committer date, which a determined actor can backdate; the threat model is
honest-operator-under-pressure, not adversarial forgery.

## Rationale

Frequent, scoped commits produce a clean audit trail at every design phase and prevent the "I have 40 files of uncommitted work across design + implementation" failure mode. Combined with branch-per-design, this means every phase of every design is recoverable, reviewable, and mergeable independently. `/tp-design-complete` then squashes/merges the branch to base, so downstream repos see a clean history if they prefer.
