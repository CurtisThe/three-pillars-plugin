# How do I authorize this merge? (human approval)

This guide is for the operator. The deterministic merge gate's fifth predicate,
`pred_human_approved`, requires a **current APPROVED human review** before the land
skill (`/tp-merge`) will run the irreversible `gh pr merge`. This is the one place
where the autonomous framework hands the decision back to a human: nothing the tooling
does can satisfy this predicate — only a human, acting out-of-band, can.

If `/tp-merge` printed `REFUSED` with `[human_approved] ...` in the blockers, this is
how you authorize the land.

## Authorize via a native APPROVED PR review

Open the PR on GitHub, review the changes, and click **Approve**. If your GitHub
identity is a non-automation human (distinct from the framework's `gh`-auth login)
and the review is on the **current head**, the gate passes.

GitHub stamps an immutable server-set `commit_id` on every review at submission time.
Currency is a direct `commit_id == headRefOid` check: a real content change leaves the
review pinned to the old `commit_id` (→ non-current → fail-closed), while a
diff-unchanged no-op/rebase push is carried forward by GitHub re-pointing `commit_id`
to the new head. A later **Request changes** by a human supersedes an earlier approval
and blocks. There is no mutable label to clear — the review path is self-cleaning.

After approving, re-run the land:

```bash
/tp-merge {pr_url}
```

## Does a base-sync cost me a re-approval?

Usually **no**. A base-sync (`/tp-merge-from-main`) merges the base branch *into* your
design branch and pushes — moving the head — so you might expect it to stale your
approval. Whether it actually does depends **entirely on how the living-doc conflicts
resolved**:

- **Fully AUTO-SAFE sync → approval SURVIVES.** If every conflict was a mechanical,
  certified-byte-for-byte class (`design-inventory-row-merge`, `id-renumber-collision`,
  `log-entry-insertion`, `append-only-log` — the AUTO-SAFE boundary in the skill), the
  `approval-survives-safe-base-sync` carry re-derives the certified link from git objects
  and keeps your approval **current**. GitHub re-points the review's `commit_id` across a
  diff-unchanged push, so a clean sync needs **no re-approval**.
- **Any hand-resolved (ALWAYS-HUMAN) hunk → approval STALES.** A conflict you resolve by
  hand (a preamble, a current-focus reprioritization, generic prose) cannot be certified
  mechanical — the hand-edit is a real content change — so the carry correctly declines
  and you must **re-approve** the new head. This is the safety property working, not a bug:
  the gate must never carry an approval across a semantic change.

**Serial fleet PRs sharing a living doc do NOT each re-approve by default.** Verify the
merge-tree **empirically** — run the sync (or `--dry-run`) and read the driver report —
before assuming a re-approval tax. A second serially-landed PR can sync **cleanly** (no
conflict at all) when its merge-base already contains the earlier PR's `## History` /
inventory entry, because the two entries land on different lines and never collide.

## You must be a human, out-of-band

The predicate rejects any approval by **automation**: GitHub Apps / bots
(`github-actions[bot]`, `dependabot[bot]`, the Copilot service logins), any login
ending in `[bot]`, the framework's own resolved self-login (so a framework-applied
PAT can never self-approve), and any login you list under `review.automation_identities`
in `.three-pillars/config.json` (use that to exclude committing CI service accounts —
separation of duties). If the reviewing author is in that set, the approval does **not**
count. You — a human, with your own GitHub identity — must submit the review yourself.

## Single-account operator: you have NO gate

The automation set above **includes the framework's own resolved `gh`-auth self-login**
(so a framework-applied PAT can never self-approve — F2 defense-in-depth). On a
**single-account / single-PAT deployment** — where you, the human operator, and the
framework's automation both authenticate as the **same** GitHub login — the review-path
gate has **no distinct human reviewer**: any review you submit is from the same login
as the automation set, so you have **NO gate**. The gate returns INDETERMINATE and
`/tp-merge` refuses, even though a real human (you) submitted it. This is the common
case on a single-PAT setup, and it is **deliberate** (the gate cannot tell your human
action apart from a framework self-apply when both wear the same login).

**Remedy — pick one:**

1. **Machine-account flip (recommended default for solo operators).** Create a separate
   GitHub account for automation (e.g. `YourNameBot`), add it as a repo collaborator,
   and authenticate `gh` as that account. You then submit your APPROVED review as your
   human account (`YourName`) — a login distinct from the automation set — and the gate
   PASSES. This is the **recommended default solo setup** (see CLAUDE.md §Solo operator
   setup for the short version). The framework implements the flip end-to-end:
   the first-run preflight offers to record the machine account as
   `github.pr_author_account` in `.three-pillars/config.json` (see `first-run.md`
   §GitHub PR-author offer), after which both PR-creation sites author as that
   account via the `skills/_shared/github_pr_author.py` chokepoint (ephemeral
   keyring token — no stored credential) and the bot login joins
   `review.automation_identities` so only your human review satisfies the gate.
   The trade: on a free-plan private repo with no branch
   protection, a raw GitHub UI merge can still bypass the gate (M18 total); the
   two-account flip keeps the strict `/tp-merge` gate path working.
2. **Relax via config.** If a separate identity is impractical, scope the automation set
   explicitly: leave `review.automation_identities` to your committing CI/service accounts
   only, and ensure the framework's `gh`-auth login is one you are willing to treat as a
   human approver. (Note: the self-login is added to the automation set *unconditionally*
   by design, so the robust fix is option 1 — a distinct approver identity.)

If `/tp-merge` reports INDETERMINATE with `[human_approved]` even though you submitted
an APPROVED review, this self-login collision is the most likely cause — switch to a
distinct approver identity (option 1, two-account flip).

### Machine-account flip walk-through

1. Create a new GitHub account (e.g. `YourNameBot`).
2. Add it as a collaborator on the repo (`Settings → Collaborators → Add people`).
3. Accept the collaborator invite from the new account.
4. Generate a PAT from the new account and configure `gh` to use it:
   ```bash
   gh auth login   # authenticate as YourNameBot
   ```
5. Verify: `gh api user --jq .login` returns the machine account login.
6. Submit your APPROVED review from your HUMAN account (GitHub web UI → review the PR
   and click Approve).
7. Re-run `/tp-merge` — the gate sees the review author as your human login (distinct
   from the automation self-login) and PASSES.

## Advisory label: tp:ready-for-human-merge

The advisory label `tp:ready-for-human-merge` (set by the review loop to flag a PR as
reviewed-stable / ready for your attention) **does not authorize anything**. It is a
flag only — it does not satisfy `pred_human_approved`. The authorization is the APPROVED
review from a non-automation human described above.

## What the land skill does with it

`/tp-merge` calls `require_merge_gate_pass(pr_url)`. When a current APPROVED human
review is present (and the other four predicates pass), the gate returns PASS and
`/tp-merge` runs `gh pr merge` exactly once. Without a current human approval,
`require_merge_gate_pass` raises `MergeGateBlocked`, `/tp-merge` **refuses** (it does
NOT run `gh pr merge`), prints the blocking predicate, and points you back to this guide.
