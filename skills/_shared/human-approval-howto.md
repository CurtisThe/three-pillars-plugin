# How do I authorize this merge? (`tp:human-approved`)

This guide is for the operator. The deterministic merge gate's fifth predicate,
`pred_human_approved`, requires a **current human approval** before the land skill
(`/tp-merge`) will run the irreversible `gh pr merge`. This is the one place where the
autonomous framework hands the decision back to a human: nothing the tooling does can
satisfy this predicate — only a human, acting out-of-band, can.

If `/tp-merge` printed `REFUSED` with `[human_approved] ...` in the blockers, this is how
you authorize the land.

## The label

The authorization signal is the exact GitHub label:

```
tp:human-approved
```

It is **distinct** from the advisory label `tp:ready-for-human-merge` (which the
review loop sets to *flag* a PR as reviewed-stable / ready for your attention). That
advisory label does **not** authorize anything. `tp:human-approved` is the
**authorization**: it tells the gate that a human looked at this exact head and approved
landing it.

## Applying it (on the CURRENT head)

The approval must be current on the PR's **current head SHA**. The gate binds currency
to the **immutable head OID**: the `tp:human-approved` label event records (server-side)
the head SHA it was applied against (`commit_id`), and the gate requires that recorded
SHA to **equal the PR's current head SHA**. A label applied against an earlier head — i.e.
before any later commit advanced the head — has a `commit_id` that no longer matches, so
it is treated as **stale** (and therefore absent) and will NOT satisfy the gate. This is
SHA-equality, not a timestamp compare, so a back-dated commit (forged `GIT_COMMITTER_DATE`)
cannot carry a prior approval onto a new head the human never saw.

Apply it via the REST labels endpoint (mirrors how the tooling adds labels), or with `gh`:

```bash
# REST (preferred — matches label_manager._add_label_rest):
gh api --method POST repos/{owner}/{repo}/issues/{pr_number}/labels \
  -f "labels[]=tp:human-approved"

# or the porcelain equivalent:
gh pr edit {pr_url} --add-label "tp:human-approved"
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

1. **Approve from a DISTINCT GitHub identity.** Apply `tp:human-approved` while
   authenticated as a GitHub login that is *not* the framework's `gh`-auth self-login
   (e.g. a personal account separate from the automation PAT). The approver is then a
   human distinct from the automation identity and the gate PASSES.
2. **Relax via config.** If a separate identity is impractical, scope the automation set
   explicitly: leave `review.automation_identities` to your committing CI/service accounts
   only, and ensure the framework's `gh`-auth login is one you are willing to treat as a
   human approver. (Note: the self-login is added to the automation set *unconditionally*
   by design, so the robust fix is option 1 — a distinct approver identity. Use this
   relaxation only with a clear understanding that it weakens the self-approve defense.)

If `/tp-merge` reports INDETERMINATE with `[human_approved]` even though you applied the
label, this self-login collision is the most likely cause — switch to a distinct approver
identity (option 1) and re-apply on the current head.

## Pushing a new commit STRIPS the approval (re-approve the new head)

A push that advances the PR head **invalidates** any prior `tp:human-approved` — it was
approving the OLD head, not the new one. Two mechanisms keep this honest:

1. **Auto-strip (convenience).** The base-sync push step
   (`/tp-merge-from-main` step 7) calls `auto_strip_hook.run(pr_url, new_head_oid)` after
   a push lands, which REST-DELETEs the now-stale `tp:human-approved` so the GitHub UI
   honestly reflects that nothing is authorized on the new head. This is fail-open.
2. **Gate-time currency re-check (correctness).** Independent of any strip, the gate
   re-derives currency on every evaluation by SHA-equality: a label whose recorded
   `commit_id` does not equal the current head OID is treated as absent — so the
   approve-then-push bypass is closed even if the push happened in the GitHub UI and the
   strip never fired, and even if a commit's committer date was forged.

The practical rule: **approve last, after the final commit.** If you push another commit
(or the review loop does), you must **re-apply** `tp:human-approved` on the new head before
`/tp-merge` will land it.

## What the land skill does with it

`/tp-merge` calls `require_merge_gate_pass(pr_url)`. When a current human approval is
present (and the other four predicates pass), the gate returns PASS and `/tp-merge` runs
`gh pr merge` exactly once. Without a current human approval, `require_merge_gate_pass`
raises `MergeGateBlocked`, `/tp-merge` **refuses** (it does NOT run `gh pr merge`), prints
the blocking predicate, and points you back to this guide.
