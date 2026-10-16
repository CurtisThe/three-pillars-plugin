"""github_pr_author.py — the single PR-create chokepoint (pr-author-bot-account).

Pure/seamed core + thin CLI. The token rules (no `gh auth switch`, no token at rest, one
implementation of the per-call token fetch, fail-loud `BotAuthUnavailable`) live in
`automation_identity.py`, the identity core shared with every other automation write; the moved
names are re-exported here so callers and tests keep using `github_pr_author.*`. **Config
source**: `.three-pillars/config.json` under the resolved repo root — an explicit `--repo` (a
LOCAL repo path, validated to be an existing directory; never a GitHub `owner/name` slug) wins
outright; otherwise the root is the git toplevel (`_default_repo_root`), not raw cwd, so a call
from a subdirectory still finds the repo's config (cwd only outside a git repo).

See `three-pillars-docs/completed-tp-designs/pr-author-bot-account/detailed-design.md`
§3 for the full interface specification.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import automation_identity  # noqa: E402
from automation_identity import (  # noqa: E402,F401  (re-exported public names)
    BotAuthUnavailable,
    _default_repo_root,
    bot_token,
    resolve_pr_author,
)

_load_repo_config = automation_identity.load_repo_config


def _default_create_runner(argv, **kwargs):
    return subprocess.run(argv, **kwargs)


def _reviewer_args(config: dict, gh_args: list) -> list:
    """Append `--reviewer <comma-joined>` iff `github.review_requests` is a
    non-empty list AND `--reviewer` is not already present in `gh_args`."""
    if "--reviewer" in gh_args:
        return list(gh_args)
    if not isinstance(config, dict):
        return list(gh_args)
    github = config.get("github")
    if not isinstance(github, dict):
        return list(gh_args)
    review_requests = github.get("review_requests")
    if not isinstance(review_requests, list) or not review_requests:
        return list(gh_args)
    filtered = [r for r in review_requests if isinstance(r, str) and r]
    if not filtered:
        return list(gh_args)
    return [*gh_args, "--reviewer", ",".join(filtered)]


def create_pr(
    gh_args: list,
    config: dict,
    context: str,
    runner=None,
    env=None,
    token_runner=None,
) -> int:
    """Resolve the PR author and run `gh pr create`.

    None → plain `gh pr create <gh_args>` (ambient auth, byte-identical to
    today). An account → bot-authored: child env =
    `{**(env or os.environ), "GH_TOKEN": token}`, os.environ itself is NEVER
    mutated. When bot-authoring and `github.review_requests` is a non-empty
    list AND no `--reviewer` already in `gh_args`, appends
    `--reviewer <comma-joined>`. Returns the child's returncode; stdout/stderr
    pass through (never capture_output on this call — the PR URL must reach
    the caller). On a token-probe failure, `BotAuthUnavailable` propagates
    and the create runner is NEVER invoked (no ambient fallback).
    """
    run = runner or _default_create_runner
    base_env = env if env is not None else os.environ

    account = resolve_pr_author(config, context)

    if account is None:
        result = run(["gh", "pr", "create", *gh_args], env=base_env)
        return result.returncode

    child_env = automation_identity.account_env(account, base_env, token_runner=token_runner)
    args = _reviewer_args(config, gh_args)
    result = run(["gh", "pr", "create", *args], env=child_env)
    return result.returncode


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".config.", suffix=".tmp", delete=False
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def _split_passthrough(raw_argv: list) -> "tuple[list, list]":
    """Split argv on a literal '--' separator. Everything after it is
    pass-through `gh pr create` args — never re-parsed or re-quoted here."""
    if "--" in raw_argv:
        idx = raw_argv.index("--")
        return raw_argv[:idx], raw_argv[idx + 1 :]
    return raw_argv, []


def _cli_verify(repo: Path) -> int:
    config_path = repo / ".three-pillars" / "config.json"
    if not config_path.exists():
        print("no .three-pillars/config.json found", file=sys.stderr)
        return 1
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        print("cannot parse .three-pillars/config.json", file=sys.stderr)
        return 1
    github = cfg.get("github")
    account = github.get("pr_author_account") if isinstance(github, dict) else None
    if not account:
        print("no github.pr_author_account configured", file=sys.stderr)
        return 1
    try:
        bot_token(account)  # probe only; the token itself is never printed/stored
    except BotAuthUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    github["verified_at"] = _now_iso_utc()
    _atomic_write_json(config_path, cfg)
    return 0


def main(argv=None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    own_args, gh_args = _split_passthrough(raw_argv)

    parser = argparse.ArgumentParser(
        description="github_pr_author.py — the single PR-create chokepoint."
    )
    parser.add_argument("command", choices=["create", "resolve", "verify"])
    parser.add_argument("--context", choices=["manual", "autonomous"], default=None)
    parser.add_argument(
        "--repo",
        default=None,
        help="LOCAL repository path holding .three-pillars/config.json "
        "(not a GitHub owner/name; pass that to gh after `--` as `-R owner/name`)",
    )
    args = parser.parse_args(own_args)
    if args.repo is not None:
        repo = Path(args.repo).resolve()
        if not repo.is_dir():
            print(
                f"--repo must be a local repository path (an existing directory), "
                f"not a GitHub owner/name: {args.repo!r} is not a directory. "
                "To target a GitHub repo, pass it to gh after `--` as `-R owner/name`.",
                file=sys.stderr,
            )
            return 2
    else:
        repo = _default_repo_root()

    if args.command in ("create", "resolve") and args.context is None:
        print(f"--context is required for {args.command!r}", file=sys.stderr)
        return 2

    if args.command == "resolve":
        try:
            cfg = _load_repo_config(repo)
            account = resolve_pr_author(cfg, args.context)
        except BotAuthUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3
        if account:
            print(account)
        return 0

    if args.command == "create":
        try:
            cfg = _load_repo_config(repo)
            return create_pr(gh_args, cfg, args.context)
        except BotAuthUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3

    return _cli_verify(repo)


if __name__ == "__main__":
    sys.exit(main())
