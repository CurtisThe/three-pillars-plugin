# Index guard — second clause of assert-before-commit

The branch assertion (`git symbolic-ref --short HEAD`) does not see a stale **index**. After a
fold, an ff-merge, `git stash pop`, or any operation that moves `HEAD` under a populated index,
the index can still hold the pre-move content; committing it silently reverts the move (a review
fix, say) under a message that claims the opposite.

After such an operation, and before staging its own work, the orchestrator runs:

```
python3 "$TP_ROOT"/skills/_shared/index_guard.py check
```

Exit 0: the index equals `HEAD`, go on. Exit 1: stop, show the operator the printed staged diff,
never commit it. Exit 2: a git error.

To discard a dirty index, prove it first:

```
python3 "$TP_ROOT"/skills/_shared/index_guard.py verify-discard --ref <commit> --reset
```

It resets (mixed, working tree untouched) only when the staged content is byte-identical to
`<commit>`; otherwise it touches nothing and shows the difference. Note: a reset leaves the
working tree as it is, so check `git status` afterwards if `HEAD` moved under a checkout.

`cherry-pick --no-commit` and `revert --no-commit` populate the index on purpose and do not move
`HEAD`; run the guard only before staging the orchestrator's own work, never after them.

A skill-level check, not a git hook: a hook cannot tell the orchestrator's own staged work from a
stale index. A caller that sets `diff.ignoreSubmodules=all` hides a submodule-pointer-only
difference from `check`.
