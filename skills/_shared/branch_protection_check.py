"""branch_protection_check.py — first-run preflight helper for `branch-protection.md`.

Handles the three programmable branches of the §Branch-protection detection flow:

- **no-origin silent skip**: `git remote get-url origin` fails → no prompt, no
  config write, no stdout. Re-checks on the next invocation.
- **gh missing fail-open**: `gh` not on PATH → write fail-open config
  (declined=false, applied_at=null, offered_at=now), print the manual command
  from `branch-protection.md` to stdout. The user has the literal command in
  their scrollback for later.
- **--auto skip + log**: autonomous mode → append a `[first-run]` entry to
  `decisions.md` per `auto-mode.md`, leave config untouched.

The interactive happy-path (gh present, user prompted yes/no/skip) is the
agent's responsibility, not this module's. The helper signals that case via
`action == "needs-prompt"`.
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


# Single-line summary mirrors `branch-protection.md` §The gh api call.
_GH_API_ONE_LINE = (
    "gh api -X PUT repos/{owner}/{repo}/branches/{branch}/protection"
)

_GH_API_FULL_TEMPLATE = """gh api -X PUT \\
  -H "Accept: application/vnd.github+json" \\
  "repos/{owner}/{repo}/branches/{branch}/protection" \\
  -F "required_status_checks=null" \\
  -F "enforce_admins=null" \\
  -F "required_pull_request_reviews[required_approving_review_count]=1" \\
  -F "required_pull_request_reviews[dismiss_stale_reviews]=true" \\
  -F "restrictions=null" \\
  -F "allow_force_pushes=false" \\
  -F "allow_deletions=false" \\
  -F "required_linear_history=false" \\
  -F "required_conversation_resolution=false\""""


@dataclass
class CheckResult:
    """What the helper decided to do.

    `action`: one of "skip-no-origin", "fail-open-gh-missing", "auto-skip",
              "needs-prompt".
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


def _resolve_repo_meta(repo: Path) -> tuple[str, str, str]:
    """Best-effort owner/repo/branch resolution for the manual-command template.

    On failure returns placeholder tokens so the printed command still parses
    when the user pastes it into their shell (they'll substitute by hand).
    """
    owner, name, branch = "{owner}", "{repo}", "{branch}"
    url_result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if url_result.returncode == 0:
        url = url_result.stdout.strip()
        # Accept git@github.com:Acme/widget.git or https://github.com/Acme/widget(.git)
        if "github.com" in url:
            tail = url.split("github.com", 1)[1].lstrip(":/")
            if tail.endswith(".git"):
                tail = tail[: -len(".git")]
            if "/" in tail:
                owner, name = tail.split("/", 1)
    head_result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if head_result.returncode == 0:
        ref = head_result.stdout.strip()
        if ref.startswith("refs/remotes/origin/"):
            branch = ref[len("refs/remotes/origin/") :]
    return owner, name, branch


def _format_manual_command(repo: Path) -> str:
    owner, name, branch = _resolve_repo_meta(repo)
    body = _GH_API_FULL_TEMPLATE.format(owner=owner, repo=name, branch=branch)
    return (
        "Branch protection could not be applied automatically. "
        "You can apply it later by running:\n\n"
        "  gh auth login                                # if not yet authenticated\n"
        f"  {body}\n\n"
        "After running, re-invoke any tp-* skill — first-run will detect the rule "
        "and stamp config.branch_protection.applied_at.\n"
    )


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


def _write_fail_open(repo: Path) -> None:
    config_path = repo / ".three-pillars" / "config.json"
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        data = {"schema_version": 1}
    bp = data.setdefault("branch_protection", {})
    bp["offered_at"] = _now_iso_utc()
    bp["applied_at"] = None
    bp["declined"] = False
    bp.setdefault("profile", None)
    _atomic_write_config(config_path, data)


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
        "### [first-run] Branch protection\n"
        "**Question**: Apply GitHub branch protection to the default branch?\n"
        "**Decided**: Skip — no interactive prompt available in --auto.\n"
        "**Reasoning**: Branch protection is a one-time UX decision that "
        "blocks self-merge; deferring lets the next interactive run surface "
        "the trade-off to the user.\n"
        "**Confidence**: Medium\n\n"
    )
    with decisions_path.open("a") as f:
        f.write(entry)


def check(
    repo: Path,
    auto: bool = False,
    decisions_file: Optional[Path] = None,
) -> CheckResult:
    """Run the branch-protection preflight branches that don't need user input.

    Returns a CheckResult; `action == "needs-prompt"` means the caller (the
    agent) must run the interactive yes/no/skip prompt itself.
    """
    if not _has_origin(repo):
        return CheckResult(
            action="skip-no-origin",
            reason="git remote get-url origin failed",
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
    if not _gh_available():
        _write_fail_open(repo)
        print(_format_manual_command(repo))
        return CheckResult(
            action="fail-open-gh-missing",
            reason="gh-not-installed",
            config_updated=True,
        )
    return CheckResult(
        action="needs-prompt",
        reason="gh-available-interactive-required",
        config_updated=False,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="First-run §Branch-protection detection helper."
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
