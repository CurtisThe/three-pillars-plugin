"""launch_design_run.py — open a design run in its own tmux session (linked into the launching one).

The one sanctioned way to start `/tp-run-full-design` from another session
(design-run-launch.md): resolves the `tp/<slug>` worktree, pre-trusts it, and
opens a detached session named `<slug>` (first window; resumed in place if it
exists, linked into the launching session) via
`design_run_command.window_command`. A live run is refused first; then the
committed `seat-brief.md` is written (design_run_brief), then design_run_delivery
prints the brief's source + blob id and the run's routing line (design_run_routing)
and types the first message into its input box (design_run_send), with the manual
command printed if that fails.
With no `--model` it reads the seat's `models.design_run`; a fable launch warns
and logs once. Without tmux (or on --dry-run) it prints the manual command.
Precedence (design_run_launch_plan): this launch's flags, then the explicit run role
(`CLAUDE_LAUNCHER_ROLE=run`, direct + Remote Control; `seat` on a launcher without it,
said in one line), then routes.conf (the worktree's own profile, pretrusted), and
never the seat's own launcher env: every launcher name is unset in the run's window.

Usage:
    python3 launch_design_run.py <slug> [--mode M] [--skip-design]
                                 [--direct] (--direct: start the run with the
                                 Homelab launcher's run role — direct backend +
                                 Remote Control, the S4 proof gate for every
                                 design run; else design_run_backend in the repo
                                 config, else route)
                                 [--model M] [--local | --no-local] [--local-mode M]
                                 [--cheap-tier[=ab] | --no-cheap-tier]  (deprecated no-ops)
                                 [--brief FILE] [--wait SECONDS] [--dry-run]
                                 (--model wins; else models.design_run; else
                                 model_policy.DEFAULTS["design_run"]; no
                                 --local/--no-local: an operator-set TP_LOCAL=on
                                 (one in CLAUDE_LAUNCHER_OWNED is ignored), else
                                 local_implement.default_run_flag;
                                 --cheap-tier is never forwarded)

Exit codes: 0 launched (or dry-run printed), 2 refused (manual command printed
when one could be built).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base_sync_window  # noqa: E402
import design_run_command as drc  # noqa: E402
import model_policy  # noqa: E402
import fable_notice  # noqa: E402  (the design-run fable warning + log entry)
import repo_config_load as rcl  # noqa: E402
import cheap_tier_default  # noqa: E402
import cheap_deprecation  # noqa: E402
import local_implement_config as lic  # noqa: E402
import design_run_tmux  # noqa: E402
import design_run_brief  # noqa: E402
import design_run_routing  # noqa: E402,F401  (the report's modules, kept as patch points)
import design_run_send  # noqa: E402,F401
import design_run_delivery  # noqa: E402  (the launch report: brief, routing, first message)
import design_run_backend  # noqa: E402  (the run's backend; its drop warning)
import design_run_launch_plan  # noqa: E402  (the run role, the env scrub, the route profile)
import design_run_mcp as drm  # noqa: E402  (the MCP allow-list argv + readout)
import design_run_window_env as dwe  # noqa: E402  (LOCAL_MODES for --local-mode)


def find_worktree(porcelain: str, slug: str) -> Optional[str]:
    """Return the worktree path checked out on `refs/heads/tp/<slug>`, else None."""
    want = f"refs/heads/tp/{slug}"
    path = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and line[len("branch "):] == want:
            return path
    return None


def _repo_root(cwd: Optional[str]) -> str:
    """The seat repo root: `git rev-parse --show-toplevel`, else `cwd`/getcwd."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    return cwd or os.getcwd()


