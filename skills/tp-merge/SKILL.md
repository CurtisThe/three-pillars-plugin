---
name: tp-merge
description: "Land a reviewed PR at the irreversible boundary: enforce the deterministic merge gate (require_merge_gate_pass — seven predicates incl. a current human approval, a fresh ci-local stamp, and a head-bound review-proof comment, plus the fragility_clear test-fragility predicate) and run the irreversible gh pr merge ONLY on PASS. Refuse on a blocked gate, printing the blocking predicate(s) and how to authorize. The base-into-branch base-sync operation is the separate /tp-merge-from-main skill."
argument-hint: "{pr-url|design-name}"
---

# tp-merge — the land gate (irreversible `gh pr merge`)

`/tp-merge` is the **land** skill: it crosses the one irreversible boundary in the
framework — running `gh pr merge` to land a reviewed PR onto its base. It is the sole
code site where the "the framework never crosses the irreversible boundary without an
explicit, current human approval" guarantee is enforced in code.

It does **not** sync the base into the branch, resolve living-doc conflicts, or rewrite
tracked files — that reversible base-into-branch operation is the separate
`/tp-merge-from-main` skill. `/tp-merge` only gates and lands.

> **Two distinct skills, one former name.** Before the human-approval-merge-gate design
> (D7), `/tp-merge` was the base-sync conflict resolver. That half is now
> `/tp-merge-from-main`. The `/tp-merge` name is retained for this **land** half, because
> operator and orchestrator references to "`/tp-merge`" mean *land/merge*. Keep them
> distinct: `/tp-merge-from-main` syncs the base in (reversible, below the gate);
> `/tp-merge` lands the PR out (irreversible, behind the gate).

## Arguments

- `{pr-url|design-name}` (required) — the PR to land. A PR URL is used directly; a design
  name resolves to its open completion PR.

## Prerequisites

