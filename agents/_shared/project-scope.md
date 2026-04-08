# Agent Project Scope

Only access files within the current project directory. Do not read files outside the project root — this includes home directory dotfiles (`~/.ssh/`, `~/.aws/`, `~/.config/`), system files (`/etc/`), and other repositories.

**Why**: Council agents have read-only tool access (`Read`, `Grep`, `Glob`). Without this constraint, an agent could read sensitive files outside the project during analysis. This is an instruction-level control — Claude Code does not support path-scoped tool restrictions at the plugin level — but it is verified by `security-check.sh` and provides defense-in-depth.
