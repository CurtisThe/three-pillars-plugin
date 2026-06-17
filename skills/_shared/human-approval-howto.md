# How do I authorize this merge? (`tp:human-approved`)

This guide is for the operator. The deterministic merge gate's fifth predicate,
`pred_human_approved`, requires a **current human approval** before the land skill
(`/tp-merge`) will run the irreversible `gh pr merge`. This is the one place where the
autonomous framework hands the decision back to a human: nothing the tooling does can
satisfy this predicate — only a human, acting out-of-band, can.

If `/tp-merge` printed `REFUSED` with `[human_approved] ...` in the blockers, this is how
you authorize the land.

## Two ways to authorize — review (primary) or label (fallback)

`pred_human_approved` is satisfied by **either** of two signals, whichever is present:

1. **A native `APPROVED` PR review (primary, low-friction)** — open the PR, review it, and
   click **Approve**. If your GitHub identity is a non-automation human (distinct from the
   framework's `gh`-auth login) and the review is on the **current head**, the gate passes —
   **no label to type, re-type, or clean up**. GitHub stamps an immutable `commit_id` on the
   review, so currency is exact: a real content change leaves the review pinned to the old
   commit (→ non-current → fail-closed), while a diff-unchanged no-op/rebase push carries the
   approval forward (GitHub re-points `commit_id`). A later **Request changes** by a human
   supersedes an earlier approval and blocks. This needs a reviewer identity distinct from the
   framework's login (the two-account topology); the single-account operator uses the label.
2. **The SHA-tagged label (single-account fallback)** — described below. Use this when you
   review and merge under the *same* GitHub account the framework authenticates as, so a
   native self-review would be rejected as automation.

Both paths reuse the **same** identity rejection (bot/App/self-login/automation), and either
alone is sufficient. The rest of this guide covers the label path.

## The label

The authorization signal is a GitHub label whose name **carries the current head SHA**:

```
tp:human-approved:<sha>        e.g.  tp:human-approved:a1b2c3d4e5f6
```

The `<sha>` tag is a **hex prefix of the PR's current head commit** (at least 7 hex
chars; **12+ recommended** so accidental prefix collisions are astronomically unlikely).
A bare `tp:human-approved` (no tag) is **recognized but never current** — the gate reports
it present-but-stale and asks you to re-apply with the head SHA tag.

This family is **distinct** from the advisory label `tp:ready-for-human-merge` (which the
review loop sets to *flag* a PR as reviewed-stable / ready for your attention). That
advisory label does **not** authorize anything. A tagged `tp:human-approved:<sha>` is the
**authorization**: it tells the gate that a human looked at **this exact head** and
approved landing it.

## Applying it (on the CURRENT head)

The gate binds currency to the **immutable head OID, carried in the label NAME** (GitHub
`labeled` timeline events always carry `commit_id: null`, so the SHA lives in the name you
set). Currency is **SHA-prefix-equality**: the tag must be a hex prefix of the PR's current
head SHA. A tag that prefixes an *earlier* head no longer prefixes the advanced head, so it
is treated as **stale** (and therefore absent) and will NOT satisfy the gate. Because the
binding is the immutable head SHA — not a timestamp — a back-dated commit (forged
`GIT_COMMITTER_DATE`) cannot carry a prior approval onto a new head the human never saw.

First get the current head SHA:

```bash
gh pr view {pr_url} --json headRefOid --jq '.headRefOid'
# -> a1b2c3d4e5f60718...   (take the first 12+ hex chars as your tag)
```

**Apply it as a HUMAN (web UI — recommended on a single-account setup).** In the PR's
**Labels** picker, type the full name `tp:human-approved:<sha12>` and choose
**“Create new label … and apply”** — GitHub creates and applies it in one gesture, and the
`labeled` event's actor is *you* (a human), which the predicate requires. On this repo the
framework's `gh` authenticates as the automation account, so applying via `gh`/REST would
record an **automation** actor and be rejected (see the single-account section below) —
apply from your own human web session.

If your human identity is distinct from the framework's `gh` login, the REST form also works:

```bash
SHA=$(gh pr view {pr_url} --json headRefOid --jq '.headRefOid' | cut -c1-12)
gh api --method POST repos/{owner}/{repo}/issues/{pr_number}/labels \
  -f "labels[]=tp:human-approved:$SHA"
```

Then re-run the land:

```bash
/tp-merge {pr_url}
```

## You must be a human, out-of-band

