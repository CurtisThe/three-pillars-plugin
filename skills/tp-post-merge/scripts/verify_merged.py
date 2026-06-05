"""verify_merged.py — dual-source merge verifier.

Primary signal: archive present on origin/{base} via git show.
Corroboration: gh pr view --json state,baseRefName returning MERGED.

Always exits 0 (reporter — the SKILL.md decides refusal).

Usage:
    python3 skills/tp-post-merge/scripts/verify_merged.py \
        --repo <repo_root> --design <name> --base <base> [--json] [--gh-cmd <path>]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Design slugs are interpolated into a `git show {ref}:...{design}/design.md`
# path and the `tp/{design}` ref, so the verifier validates its own input
# rather than trusting the caller (defense-in-depth; mirrors the SKILL's
# validate-name check). Anything outside this charset — `..`, `/`, spaces —
# is rejected at the boundary.
_DESIGN_RE = re.compile(r"^[a-z0-9-]+$")


def check_archive_on_base(repo: str, design: str, base: str) -> bool:
    """Return True if the completed archive exists on origin/{base}.

    Primary, squash-safe signal: the archive present on the base ref means
    the design's completion PR was merged (tp-design-complete writes the archive
    as part of the completion commit).

    Falls back gracefully if origin/{base} is unavailable.
    """
    repo_path = Path(repo).resolve()
    archive_path = f"three-pillars-docs/completed-tp-designs/{design}/design.md"

    # Attempt to fetch origin/{base} (fail-open)
    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "fetch", "--quiet", "origin", base],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass

    # Only consult the BASE ref — never HEAD or the design branch. The archive
    # exists on the design branch (tp/{name}) and its HEAD *before* the merge,
    # so including HEAD here would report merged=true on an unmerged PR and let
    # teardown run — breaking the inviolable merge gate. origin/{base} is the
    # authoritative squash-safe signal; the local {base} ref is an offline
    # fallback (still the base branch, never the design branch).
    for ref in (f"origin/{base}", base):
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "show", f"{ref}:{archive_path}"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        except Exception:
            pass

    return False


def check_gh_merged(design: str, gh_cmd: str = "gh", repo: str = ".") -> bool:
    """Return True if gh pr view reports state=MERGED for the design's branch.

    Runs `gh` with cwd=`repo` so the corroboration consults the same repo as
    the primary archive check — otherwise gh would infer the repo from whatever
    the current working directory happens to be (wrong repo if the caller
    invokes the script from elsewhere).

    Fail-open: if gh is missing, unauthenticated, or returns any error,
    return False (do not raise).
    """
    try:
        result = subprocess.run(
            [gh_cmd, "pr", "view", f"tp/{design}", "--json", "state,baseRefName"],
            capture_output=True,
            timeout=15,
            cwd=str(Path(repo).resolve()),
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return data.get("state") == "MERGED"
    except Exception:
        return False


def compute_verdict(archive: bool, gh: bool, base: str) -> dict[str, Any]:
    """Compute the merged verdict from primary and corroboration signals."""
    merged = archive or gh
    if archive and gh:
        via = "both"
    elif archive:
        via = "archive"
    elif gh:
        via = "pr"
    else:
        via = "none"
    return {"merged": merged, "via": via, "base": base}


def main(argv: list[str]) -> int:
    """CLI entry point. Always returns 0."""
    try:
        parser = argparse.ArgumentParser(description="Verify a design's completion PR is merged.")
        parser.add_argument("--repo", default=".", help="Path to the git repo root")
        parser.add_argument("--design", required=True, help="Design slug (name)")
        parser.add_argument("--base", default="master", help="Base branch name")
        parser.add_argument("--json", action="store_true", dest="json_output",
                            help="Output JSON verdict to stdout")
        parser.add_argument("--gh-cmd", default="gh", dest="gh_cmd",
                            help="Path to gh executable (for testing)")
        args = parser.parse_args(argv)

        # Validate the slug at the boundary — it is interpolated into a git path
        # and a ref. An invalid name is fail-safe: report merged=false (refuse
        # teardown) and exit 0, never raise, never interpolate the bad value.
        if not _DESIGN_RE.match(args.design):
            _print_fallback(argv)
            return 0

        # Primary: archive on origin/{base}
        archive = check_archive_on_base(args.repo, args.design, args.base)

        # Corroboration: gh pr view (run in the same repo as the primary check)
        gh = check_gh_merged(args.design, gh_cmd=args.gh_cmd, repo=args.repo)

        verdict = compute_verdict(archive=archive, gh=gh, base=args.base)

        if args.json_output:
            print(json.dumps(verdict))
        else:
            print(
                f"merged={verdict['merged']} via={verdict['via']} base={verdict['base']}"
            )
        return 0

    except SystemExit as exc:
        # argparse raised on CLI misuse (e.g. missing --design) or --help.
        # SystemExit is a BaseException, so the `except Exception` below would
        # NOT catch it and the non-zero argparse code would escape the
        # always-exit-0 fail-open contract. A clean --help/clean exit (code 0
        # or None) just returns 0; any error code becomes a safe merged=false
        # verdict + exit 0 — refuse-teardown-on-doubt, never crash the caller.
        if exc.code in (0, None):
            return 0
        _print_fallback(argv)
        return 0

    except Exception:
        # Absolute fail-open: even on unexpected errors, print a safe verdict and exit 0
        _print_fallback(argv)
        return 0


def _print_fallback(argv: list[str]) -> None:
    """Print a safe merged=false verdict (fail-open). Never raises.

    Honors the `--json` flag from argv so the fallback path obeys the same
    output contract as the happy path: JSON only when `--json` was passed,
    human-readable otherwise.
    """
    try:
        base = "unknown"
        for i, arg in enumerate(argv):
            if arg == "--base" and i + 1 < len(argv):
                base = argv[i + 1]
        verdict = {"merged": False, "via": "none", "base": base}
        if "--json" in argv:
            print(json.dumps(verdict))
        else:
            print(f"merged={verdict['merged']} via={verdict['via']} base={verdict['base']}")
    except Exception:
        print('{"merged": false, "via": "none", "base": "unknown"}')


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
