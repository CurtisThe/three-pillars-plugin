"""github_auth_check.py — first-run preflight helper for the GitHub PR-author offer.

Mirrors `branch_protection_check.py` exactly (dataclass `CheckResult`, atomic
tmp-file-and-rename config write, `--auto` decisions-append). Handles the
programmable branches of the `## GitHub PR-author offer` flow in
`first-run.md`:

- **no-origin silent skip**: `git remote get-url origin` fails → no prompt,
  no config write. Re-checks on the next invocation.
- **already-decided skip**: `github.pr_author_account` is set OR
  `github.declined` is true — the operator has already answered.
- **gh-missing skip**: `gh` not on PATH — the offer is moot (no `gh`, no PR
  creation at all). Silent, no write, re-checks next run.
- **--auto skip + log**: autonomous mode → append a `[first-run]` entry to
  `decisions.md` per `auto-mode.md`, leave config untouched.

The interactive happy-path (prompt account/no/skip, run `verify_account`,
`mark_configured`/`mark_declined`) is the agent's responsibility per
`first-run.md`'s `## GitHub PR-author offer` section, not this module's.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class CheckResult:
    """What the helper decided to do.

    `action`: one of "skip-no-origin", "skip-decided", "skip-gh-missing",
              "auto-skip", "needs-prompt".
    `reason`: short human string for logs / handoffs.
    `config_updated`: True iff `.three-pillars/config.json` was written.
    """

    action: str
    reason: str
    config_updated: bool


def _has_origin(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_config(repo: Path) -> dict:
    config_path = repo / ".three-pillars" / "config.json"
    if not config_path.exists():
        return {"schema_version": 1}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {"schema_version": 1}


def _already_decided(config: dict) -> bool:
    github = config.get("github")
    if not isinstance(github, dict):
        return False
    if github.get("pr_author_account"):
        return True
    if github.get("declined") is True:
        return True
    return False


def _atomic_write_config(config_path: Path, data: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=config_path.parent,
        prefix=".config.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, config_path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def _append_auto_decision(decisions_path: Path) -> None:
    """Append a `[first-run]` entry per auto-mode.md."""
    if not decisions_path.exists():
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        decisions_path.write_text(
            "# Autonomous Run — Decision Log\n\n"
            "## Run Metadata\n"
            f"**Started**: {_now_iso_utc()}\n\n"
        )
    entry = (
        "### [first-run] GitHub PR-author\n"
        "**Question**: Open design PRs as a secondary bot account so your "
        "main account can approve them?\n"
        "**Decided**: Skip — no interactive prompt available in --auto.\n"
        "**Reasoning**: The bot-account topology is a one-time UX decision "
        "with security implications; deferring lets the next interactive "
        "run surface the trade-off to the user.\n"
        "**Confidence**: Medium\n\n"
    )
    with decisions_path.open("a") as f:
        f.write(entry)


def verify_account(login: str, runner=None) -> bool:
    """Probe `gh auth token --user <login>` (never prints/stores the token;
    checks returncode only). `runner` seam: callable `(argv) -> CompletedProcess`,
    defaulting to `subprocess.run` with captured stdout (never inherited)."""
    run = runner or (
        lambda argv: subprocess.run(argv, capture_output=True, text=True)
    )
    result = run(["gh", "auth", "token", "--user", login])
    return result.returncode == 0


def mark_configured(
    repo: Path,
    account: str,
    used_for: str = "all-prs",
    review_requests: Optional[list] = None,
) -> None:
    """Read-validate-mutate-write (atomic): sets the `github` block
    (`verified_at`=now, `offered_at`=now, `declined`=False) AND appends
    `account.lower()` to `review.automation_identities` (creates the `review`
    block if absent; dedup; preserves existing entries).

    Committed-HEAD caveat: this write is INERT to the merge gate until it is
    committed (`deterministic_gate._load_repo_config` reads `git show
    HEAD:.three-pillars/config.json`). The first-run offer flow commits the
    config write immediately — see `first-run.md`'s `## GitHub PR-author offer`.
    """
    config_path = repo / ".three-pillars" / "config.json"
    data = _read_config(repo)
    github = data.setdefault("github", {})
    github["pr_author_account"] = account
    github["used_for"] = used_for
    github["review_requests"] = list(review_requests) if review_requests else []
    github["verified_at"] = _now_iso_utc()
    github["offered_at"] = _now_iso_utc()
    github["declined"] = False

    review = data.setdefault("review", {})
    automation = review.setdefault("automation_identities", [])
    lowered = account.lower()
    if lowered not in automation:
        automation.append(lowered)

    _atomic_write_config(config_path, data)


def mark_declined(repo: Path) -> None:
    """Sets `github.declined=True`, `offered_at=now`. Sticky — suppresses re-prompt."""
    config_path = repo / ".three-pillars" / "config.json"
    data = _read_config(repo)
    github = data.setdefault("github", {})
    github["declined"] = True
    github["offered_at"] = _now_iso_utc()
    _atomic_write_config(config_path, data)


def check(
    repo: Path,
    auto: bool = False,
    decisions_file: Optional[Path] = None,
) -> CheckResult:
    """Run the GitHub PR-author preflight branches that don't need user input.

    Returns a CheckResult; `action == "needs-prompt"` means the caller (the
    agent) must run the interactive account/no/skip prompt itself.
    """
    if not _has_origin(repo):
        return CheckResult(
            action="skip-no-origin",
            reason="git remote get-url origin failed",
            config_updated=False,
        )
    config = _read_config(repo)
    if _already_decided(config):
        return CheckResult(
            action="skip-decided",
            reason="github.pr_author_account or github.declined already set",
            config_updated=False,
        )
    if not _gh_available():
        return CheckResult(
            action="skip-gh-missing",
            reason="gh-not-installed",
            config_updated=False,
        )
    if auto:
        target = decisions_file if decisions_file is not None else (repo / "decisions.md")
        _append_auto_decision(target)
        return CheckResult(
            action="auto-skip",
            reason="auto-mode-no-interactive-prompt",
            config_updated=False,
        )
    return CheckResult(
        action="needs-prompt",
        reason="gh-available-interactive-required",
        config_updated=False,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="First-run §GitHub PR-author offer helper."
    )
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd).")
    parser.add_argument("--auto", action="store_true", help="Autonomous mode.")
    parser.add_argument(
        "--decisions-file",
        default=None,
        help="Path to decisions.md (default: <repo>/decisions.md under --auto).",
    )
    args = parser.parse_args()
    result = check(
        repo=Path(args.repo).resolve(),
        auto=args.auto,
        decisions_file=Path(args.decisions_file).resolve() if args.decisions_file else None,
    )
    print(f"action={result.action} reason={result.reason} config_updated={result.config_updated}")