def _raw_config(root: str) -> dict:
    """The unpruned `.three-pillars/config.json` (else `{}`), for deprecation notes."""
    try:
        with open(os.path.join(root, ".three-pillars", "config.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def claude_help(env: Mapping[str, str]) -> str:
    """`claude --help` text for the MCP flag probe; any failure -> "" (fail-open)."""
    try:
        path = shutil.which("claude", path=env.get("PATH"))
        if not path:
            return ""
        out = subprocess.run([path, "--help"], capture_output=True, text=True,
                             encoding="utf-8", timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _manual(cmd: str, reason: str) -> int:
    print(f"{reason} Run this in a new terminal / tmux window:")
    print(cmd)
    return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser. Extracted so launch_model_registry.py can drive
    the `--model` default through the same parser `main` uses, without
    forking a subprocess or re-declaring the argument list."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug")
    ap.add_argument("--mode", default=None)
    ap.add_argument("--skip-design", action="store_true")
    ap.add_argument("--model", default=None)
    local = ap.add_mutually_exclusive_group()
    local.add_argument("--local", action="store_true", help="forward --local to the run (wins over TP_LOCAL)")
    local.add_argument("--no-local", action="store_true",
                       help="skip TP_LOCAL / the repo default for this launch")
    ap.add_argument("--local-mode", default=None, choices=dwe.LOCAL_MODES,
                    help="export TP_LOCAL_MODE=M into the run's window (e.g. wait)")
    cheap = ap.add_mutually_exclusive_group()
    cheap.add_argument("--cheap-tier", nargs="?", const="on", default=None,
                       choices=drc.CHEAP_TIER_MODES,
                       help="deprecated no-op (the cheap tier is always on)")
    cheap.add_argument("--no-cheap-tier", action="store_true",
                       help="deprecated no-op (the cheap tier is always on)")
    ap.add_argument("--brief", default=None, metavar="FILE",
                    help="seat brief to commit as seat-brief.md (else the design-dir file, "
                         "the repo's .three-pillars/seat-brief.md, or the shipped template)")
    ap.add_argument("--wait", type=float, default=90.0, metavar="SECONDS",
                    help="wait this long for the run's claude to report its routing and take "
                         "the first message (0 = skip both and print the send command)")
    ap.add_argument("--direct", action="store_true",
                    help="start the run with the launcher's run role (direct backend + Remote "
                         "Control) — the proof gate every design run crosses before "
                         'design_run_backend: "direct" is the repo default')
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base-sync", action="store_true",
                    help="print the base-sync window command for this slug (a Strata session "
                         "under --local, else a sonnet session) instead of starting a design run")
    return ap


default_cheap_tier = cheap_tier_default.default_mode
cheap_tier_warning = cheap_tier_default.is_drop_warning


def resolve_model(cli_model: Optional[str], cfg) -> tuple:
    """`(model, configured)`: `--model` wins, else the validated
    `models.design_run`, else model_policy's default. `configured` is the
    validated config value (the fable gate's explicit opt-in), else None."""
    configured = model_policy.validate_models(cfg.get("models"))[0].get("design_run")
    return cli_model or model_policy.model_for("design_run", cfg), configured


def _write_brief(args, wt: str, root: str) -> Optional[tuple]:
    """Write and commit the seat brief; `(path, source)`, None when not written (fail-open)."""
    try:
        path, _, source = design_run_brief.write_brief(
            wt, args.slug, args.brief, repo_root=root,
            warn=lambda msg: print(msg, file=sys.stderr))
    except OSError as exc:
        print(f"warning: seat brief not written: {exc}", file=sys.stderr)
        return None
    note = design_run_brief.commit_brief(wt, args.slug, path)
    if note:
        print(note, file=sys.stderr if note.startswith("not committed") else sys.stdout)
    return path, source


def _report(args, runner, brief: Optional[tuple], env: Mapping[str, str]) -> None:
    """After the run opens: the brief, its routing, the first message (design_run_delivery)."""
    design_run_delivery.report(args.slug, runner, args.wait, brief=brief, env=env)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[str] = None,
    help_probe=None,
) -> int:
    env = os.environ if env is None else env
    args = build_parser().parse_args(argv)
    if args.brief and not os.path.isfile(args.brief):
        print(f"error: --brief file not found: {args.brief}", file=sys.stderr)
        return 2

    root = _repo_root(cwd)
    loaded = rcl.load_repo_config(root)
    cfg = loaded.config
    model, configured = resolve_model(args.model, cfg)
    # The cheap tier is always on: the retired switches parse, print one
    # `deprecated:` line each (from the RAW config; the prune may drop them)
    # and forward nothing.
    for note in cheap_deprecation.notes(
            _raw_config(root), cheap_tier=args.cheap_tier, no_cheap_tier=args.no_cheap_tier):
        print(note, file=sys.stderr)
    args.cheap_tier = None
    explicit_local = args.local
    local_note = cheap_tier_default.env_local_note(
        cfg, env, local=args.local, no_local=args.no_local, ignore_launcher_owned=True)
    if local_note:
        print(local_note, file=sys.stderr)
    args.local = cheap_tier_default.resolve_local(
        cfg, local=args.local, no_local=args.no_local, env=env, ignore_launcher_owned=True)
    if args.local and not explicit_local:
        # TP_LOCAL or the repo default turned --local on; validate the RAW block
        # the way Tier 1 does (lic.load reads .three-pillars/config.json directly
        # and raises on a schema violation the pruned `cfg` above already hid).
        source = cheap_tier_default.local_source(env, ignore_launcher_owned=True)  # an owned TP_LOCAL is not the source
        try:
            lic.load(root)
        except ValueError as exc:
            args.local = False
            print(f'warning: {source} "on" not applied: {exc}', file=sys.stderr)
    for warning in loaded.warnings:
        if cheap_tier_default.is_local_drop_warning(warning):
            print(f"warning: {warning}", file=sys.stderr)
        elif design_run_backend.is_backend_drop_warning(warning):
            print(f"warning: {warning} (the run stays on the default route)",
                  file=sys.stderr)
    try:  # validate before any side effect
        drc.window_command(args.slug, ".", mode=args.mode, skip_design=args.skip_design,
                           model=model, configured=configured, local=args.local,
                           cheap_tier=args.cheap_tier)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    model_src = "--model" if args.model else ("models.design_run" if configured else "default")
    print(f"design-run model: {model} ({model_src})")

    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    wt = find_worktree(listing.stdout, args.slug) if listing.returncode == 0 else None
    if not wt:
        print(f"error: no worktree on branch tp/{args.slug}. Create one first: "
              f"git worktree add ../<repo>-wt/{args.slug} tp/{args.slug}", file=sys.stderr)
        return 2

    if args.base_sync:
        # The base-sync window's engine is chosen here, not by seat memory.
        bs_cmd, bs_notes = base_sync_window.window_command(
            args.slug, wt, local=args.local,
            which=lambda name: shutil.which(name, path=env.get("PATH")))
        for note in bs_notes:
            print(note, file=sys.stderr)
        print(bs_cmd)  # last, so callers can take the final line as the command
        return 0
    plan = design_run_launch_plan.build(env, cfg, args.direct, args.local_mode, wt)
    for note in plan.notes:
        print(note, file=sys.stderr)
    help_fn = help_probe or claude_help  # resolved now so a patched module global applies
    mcp_plan = drm.plan(cfg, help_fn(env), drm.read_server_defs(wt, plan.profile_dir))
    for line in mcp_plan.lines:
        print(line)
    cmd = drc.window_command(
        args.slug, wt, mode=args.mode, skip_design=args.skip_design,
        config_dir=plan.command_config_dir, model=model, configured=configured,
        local=args.local, cheap_tier=args.cheap_tier, backend_env=plan.backend_env,
        mcp=mcp_plan.args, extra_env=plan.extra_env, unset=plan.unset,
    )
    fable_notice.fable_notice(
        model, os.path.join(wt, "three-pillars-docs", "tp-designs", args.slug, "decisions.md"),
        write=not args.dry_run, launcher="launch_design_run.py")
    if args.dry_run:
        source, src = design_run_brief.pick_source(wt, args.slug, args.brief, root)
        print(f"seat brief: {source} ({src})")
        print(cmd)  # last, so callers can take the final line as the command
        return 0
    try:  # also helps the manual fallback skip the dialog
        if plan.pretrust:
            drc.pretrust(wt, plan.profile_dir)
    except (OSError, ValueError) as exc:
        print(f"error: could not pre-trust worktree: {exc}", file=sys.stderr)
        return _manual(cmd, "Pre-trusting the worktree failed.")
    tmux = shutil.which("tmux", path=env.get("PATH"))
    probe = design_run_tmux.subprocess_runner(tmux) if tmux else None
    runner = probe if env.get("TMUX") else None
    busy = design_run_tmux.live(args.slug, probe) if probe else ""  # inside tmux or not
    if busy:  # a run is going: attach, never print a second launch command
        print(design_run_tmux.live_message(args.slug, busy), file=sys.stderr)
        return 2
    brief = _write_brief(args, wt, root)
    if runner is None:
        rc = _manual(cmd, "tmux is not available (not inside a tmux session).")
        if brief:
            print(f"then type: {design_run_brief.FIRST_LINE}")
        return rc

    result = design_run_tmux.open(
        args.slug, cmd, link_into=design_run_tmux.current_session(runner, env), runner=runner)
    if result.live:
        print(result.message, file=sys.stderr)
        return 2
    if not result.ok:
        print(result.message, file=sys.stderr)
        return _manual(cmd, "tmux could not open the design-run session.")
    print(result.message)
    print(f"attach to it directly: tmux attach -t {args.slug}")
    _report(args, runner, brief, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
