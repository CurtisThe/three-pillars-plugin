# Design-run launch: window env, backend and teardown

Detail for [`design-run-launch.md`](design-run-launch.md) (`design-run-launch-fixes`, 2026-10-13).
The window env is built by `design_run_window_env.py`; `design_run_command.py` renders it.

## Window env

Precedence for every launch: flags passed on this launch (`--model`, `--local-mode`) > the role (backend and Remote Control only) > `routes.conf` (everything else) > never the parent session's env.

- **`--local-mode {wait,fallback,exclusive}`** exports `TP_LOCAL_MODE=<mode>` into the run's
  window command. `wait` makes a busy Strata wait for the GPU instead of falling back to Sonnet.
  An unknown value is a usage error (exit 2, nothing written); when `--local-mode` is absent
  nothing is added and the tmux-global `TP_LOCAL_MODE` route keeps working.
- **Profile pin.** `CLAUDE_LAUNCHER_FORCE_PROFILE=<name>` (a profile *name*; the launcher builds
  `~/.claude-profiles/<name>`) goes into the window: taken from the launching env, else derived
  from a launcher-owned `CLAUDE_CONFIG_DIR` under `.claude-profiles/<name>`. A config dir outside
  `.claude-profiles/` derives nothing.
- **No launcher-owned leaks.** The command `-u`-unsets every name listed in the seat launcher's
  `CLAUDE_LAUNCHER_OWNED` (`TP_LOCAL`, `CLAUDE_LAUNCHER_BACKEND`, …) so the run's own launcher plans
  its route. Never unset: `PATH`, `HOME`, and any name the command sets (`CLAUDE_LAUNCHER_ROLE`,
  `CLAUDE_CONFIG_DIR`, `CLAUDE_LAUNCHER_FORCE_PROFILE`, `TP_LOCAL_MODE`, `TP_DESIGN_RUN`). A name
  that is not a plain identifier is dropped with one note.

## `--local` and a launcher-owned `TP_LOCAL`

A `TP_LOCAL` the seat's launcher set (listed in `CLAUDE_LAUNCHER_OWNED`) no longer cancels the
repo's `local_implement.default_run_flag`; the launch prints one `note:` line saying it was
ignored. An operator-set `TP_LOCAL` keeps its precedence, and `--local` / `--no-local` still win.

## Backend (`design_run_backend`)

`--direct`, or the repo key `design_run_backend: "direct"`, launches the window direct
(`CLAUDE_LAUNCHER_ROLE=seat` when the launcher is present). The code default stays `"route"` for
consumer repos. This repo sets `"direct"` in `.three-pillars/config.json`: the S4 proof run was
waived by the operator's design ruling of 2026-10-13 (L208).

## Launch report

- `seat brief: <path> (source: …; blob <12hex>)` names the brief that was delivered.
- The `routing:` line reads the deepest `claude` child; a `routing: pending` suffix means that
  child's launcher had not finished setting its route — re-read later.
- Brief delivery is confirmed from the transcript above an empty input box, not from the box alone.

## Teardown (`close <slug> [--worktree PATH]`)

`close` kills the `<slug>` session's windows, then the session. Only when there is NO `<slug>`
session does it scan every session and kill, by window id, windows named `<slug>` or whose pane
path is the worktree (a path-boundary match, so `…/foo-bar` never matches `…/foo`).
`/tp-post-merge` passes `--worktree`.
