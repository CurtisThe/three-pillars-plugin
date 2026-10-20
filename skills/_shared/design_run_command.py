"""design_run_command.py — shared builder for a top-level design-run window.

Single source of truth for the shell command that starts an autonomous
`/tp-run-full-design` run as a fresh top-level `claude` session (never a
subagent). Every launching path builds its command from these helpers so the
marker env var, the profile passthrough, and the model pin cannot drift.

Pure string builders plus one side effect: `pretrust()`, which marks a
worktree as trusted in the profile's `.claude.json` so the new session does
not stop at the trust dialog.

CLI:
    python3 design_run_command.py pretrust <worktree> [--config-dir DIR]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import sys
import tempfile
from typing import Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_policy  # noqa: E402
import design_run_role  # noqa: E402

MARKER = "TP_DESIGN_RUN"
# The session-level effort pin that must not leak into a launched run.
EFFORT_ENV = "CLAUDE_CODE_EFFORT_LEVEL"
# The config-free design-run default; model_policy is the one model source.
DEFAULT_MODEL = model_policy.model_for("design_run", None)
# The design-run effort (model_policy is the one source): a `--effort` flag.
DEFAULT_EFFORT = model_policy.effort_for("design_run")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
# The stages a run can be resumed at; `resume_command` refuses anything else.
RESUME_STAGES = ("plan", "implement", "review")
CHEAP_TIER_MODES = ("on", "ab")  # `--cheap-tier` modes (cheap-tier.md); bare flag = on


def resolve_config_dir(env: Mapping[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (config_dir, warning). Warning is set when CLAUDE_CONFIG_DIR is unset."""
    cfg = env.get("CLAUDE_CONFIG_DIR") or None
    if cfg:
        return cfg, None
    return None, (
        "warning: CLAUDE_CONFIG_DIR is unset; the new session will use the "
        "default profile (~/.claude.json)"
    )


def env_prefix(config_dir: Optional[str], backend_env: str = "", extra_env=(), unset=()) -> str:
    """Env words (trailing space) before `claude`: `env -u CLAUDE_CODE_EFFORT_LEVEL` (a session
    effort pin must not leak; the run's effort is `--effort`), one `-u` per `unset` name, the
    marker, `backend_env` (a seat-role `NAME=value`), the profile dir, then `extra_env` pairs."""
    unsets = "".join(f"-u {shlex.quote(n)} " for n in dict.fromkeys((EFFORT_ENV, *unset)))
    prefix = f"env {unsets}{MARKER}=1 "
    if backend_env:
        prefix += f"{backend_env} "
    if config_dir:
        prefix += f"CLAUDE_CONFIG_DIR={shlex.quote(config_dir)} "
    return prefix + "".join(f"{name}={shlex.quote(value)} " for name, value in extra_env)


def effort_args(effort: str = DEFAULT_EFFORT) -> str:
    """The `--effort <effort>` flag; `ValueError` outside `model_policy.EFFORTS`."""
    if not isinstance(effort, str) or effort not in model_policy.EFFORTS:
        raise ValueError(
            f"invalid effort {effort!r}; allowed: {' '.join(model_policy.EFFORTS)}"
        )
    return f"--effort {effort}"


def _require_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValueError(f"invalid design slug {slug!r}; must match [a-z0-9-]+")
    return slug


def _require_model(model: str, *, configured: Optional[str] = None) -> str:
    """Validate a design-run model; returns it. Refuses an empty/None value and
    `inherit` (case-insensitive). A value containing `fable` is the rare-exception
    model: refused unless the seat's `models.design_run` is exactly this string."""
    msg = f"model {model!r} is not allowed for a design run"
    if not model or model.strip().lower() == "inherit":
        raise ValueError(msg)
    if "fable" in model.lower() and configured != model:
        raise ValueError(msg)
    return model


def slash_command(slug: str, mode: Optional[str] = None, skip_design: bool = False,
                  local: bool = False, cheap_tier: Optional[str] = None) -> str:
    """The `/tp-run-full-design` invocation typed into the new session."""
    parts = ["/tp-run-full-design", _require_slug(slug)]
    if mode:
        parts += ["--mode", mode]
    if skip_design:
        parts.append("--skip-design")
    if local:
        parts.append("--local")
    if cheap_tier is not None:  # after --local; "on" is the bare flag
        if not isinstance(cheap_tier, str) or cheap_tier not in CHEAP_TIER_MODES:
            raise ValueError(f"invalid cheap-tier mode {cheap_tier!r}; allowed: on ab")
        parts.append("--cheap-tier" + ("" if cheap_tier == "on" else f"={cheap_tier}"))
    return " ".join(parts)


