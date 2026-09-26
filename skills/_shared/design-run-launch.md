# Design-run launch rule

A **design run** (`/tp-run-full-design <slug> …`) is always its own top-level Claude Code
session in its own tmux window — visible to the operator, attachable, resumable, and on its own
budget. The **seat** (the operator's orchestration session, `/tp-promote`, a fleet batch)
*launches* design runs; it never *hosts* one.

## The rule

- **Never** invoke `/tp-run-full-design` via the Agent tool or the Skill tool from inside
  another session's work (a promote, a fleet seat, a subagent, any other skill). Chaining into
  the run in-context hides it from the operator and spends the parent's budget.
- Launch it through the one sanctioned launcher:

  ```bash
  python3 "$TP_ROOT"/skills/_shared/launch_design_run.py <slug> [--mode M] [--skip-design] [--local] [--dry-run]
  ```

  It resolves the `tp/<slug>` worktree, pre-trusts it in the active profile's `.claude.json`,
  pins `CLAUDE_CONFIG_DIR` from the launching session (unset → default profile, with a
  warning), and opens a detached tmux window named `<slug>` running
  `TP_DESIGN_RUN=1 [CLAUDE_CONFIG_DIR=…] claude --model opus '/tp-run-full-design <slug> …'`.
  It prints the window target plus a `tmux link-window -s <target>` hint.
- **Fail visibly, never in-context.** Exit 2 means the launcher could not open a window
  (tmux missing, not inside tmux, no worktree, disallowed model). It prints the manual command
  when it can build one — relay that verbatim to the operator and stop. Do not fall back to
  running the design run in the current session.
- Fleet launch scripts build the same marker/profile/trust shape from the same
  builder (`skills/_shared/design_run_command.py`), so the two paths cannot drift.
- Never pass `--model fable`; the default is `--model opus`.

## Backstop inside the design run (Tier 0)

`/tp-run-full-design` checks for the marker before pickup:

| Condition | Action |
|---|---|
| `TP_DESIGN_RUN` is set in the environment | Proceed. |
| Marker absent **and** this session was started by a parent agent's task prompt (a subagent dispatch, not the operator) | **Refuse** before pickup; print the launcher call above for the parent to run instead. |
| Marker absent and the operator typed the command in a top-level session, or unsure | **Warn once** (suggest the launcher next time) and continue. |

Check the marker with `printenv TP_DESIGN_RUN`. The self-check has no harness signal to lean
on; it is an honest self-assessment of how this session was started.
