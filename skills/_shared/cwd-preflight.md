# cwd-preflight — worktree cwd contract

Worktree-operating skills must run from **inside** the target `tp/<design>`
worktree, not from the main checkout. If a `tp/<design>` worktree exists and
the skill's cwd is the main checkout (or any path outside the worktree), the
skill should refuse early with a one-line `cd` fix before any stray write occurs.

## When to run this preflight

Any skill that operates inside a worktree (tp-merge-from-main, tp-design-complete,
tp-phase-implement, tp-spike-implement, and the worktree-management skill) must
run this check near the top of its preflight sequence, after the first-run
check and before the collaboration preflight.

## How to run it

```
python3 "$TP_ROOT"/skills/_shared/cwd_preflight.py <design>
```

- **Exit 0** — ok: either the cwd is already inside the `tp/<design>` worktree,
  or no such worktree exists (single-checkout flow, nothing to redirect into).
- **Exit 3** — refuse: the `tp/<design>` worktree exists and cwd is outside it.
  The message names the worktree path and the `cd` fix. Stop the skill and
  show the message to the user.
- **Fail-open**: on any git error or unreadable worktree state, the script exits 0.
  The commit-time guard (the fail-closed worktree write guard) is the backstop;
  this preflight is the ergonomic early-refuse only.

## The problem it solves

Without this check, a skill running in the main checkout can write files into
the main checkout while a tp/<design> worktree is live. Those writes then look
like default-branch commits. The commit-time guard (the fail-closed worktree
write guard) is the hard backstop, but this preflight catches the mistake
earlier and more legibly — before any file is written.

## Fix for the user

```
cd <worktree-path>
# then re-run your command
```

The `cd` path is printed in the exit-3 message.

## Implementation

The helper is at `skills/_shared/cwd_preflight.py`. Its `check_cwd` function
uses path-prefix containment (via `pathlib.Path.relative_to`) to test whether
the cwd is inside the target worktree. The `target_worktree_path` function
parses `git worktree list --porcelain` to find the worktree for `tp/<design>`.

Both functions fail-open (return ok=True on any error) so a git state anomaly
never false-blocks a skill invocation.