def resume_command(argv_tail: str, stage: str) -> str:
    """`/tp-run-full-design <tail> --resume-stage <stage>`, keeping the tail verbatim.

    `argv_tail` is the exact text a run was invoked with after the slash command
    (slug first). Every earlier `--resume-stage X` or `--resume-stage=X` is
    removed with a regex on the raw string — never shlex, which would re-quote
    values like `copilot-pull-request-reviewer[bot]` — then whitespace runs are
    collapsed. `stage` must be in `RESUME_STAGES`; the tail must keep at least
    the slug or `ValueError` is raised.
    """
    if stage not in RESUME_STAGES:
        raise ValueError(
            f"invalid resume stage {stage!r}; allowed: {' '.join(RESUME_STAGES)}"
        )
    rest = re.sub(r"(?:^|\s)--resume-stage(?:=\S+|\s+\S+)", " ", argv_tail)
    rest = " ".join(rest.split())
    if not rest:
        raise ValueError("resume tail is empty after removing --resume-stage")
    return f"/tp-run-full-design {rest} --resume-stage {stage}"


def window_command(
    slug: str,
    worktree: str,
    *,
    mode: Optional[str] = None,
    skip_design: bool = False,
    config_dir: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    configured: Optional[str] = None,
    local: bool = False,
    effort: str = DEFAULT_EFFORT,
    cheap_tier: Optional[str] = None,
    backend_env: str = "",
    mcp: str = "",
    extra_env: Sequence[Tuple[str, str]] = (), unset: Sequence[str] = (),
) -> str:
    """Full shell command for a tmux window (or manual paste). `mcp` (a `design_run_mcp` argv
    fragment, empty = none) goes before `--model`: `--mcp-config` is variadic and would swallow
    a slash prompt after it as a second config file. `extra_env`/`unset`: see `env_prefix`. `--name` = RC label; a role launch (see `design_run_role.remote_control_args`) also carries `--remote-control=<slug>`."""
    model = _require_model(model, configured=configured)
    args = effort_args(effort)
    lead = f"{mcp} " if mcp else ""
    slash = slash_command(slug, mode=mode, skip_design=skip_design, local=local, cheap_tier=cheap_tier)
    return (
        f"cd {shlex.quote(worktree)} && {env_prefix(config_dir, backend_env, extra_env, unset)}"
        f"claude {lead}--model {shlex.quote(model)} {args} --name {shlex.quote(slug)} "
        f"{design_run_role.remote_control_args(slug, backend_env)}{shlex.quote(slash)}; exec bash"
    )


_SID_RE = re.compile(r"^[A-Za-z0-9-]+$")


def resume_window_command(
    slug: str, worktree: str, sid: str, *, config_dir: Optional[str] = None,
    model: str = DEFAULT_MODEL, configured: Optional[str] = None,
    effort: str = DEFAULT_EFFORT, backend_env: str = "", mcp: str = "",
    extra_env: Sequence[Tuple[str, str]] = (), unset: Sequence[str] = (),
) -> str:
    """Like `window_command` but `claude [mcp] --resume <sid> …` with no slash prompt."""
    _require_slug(slug)
    if not isinstance(sid, str) or not _SID_RE.match(sid):
        raise ValueError(f"invalid session id {sid!r}; must match [A-Za-z0-9-]+")
    model = _require_model(model, configured=configured)
    lead = f"{mcp} " if mcp else ""
    return (
        f"cd {shlex.quote(worktree)} && {env_prefix(config_dir, backend_env, extra_env, unset)}"
        f"claude {lead}--resume {sid} --model {shlex.quote(model)} {effort_args(effort)} "
        f"--name {shlex.quote(slug)}; exec bash"
    )


def claude_json_path(config_dir: Optional[str], home: Optional[str] = None) -> str:
    """Profile `.claude.json`: `$CLAUDE_CONFIG_DIR/.claude.json` or `~/.claude.json`."""
    if config_dir:
        return os.path.join(config_dir, ".claude.json")
    return os.path.join(home or os.path.expanduser("~"), ".claude.json")


def pretrust(worktree: str, config_dir: Optional[str]) -> str:
    """Merge `hasTrustDialogAccepted: true` for worktree into the profile file.

    Every other key and project entry is preserved. The write is atomic
    (temp file in the same directory, then os.replace) and serialized by an
    exclusive flock on a `<path>.tp-pretrust.lock` sidecar held across
    load -> merge -> replace, so concurrent calls never lose entries.
    Returns the path.
    """
    path = claude_json_path(config_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tp-pretrust.lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _pretrust_locked(path, os.path.abspath(worktree))


def _pretrust_locked(path: str, wt: str) -> str:
    data: dict = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(wt, {})
    entry["hasTrustDialogAccepted"] = True
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".claude.json.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def pretrust_shell_line(worktree: str, config_dir: Optional[str]) -> str:
    """Shell line that runs this module's `pretrust` subcommand."""
    mod = os.path.abspath(__file__)
    line = f"python3 {shlex.quote(mod)} pretrust {shlex.quote(worktree)}"
    if config_dir:
        line += f" --config-dir {shlex.quote(config_dir)}"
    return line


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pretrust", help="mark a worktree trusted in .claude.json")
    p.add_argument("worktree")
    p.add_argument("--config-dir", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "pretrust":
        print(pretrust(args.worktree, args.config_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
