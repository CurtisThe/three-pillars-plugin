"""github_pr_author.py — the single PR-create chokepoint (pr-author-bot-account).

Pure/seamed core + thin CLI. **No `gh auth switch` anywhere** (machine-global
mutation; racy under parallel fleet workers). **No token at rest**: the token
exists only as a local variable passed into one child process env. **Config
source**: `.three-pillars/config.json` under the resolved repo root — an
explicit `--repo` wins outright; otherwise the root is the git toplevel
(`git rev-parse --show-toplevel`), not raw cwd, so a call from a
subdirectory still finds the repo's config instead of misreading a missing
file as "unconfigured" (falls back to cwd only outside a git repo).

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


class BotAuthUnavailable(RuntimeError):
    """Raised when a configured PR-author bot account cannot be honored.

    Covers two distinct triggers, both fail-loud (never a silent ambient
    fallback): (1) the configured account failed its `gh auth token --user`
    probe, and (2) the `github` config block is present but structurally
    unusable (non-dict, malformed account, unknown `used_for`).
    """


def resolve_pr_author(config: dict, context: str) -> "str | None":
    """Resolve which account (if any) should author the PR.

    Pure. Returns `github.pr_author_account` iff it is a non-empty str AND
    (`used_for` == "all-prs" or ("autonomous-only" and context == "autonomous")).
    `used_for` null/absent folds to "all-prs".

    Fail-loud asymmetry: a config with NO `github` key (or
    `pr_author_account: null`) → None (plain path, byte-identical to today).
    A PRESENT-yet-unusable `github` block — non-dict `github`, non-str
    non-null `pr_author_account`, empty-str account, unknown `used_for`
    (only when an account IS configured) — raises `BotAuthUnavailable`.

    `context` not in {"manual", "autonomous"} → ValueError (caller bug).
    """
    if context not in ("manual", "autonomous"):
        raise ValueError(
            f"context must be 'manual' or 'autonomous', got {context!r}"
        )

    cfg = config if isinstance(config, dict) else {}
    if "github" not in cfg:
        return None

    github = cfg["github"]
    if not isinstance(github, dict):
        raise BotAuthUnavailable(
            "`.three-pillars/config.json`'s `github` block is present but is "
            f"not an object (got {type(github).__name__}); cannot determine "
            "the PR-author account. Fix the config or remove the `github` "
            "key to fall back to ambient gh auth."
        )

    account = github.get("pr_author_account")
    if account is None:
        return None

    if not isinstance(account, str) or account == "":
        raise BotAuthUnavailable(
            "`github.pr_author_account` is configured but is not a usable "
            f"login (got {account!r}). Fix `.three-pillars/config.json` or "
            "clear `github.pr_author_account` to disable bot-authored PRs."
        )

    used_for = github.get("used_for")
    if used_for is None:
        used_for = "all-prs"
    if used_for not in ("all-prs", "autonomous-only"):
        raise BotAuthUnavailable(
            f"`github.used_for` is set to an unknown value {used_for!r} for "
            f"configured account {account!r}. Expected 'all-prs' or "
            "'autonomous-only'. Fix `.three-pillars/config.json`."
        )

    if used_for == "all-prs":
        return account
    # used_for == "autonomous-only"
    return account if context == "autonomous" else None


def bot_token(account: str, runner=None) -> str:
    """`gh auth token --user <account>`; non-zero/empty → BotAuthUnavailable.

    Fail loud, never fall back — a silent fallback to ambient auth re-creates
    the self-approval trap the design exists to remove. The probe CAPTURES
    stdout (never inherited) — `gh auth token` prints the credential, and an
    inheriting runner would leak it into the terminal/transcript.
    """
    run = runner or (
        lambda argv: subprocess.run(argv, capture_output=True, text=True)
    )
    result = run(["gh", "auth", "token", "--user", account])
    token = (result.stdout or "").strip() if result.returncode == 0 else ""
    if result.returncode != 0 or not token:
        raise BotAuthUnavailable(
            f"GitHub bot account {account!r} is not available via "
            f"`gh auth token --user {account}` — the account may not be "
            "logged into this machine's gh keyring. Fix by either: "
            f"(1) run `gh auth login` and authenticate as {account}, adding "
            "it to the multi-account keyring (`gh auth token --user` "
            "requires a modern gh, ~2.40+), or "
            "(2) clear `github.pr_author_account` in "
            "`.three-pillars/config.json` to disable bot-authored PRs."
        )
    return token


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

    token = bot_token(account, runner=token_runner)
    child_env = {**base_env, "GH_TOKEN": token}
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


def _load_repo_config(repo: Path) -> dict:
    """CLI-level config load: missing file -> {} (unconfigured, plain path);
    present-but-unparseable JSON -> BotAuthUnavailable (fail loud — a
    configured bot account cannot be ruled out, so this refuses rather than
    silently falling back to ambient gh auth). `repo` is the git toplevel
    when `--repo` is omitted (see `_default_repo_root`), not raw cwd — a
    "missing" config here means genuinely absent, not "wrong directory"."""
    config_path = repo / ".three-pillars" / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise BotAuthUnavailable(
            "`.three-pillars/config.json` exists but could not be parsed "
            f"({exc}); a configured PR-author bot account cannot be ruled "
            "out. Fix or remove the file to proceed."
        ) from exc


def _default_repo_root() -> Path:
    """Resolve the repo root to use when `--repo` is NOT passed explicitly.

    Walks to the git toplevel (`git rev-parse --show-toplevel`) rather than
    trusting cwd — invoked from a subdirectory of a configured repo, a raw
    `Path(".").resolve()` finds no `.three-pillars/config.json`, cannot tell
    "config genuinely absent" from "wrong cwd", and silently resolves
    "unconfigured" (plain ambient `gh pr create`, no bot token, no
    reviewer) — the exact silent-ambient-authorship class this chokepoint
    exists to forbid. Falls back to `Path(".").resolve()` when not inside a
    git repo (`gh pr create` itself requires a git repo, so the fallback
    only affects degenerate/non-git invocations).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=".",
        )
    except OSError:
        return Path(".").resolve()
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path(".").resolve()


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
    parser.add_argument("--repo", default=None)
    args = parser.parse_args(own_args)
    repo = Path(args.repo).resolve() if args.repo is not None else _default_repo_root()

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