The predicate rejects any approval applied by **automation**: GitHub Apps / bots
(`github-actions[bot]`, `dependabot[bot]`, the Copilot service logins), any login ending
in `[bot]`, the framework's own resolved self-login (so a framework-applied PAT can never
self-approve), and any login you list under `review.automation_identities` in
`.three-pillars/config.json` (use that to exclude committing CI service accounts —
separation of duties). If the labeling actor is in that set, the approval does **not**
count. You — a human, with your own GitHub identity — must apply the label yourself.

## Single-account operator (your OWN approval is REJECTED when you share the framework's login)

The automation set above **includes the framework's own resolved `gh`-auth self-login**
(so a framework-applied PAT can never self-approve — F2 defense-in-depth). On a
**single-account / single-PAT deployment** — where you, the human operator, and the
framework's automation both authenticate as the **same** GitHub login — this means
**your own `tp:human-approved` is REJECTED**: the labeling actor equals the self-login,
which is in the automation set, so the gate returns **INDETERMINATE** and `/tp-merge`
refuses, even though a real human (you) applied it. This is the common case on this
repo's single-PAT setup, and it is **deliberate** (the gate cannot tell your human action
apart from a framework self-apply when both wear the same login).

**Remedy — pick one:**

1. **Machine-account flip (recommended default for solo operators).** Create a separate
   GitHub account for automation (e.g. `YourNameBot`), add it as a repo collaborator,
   and authenticate `gh` as that account. You then apply `tp:human-approved` as your
   human account (`YourName`) — a login distinct from the automation set — and the gate
   PASSES. This is the **recommended default solo setup** (see CLAUDE.md §Solo operator
   setup for the short version, and the step-by-step below). The trade: on a free-plan
   private repo with no branch protection, a raw GitHub UI merge can still bypass the
   gate (known-issue M18); the flip keeps the strict `/tp-merge` gate path working.
2. **Relax via config.** If a separate identity is impractical, scope the automation set
   explicitly: leave `review.automation_identities` to your committing CI/service accounts
   only, and ensure the framework's `gh`-auth login is one you are willing to treat as a
   human approver. (Note: the self-login is added to the automation set *unconditionally*
   by design, so the robust fix is option 1 — a distinct approver identity. Use this
   relaxation only with a clear understanding that it weakens the self-approve defense.)

If `/tp-merge` reports INDETERMINATE with `[human_approved]` even though you applied the
label, this self-login collision is the most likely cause — switch to a distinct approver
identity (option 1) and re-apply on the current head.

### Machine-account flip walk-through

1. Create a new GitHub account (e.g. `YourNameBot`).
2. Add it as a collaborator on the repo (`Settings → Collaborators → Add people`).
3. Accept the collaborator invite from the new account.
4. Generate a PAT from the new account and configure `gh` to use it:
   ```bash
   gh auth login   # authenticate as YourNameBot
   ```
5. Verify: `gh api user --jq .login` returns the machine account login.
6. Apply `tp:human-approved:<sha>` from your HUMAN account (web UI → Labels picker).
7. Re-run `/tp-merge` — the gate sees the label actor as your human login (distinct from
   the automation self-login) and PASSES.

## Pushing a new commit STRIPS the approval (re-approve the new head)

A push that advances the PR head **invalidates** any prior `tp:human-approved` — it was
approving the OLD head, not the new one. Two mechanisms keep this honest:

1. **Auto-strip (convenience).** The base-sync push step
   (`/tp-merge-from-main` step 7) calls `auto_strip_hook.run(pr_url, new_head_oid)` after
   a push lands, which REST-DELETEs the now-stale `tp:human-approved` so the GitHub UI
   honestly reflects that nothing is authorized on the new head. This is fail-open.
2. **Gate-time currency re-check (correctness).** Independent of any strip, the gate
   re-derives currency on every evaluation by SHA-prefix-equality: a label whose name tag
   no longer prefixes the current head OID is treated as absent — so the approve-then-push
   bypass is closed even if the push happened in the GitHub UI and the strip never fired,
   and even if a commit's committer date was forged.

The practical rule: **approve last, after the final commit.** If you push another commit
(or the review loop does), you must **re-apply** `tp:human-approved` on the new head before
`/tp-merge` will land it.

## What the land skill does with it

`/tp-merge` calls `require_merge_gate_pass(pr_url)`. When a current human approval is
present (and the other four predicates pass), the gate returns PASS and `/tp-merge` runs
`gh pr merge` exactly once. Without a current human approval, `require_merge_gate_pass`
raises `MergeGateBlocked`, `/tp-merge` **refuses** (it does NOT run `gh pr merge`), prints
the blocking predicate, and points you back to this guide.