- `gh` CLI installed and authenticated (the merge runs `gh pr merge`).
- The PR has been reviewed and is reviewed-stable (the autonomous loop pauses here — this
  step is the human's).

## The gate (load-bearing)

The land is gated by `require_merge_gate_pass(pr_url)` from
`skills/tp-merge-from-main/scripts/merge_gate.py` — the **fail-closed enforcing** form of
the deterministic merge gate. It evaluates the gate's predicates over the PR head SHA and
**raises `MergeGateBlocked` on any non-PASS verdict**, so a caller that ignores the return
value still cannot proceed. The gate carries **seven** head-SHA-keyed predicates, plus an
eighth, `fragility_clear`, that is on by default:

- **threads_resolved** — all review threads resolved. When this predicate blocks
  the refusal, `land.py` prints a remediation pointer:
  `/tp-pr-iterate {design} --dispose-only` (reply-and-resolve out-of-band).
- **mergeable** — PR is in MERGEABLE state.
- **checks_success** — all required CI checks settled and concluded SUCCESS.
- **copilot_on_head** — Copilot has reviewed the current head SHA.
- **human_approved** — a **current APPROVED human review** from a non-automation human
  is present on the head SHA. Absent / stale (review predates the head) /
  automation-authored → INDETERMINATE. This is the predicate the autonomous path can never
  satisfy: the autonomous path cannot produce a non-automation APPROVED review on the
  head out-of-band. The review's immutable `commit_id` is the currency check — a real
  content push leaves the prior review pointing to the old head (non-current → fail-closed).
- **ci_local_stamp** — a fresh SHA-keyed local-CI green stamp, required only when the
  repo declares `ci.gate_command`; the stamp is produced by running that command through
  `skills/_shared/ci_gate_run.py`, which stamps the head on rc 0. No `ci.gate_command`
  declared → the predicate is OMITTED (a roster note, not a FAIL) — declare the command
  to require this stamp. Declared but absent, stale, or dirty → FAIL; run
  `python3 $TP_ROOT/skills/_shared/ci_gate_run.py` to satisfy it.
  (dev-repo only: `ci.gate_command` is `scripts/ci-local.sh`.) Opt out explicitly
  per-repo via `review.require_ci_local_stamp: false`, even with a declared command.
- **review_proof_on_head** — a head-bound, non-degraded proof-of-review digest comment
  exists on the current head SHA, **authored by a trusted automation identity**: the
  framework's own gh login (`github.pr_author_account` when one is configured) + config `review.automation_identities` extras, and NOTHING
  else — the Copilot/native-bot automation floor is deliberately not digest-trusted
  (those identities never legitimately post digests, and a prompt-injected Copilot
  comment must not mint proof), and a drive-by commenter pasting a matching digest does
  NOT count. The `/tp-pr-iterate` review arm posts it each round. Absent / stale
  (head moved) / degraded / untrusted-author → INDETERMINATE; re-run the proof-bearing
  review on the current head. Opt out per-repo via `review.require_review_proof: false`.
- **Operator-accept** — an operator who cannot post the digest can still fill THAT slot
  with a prose accept: submit an APPROVED review on the current head whose body has the
  line `tp-accept: <full 40-hex head sha> <reason>`. It stands in for
  `review_proof_on_head` ONLY — `human_approved` (the same APPROVED review normally
  satisfies it) and every other predicate stay required; a bot/automation author or a
  COMMENTED review never counts. Check one with
  `python3 "$TP_ROOT"/skills/_shared/operator_accept.py check --pr-url <url> --head <sha>`
  (exit 0 found / 1 not). On a Gitea origin the accept is unavailable — exit 2 with
  `operator-accept unavailable on gitea (gitea-forge-adapter)`; use the review-proof path.
  When the slot rides an accept, `land.py` prints `merge rides an operator-accept:
  <detail>` before the `Merged` line, so the merge record names who accepted and why.
- **fragility_clear** — the PR adds no fragile test, per `skills/_shared/test-fragility.md`.
  Three conditions, each named in the FAIL detail: the fragility lint finds no gating hit
  on the lines the PR adds; no confirmed fragile item (from the implementation audit or the
  PR review loop) is open; and the changed tests have a run record for the PR head
  (`changed_tests_runs.py`) that passes. A missing or stale record fails, and the detail
  names the `record` command. An `unverified` record (no pytest runner) passes with a note
  unless `fragility.strict: true`, which fails it. To clear an open item, waive it by id
  with a reason, as the operator's own call:
  `python3 "$TP_ROOT"/skills/_shared/fragility_items.py waive --branch tp/{design-name} --id <item-id> --by <your-name> --reason "<why>"`
  (`--scope path-class` covers every item with the same path and class; an empty `--by` or
  `--reason` is refused). `fragility_items.py list --branch tp/{design-name}` prints the
  open ids. Opt out per-repo via `fragility.merge_predicate: false`; the roster then shows
  `fragility_clear` as OMITTED `skipped (opt-out)`, never silently absent.

The emitted label is always *"mechanical predicates hold — semantics UNVERIFIED — your
review is the only semantic check"* — shown even on PASS. The gate never asserts the PR is
ready-to-merge-without-caveats; the operator's review is the only semantic check.

## Steps

> A PR head that still holds unnumbered issue IDs (`### <S>-new-<slug>`) is refused; run `python3 "$TP_ROOT"/skills/_shared/number_issues.py --base <base> --commit` first, or `/tp-merge-from-main` when it reports the IDs as inherited (the base already numbered them; see `skills/_shared/issue-id-placeholders.md`).

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

1. **Resolve the PR.** If a PR URL was passed, use it. If a design name was passed,
   resolve it to the design's open completion PR (`gh pr view`). Validate `{design-name}`
   per `skills/_shared/validate-name.md` when a name (not a URL) is passed.

1a. **Record the changed-tests run for the PR head, when it is missing.** The
   `fragility_clear` predicate needs a run record for the PR head. Light and just-do-it
   designs have no implementation audit, and a PR may predate this predicate or have
   been pushed after `two-stable`, so ask first, in the design worktree:
   ```bash
   ROOT="$(git rev-parse --show-toplevel)"
   HEAD_OID="$(gh pr view <pr_url> --json headRefOid --jq .headRefOid)"
   BASE_REF="origin/$(gh pr view <pr_url> --json baseRefName --jq .baseRefName)"
   python3 "$TP_ROOT"/skills/_shared/changed_tests_runs.py read --root "$ROOT" --head "$HEAD_OID" >/dev/null \
     || python3 "$TP_ROOT"/skills/_shared/changed_tests_runs.py record --root "$ROOT" --base "$BASE_REF" --head "$HEAD_OID"
   ```
   `read` exits 1 when no record exists for `HEAD_OID`; only then does `record` run. The
   worktree may be ahead of the PR head: `record` runs the changed tests in its own
   detached worktree at `HEAD_OID`, so the caller's checkout never changes the verdict.
   Do not stop on its exit code (0 pass, 1 fail, 2 unverified or not written): the gate
   below reads the record, and when `record` refused (for example the head is not
   fetched) the predicate reports the missing record with that reason. Skip this step
   when `fragility.merge_predicate` is `false`.

2. **Gate, then land.** **Dispatch-from-seat invocation** (load-bearing for the
   base-sync approval carry — see below), run the land driver:
   ```bash
   SEAT="$(bash "$TP_ROOT"/skills/_shared/seat_resolve.sh --where)"
   if [ -n "$SEAT" ] && [ "$SEAT" != "NONE" ] && [ -f "$SEAT"/skills/_shared/resolve_root.sh ]; then
     TP_SEAT_ROOT="$(bash "$SEAT"/skills/_shared/resolve_root.sh --skill-dir "$SEAT"/skills/tp-merge)"
   else
     TP_SEAT_ROOT="$TP_ROOT"
   fi
   python3 "$TP_SEAT_ROOT"/skills/tp-merge/scripts/land.py --repo "$(git rev-parse --show-toplevel)" <pr_url>
   ```
   **Existence-guarded hop 2**: on a user repo (a plugin install, not the dev repo's
   own seat) the seat (the base checkout) does not contain the framework code
   (`"$SEAT"/skills/_shared/resolve_root.sh` does not exist there — only the dev
   repo is its own seat) — the guard falls back to the naive `$TP_SEAT_ROOT="$TP_ROOT"`
   automatically instead of hop 2 failing loud and leaving the agent to improvise.
   This fallback is the documented-safe path (see the note below): in a plugin
   install, `$TP_ROOT` is the plugin cache — a directory outside any git repo — so
   the independent-oracle guard's DISJOINT-CODE check accepts it as genuinely
   independent, and the base-sync approval carry works: an approval survives a
   safe base-sync when `review.approval_survives_safe_base_sync` is true and
   `git fetch origin <base>` succeeds. The driver calls
   `require_merge_gate_pass(pr_url, repo_root=<worktree toplevel>)`:
   - **On PASS** — it runs `gh pr merge <pr_url> --merge` exactly once and exits **0**.
   - **On `MergeGateBlocked`** (any non-PASS verdict) — it **REFUSES**: it does **NOT**
     run `gh pr merge`, prints the blocking predicate(s), and exits **2**.

   **Why the two-hop `$TP_SEAT_ROOT` resolution, not `$TP_ROOT` directly**: this skill
   runs with cwd inside the design worktree, and the step-0 bootstrap's `$TP_ROOT`
   resolves relative to whatever checkout loaded the code — naively, that is the
   worktree under verification, not the seat. The `human_approved` predicate's
   base-sync-carry (approval-survives-safe-base-sync) is gated by an
   independent-oracle guard (`base_sync_cert.oracle_independent`) that is
   DISJOINT-CODE-gated: it checks where the *executing* gate code physically lives,
   and a worktree-resolved `$TP_ROOT`/`$TP_SEAT_ROOT` is **detected and refused** by
   that guard, not silently trusted. `seat_resolve.sh --where` (repo-global via `git
   worktree list --porcelain`, prints the seat path or `NONE`) plus `resolve_root.sh
   --skill-dir "$SEAT"/skills/tp-merge` (probe-2 grandparent, anchored at the SEAT's
   own skill directory — **not** the worktree's, and **not** probe-4's cwd-derived
   dev-checkout fallback) is the concrete, non-circular recipe that resolves the
   seat's code root from the worktree cwd. This two-hop dance matters in the
   **dev repo's own worktree**: skipping this note there and running the naive
   `$TP_ROOT` invocation does not produce an unsound certificate — the guard fails
   CLOSED — but it silently loses the carry capability, because a worktree-resolved
   root is still inside a git repo: an otherwise-valid base-sync-carried approval
   reports INDETERMINATE instead of PASS. In a **plugin install** (a user repo
   running the shipped plugin, not the dev repo's worktree), `$TP_ROOT` already
   IS the plugin cache — a directory outside any git repo — so the guard accepts
   it directly and the carry works when `review.approval_survives_safe_base_sync`
   is true and `git fetch origin <base>` succeeds, without needing the two-hop
   resolution at all. `--repo "$(git rev-parse --show-toplevel)"` supplies the
   SUBJECT repo (the worktree) explicitly, independent of which checkout's code
   is executing.

3. **On refusal, remediate and re-run.** The refusal prints which predicate(s) blocked.
   When `human_approved` is the blocker, follow `skills/_shared/human-approval-howto.md`:
   a human submits a current APPROVED PR review on the head out-of-band, then re-run
   `/tp-merge`. (A re-push makes a prior review non-current — re-approve on the new head.)
   When the blocker is a base-moved conflict (`mergeable`), run `/tp-merge-from-main` to
   sync the base in first, then re-run `/tp-merge`.
   When the blocker is `fragility_clear`, fix the fragile test the detail names (the
   ordered fixes in `skills/_shared/test-fragility.md`), or waive an open item by id with
   `fragility_items.py waive` (see the predicate above), then re-run `/tp-merge`.

## Rules

- **Refuse on a blocked gate — never cross the irreversible boundary without PASS.**
  `gh pr merge` is reached ONLY after `require_merge_gate_pass` returns; a `MergeGateBlocked`
  exit is **2** with the blockers printed and `gh pr merge` NOT invoked. This is the code
  enforcement of the human-approval guarantee; it is not advisory.
- **Human approval is the human's, submitted out-of-band.** The framework never submits
  an APPROVED review for itself (the autonomous path cannot satisfy `human_approved`).
  See `skills/_shared/human-approval-howto.md`.
- **`/tp-merge` does not sync or rewrite files.** Base-sync / living-doc conflict
  resolution is `/tp-merge-from-main`. This skill only gates and lands.
- **Honest GitHub-UI bypass note**: a merge clicked in the GitHub UI outside the tooling
  **bypasses** this gate. The branch-protection required-check backstop is deferred to the
  `self-hosted-ci-runner` design. Until that ships, the tooling-path land gate is the only
  enforcement — land via `/tp-merge`, not the GitHub UI, on guarded branches. The gate's
  on-head currency re-check still treats a stale/absent approval as unauthorized regardless
  of how the head advanced, so the approve-then-push bypass is closed even on a UI push.
- **Never bypass hooks**: if a `git`/`gh` step is blocked, surface the output and stop —
  do not retry with `--no-verify`.

## Serial landings and the depth-1 revert window

Landings are **serial** — one at a time. This is the current practice, documented here as load-bearing: serial landings are what makes the depth-1 revert window reliable.

**Why it matters**: only the newest landing reverts clean. Probe data: 1/12 landings in a representative sample were revertible at depth > 0; clean reverts are depth-1 only. Each `/tp-merge` therefore opens a brief window where a clean `/tp-revert` is available — and closes it at the next merge.

**The budget**: run `/tp-post-merge` after each `/tp-merge`, **before the next merge gesture**. The inter-merge gap IS the tripwire latency budget — it is event-denominated, not minutes. How long that gap is depends entirely on operator pacing; `/tp-post-merge` runs the T1/T2/T3 tripwires and fires the advisory banner if any wire triggers.
