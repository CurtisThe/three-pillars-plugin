# Branch Protection

When a three-pillars repo has a GitHub `origin`, the first-run preflight offers to apply a branch-protection rule to the default branch so accidental self-merges or force-pushes can't land. The rule is applied via `gh api`, the user can opt out (recorded once, never re-asked), and the entire path is **fail-open**: if anything goes wrong, we record the manual command for the user to run later and continue.

This file is the protocol that [`first-run.md`](first-run.md) delegates to when its `## Branch-protection detection` section fires.

## When this runs

Driven by `first-run.md`. The cheap-path checks in the preflight skip this section entirely once `branch_protection.applied_at` is non-null OR `branch_protection.declined` is true. The first invocation in a repo with `origin` configured (and no prior decision recorded) goes through every step below.

## Resolving owner/repo and default branch

1. `gh repo view --json nameWithOwner,defaultBranchRef -q '.nameWithOwner + " " + .defaultBranchRef.name'` — single call, two fields. Returns e.g. `Acme/widget main`.
2. If `gh` is not installed or returns non-zero, fall back to parsing `git remote get-url origin`:
   - `git@github.com:Acme/widget.git` → owner `Acme`, repo `widget`.
   - `https://github.com/Acme/widget.git` → owner `Acme`, repo `widget`.
   - For the default branch, the fallback uses `git symbolic-ref refs/remotes/origin/HEAD` (`refs/remotes/origin/main` → `main`). If that ref is unset, prompt the user for the branch name (default `main`).
3. If both `gh` and the URL fallback fail, treat this as a `gh missing` failure — see `## Manual instructions` below.

## Prompt

Once owner/repo/branch are resolved, ask the user once:

> Apply GitHub branch protection to `{owner}/{repo}` on `{branch}`? This requires 1 approving review on PRs, blocks force-pushes, and blocks deletions. **It blocks self-merge** — solo users will need a teammate to approve or `gh pr merge --admin` to bypass. (yes / no / skip)

- **yes** — run the `gh api` command below. On success: record `applied_at`, `profile`. On failure: record fail-open (declined=false, applied_at=null) and print the manual command.
- **no** — record `declined: true`. Permanently silences future prompts in this repo.
- **skip** — leave config unchanged. The prompt re-fires on the next invocation.

The "blocks self-merge" warning is the most important part of the prompt copy. Solo users routinely turn this on, hit the self-merge block on their first PR, and then have to figure out `--admin` under stress. Surfacing it up-front prevents that.

## The gh api call (profile: `team-pr-1approval-noforce`)

Endpoint: `gh api -X PUT repos/{owner}/{repo}/branches/{branch}/protection` (PUT replaces the entire protection rule — partial updates require multiple calls).

```bash
gh api -X PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/{owner}/{repo}/branches/{branch}/protection" \
  -F "required_status_checks=null" \
  -F "enforce_admins=null" \
  -F "required_pull_request_reviews[required_approving_review_count]=1" \
  -F "required_pull_request_reviews[dismiss_stale_reviews]=true" \
  -F "restrictions=null" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false" \
  -F "required_linear_history=false" \
  -F "required_conversation_resolution=false"
```

The fields in plain English:

| Field | Why |
|---|---|
| `required_approving_review_count: 1` | Forces every PR through at least one human review. Catches the "I'll just merge my own branch" pattern that surfaces in solo flows and tiny teams. |
| `dismiss_stale_reviews: true` | Approvals dropped when new commits land — prevents a stale rubber-stamp from carrying through unreviewed changes. |
| `allow_force_pushes: false` | Force-push to the default branch is one of the rare destructive git operations. Disabling it is cheap insurance; legitimate history rewrites should happen on a feature branch. |
| `allow_deletions: false` | Symmetric — deleting the default branch should never be a one-keystroke mistake. |
| `enforce_admins: null` | Admins keep the override. Used together with `gh pr merge --admin` as the documented self-merge escape hatch. Flipping to `true` would lock the maintainer out of their own emergency lever, which is the wrong trade for a framework that runs in solo and tiny-team contexts. |
| `restrictions: null` | No user/team allow-list; any reviewer in the repo's permission model can approve. Repos with strict review ownership policies should layer CODEOWNERS instead — out of scope for this protocol. |
| `required_status_checks: null` | This protocol doesn't assume a CI provider exists. Projects that wire up CI can layer required checks on top later; the framework refuses to invent green-check requirements that don't exist yet. |

This payload is the profile `team-pr-1approval-noforce` recorded in `config.branch_protection.profile`. It is the only profile shipped today. Future profiles (e.g. `solo-noforce-only`) can be added without breaking config forward-compat — the schema's enum widens.

## Manual instructions (when gh is missing or unauthorized)

If the `gh api` call fails for any reason — `gh` not installed, not authenticated, returned 403 (insufficient scopes), network failure, repo doesn't exist — **do not block the calling skill**. Record fail-open and print the manual command for the user to run later.

The fail-open record:
- `config.branch_protection.declined`: `false` (the user said yes — the system, not the user, failed)
- `config.branch_protection.applied_at`: `null` (not applied)
- `config.branch_protection.offered_at`: current ISO 8601 UTC timestamp (so the prompt doesn't re-fire on every invocation)

The stdout copy printed to the user (substitute `{owner}/{repo}/{branch}` with the resolved values):

```
Branch protection could not be applied automatically. You can apply it later by running:

  gh auth login                                # if not yet authenticated
  gh api -X PUT \
    -H "Accept: application/vnd.github+json" \
    "repos/{owner}/{repo}/branches/{branch}/protection" \
    -F "required_status_checks=null" \
    -F "enforce_admins=null" \
    -F "required_pull_request_reviews[required_approving_review_count]=1" \
    -F "required_pull_request_reviews[dismiss_stale_reviews]=true" \
    -F "restrictions=null" \
    -F "allow_force_pushes=false" \
    -F "allow_deletions=false" \
    -F "required_linear_history=false" \
    -F "required_conversation_resolution=false"

After running, re-invoke any tp-* skill — first-run will detect the rule and stamp config.branch_protection.applied_at.
```

The framework intentionally does not retry, does not poll, and does not nag. The user has the literal command in their terminal scrollback; the next tp-* invocation will pick up the new state.

## No-origin silent skip

If `git remote get-url origin` returns non-zero, this entire section is skipped silently:

- **No prompt** fires.
- **Nothing is written** to `config.branch_protection`.
- The next invocation re-checks `origin` from scratch — adding a remote later naturally re-triggers the prompt.

This matters for local-only repos, repos using a non-GitHub remote (GitLab, Gitea, plain ssh), and offline development. Asking the user about GitHub branch protection on a Gitea repo would be noise; the silence is the correct UX.

The `--auto` deferral in `first-run.md` covers the orthogonal case where origin exists but we cannot prompt. In that mode the helper logs a `[first-run]` decisions.md entry rather than emitting prompt text.
