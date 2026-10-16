---
name: project-scope
description: "Shared instruction snippet referenced by every council agent and worker (not a standalone deployable agent): the read-only project-scope security constraint, verified before release by the plugin's own CI (framework-check.sh, dev-repo only); in your repo it is instruction-level."
---

# Agent Project Scope

Only access files within the current project directory. Do not read files outside the project root — this includes home directory dotfiles (`~/.ssh/`, `~/.aws/`, `~/.config/`), system files (`/etc/`), and other repositories.

**Why**: Council agents have read-only tool access (`Read`, `Grep`, `Glob`). Without this constraint, an agent could read sensitive files outside the project during analysis. This is an instruction-level control — Claude Code does not support path-scoped tool restrictions at the plugin level. It is verified before release by the plugin's own CI (`framework-check.sh`, dev-repo only); in your repo it is instruction-level, and provides defense-in-depth.

## No kill by name

Never kill processes by name or pattern (`pkill`, `killall`, `kill $(pgrep …)`, `pgrep … | xargs kill`); stop only PIDs your own code started (record `Popen` PIDs, start them with `start_new_session=True`, and kill those). A fake process in a test gets a unique name, never a real program's. On 2026-10-07 a test's `pkill -x claude` killed every Claude Code session on the machine. The `kill-guard` PreToolUse hook enforces this at runtime.
