"""verify_merged.py — dual-source merge verifier.

Primary signal: archive present on origin/{base} via git show.
Corroboration: gh pr view --json state,baseRefName returning MERGED.

Always exits 0 (reporter — the SKILL.md decides refusal).

Usage:
    python3 skills/tp-post-merge/scripts/verify_merged.py \
        --repo <repo_root> --design <name> [--base <base>] [--json] [--gh-cmd <path>]

`--base` defaults to the repo's resolved default branch (via
`skills/_shared/default_branch.py`) when omitted.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# The shared default-branch resolver lives in skills/_shared; put it on
# sys.path so a missing --base can delegate to it (same idiom used by
# gc_residue_fetch.py and fleet_plan.py's _resolve_base).
_HERE = Path(__file__).parent
_SHARED = str(_HERE.parents[1] / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

# Design slugs are interpolated into a `git show {ref}:...{design}/design.md`
# path and the `tp/{design}` ref, so the verifier validates its own input
# rather than trusting the caller (defense-in-depth; mirrors the SKILL's
# validate-name check). Anything outside this charset — `..`, `/`, spaces —
# is rejected at the boundary.
_DESIGN_RE = re.compile(r"^[a-z0-9-]+$")


def _resolve_base(base: str | None, repo: str) -> str:
    """`base` verbatim when set, else `repo`'s default branch via the shared
    resolver, or `"master"` (today's value) on `DefaultBranchError` / import
    failure — fail-open, never raise."""
    if base:
        return base
    try:
        from default_branch import resolve_default_branch
        return resolve_default_branch(repo)
    except Exception:
        return "master"


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


def _git_out(repo: str, *args: str) -> tuple[int, str]:
    """Run git in `repo`; return (returncode, stdout). Never raises."""
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                           text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 128, ""


def ancestor_status(repo: str, design: str, base: str) -> tuple[bool, str]:
    """(True, reason) iff every `tp/{design}` tip is merged into the base by a
    merge commit: an ancestor of the base ref yet off its first-parent line.
    Total: never raises; no network."""
    try:
        if not _DESIGN_RE.match(design):
            return False, f"invalid design slug {design!r}"
        refs = (f"refs/heads/tp/{design}", f"refs/remotes/origin/tp/{design}")
        tips: list[str] = []
        for ref in refs:
            rc, out = _git_out(repo, "rev-parse", "--verify", "--quiet",
                               f"{ref}^{{commit}}")
            if rc == 0 and out and out not in tips:
                tips.append(out)
        if not tips:
            return False, f"missing ref tp/{design} (no local or origin branch)"
        base_ref = None
        for cand in (f"origin/{base}", base):
            rc, _ = _git_out(repo, "rev-parse", "--verify", "--quiet",
                             f"{cand}^{{commit}}")
            if rc == 0:
                base_ref = cand
                break
        if base_ref is None:
            return False, f"missing base ref {base}"
        rc, fp = _git_out(repo, "rev-list", "--first-parent", base_ref)
        if rc != 0:
            return False, f"cannot list first-parent line of {base_ref}"
        first_parent = set(fp.split())
        for tip in tips:
            rc, _ = _git_out(repo, "merge-base", "--is-ancestor", tip, base_ref)
            if rc != 0:
                return False, f"tip {tip[:7]} of tp/{design} is not in {base_ref}"
            if tip in first_parent:
                return False, (f"tip {tip[:7]} of tp/{design} is on {base_ref}'s "
                               "first-parent line (no merge commit)")
        return True, f"tip {tips[0][:7]} of tp/{design} merged into {base_ref}"
    except Exception as exc:  # fail-open: never raise
        return False, f"ancestor check failed: {exc}"


def _origin_host(repo: str) -> str:
    """Host part of `origin`'s URL ('' for a local path / no origin / error)."""
    rc, url = _git_out(repo, "remote", "get-url", "origin")
    if rc != 0 or not url:
        return ""
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)", url, re.I)
    if m:
        return m.group(1).lower()
    m = re.match(r"^(?:[^@/]+@)?([^/:]+):", url)  # scp-like git@host:o/r
    return m.group(1).lower() if m else ""


def origin_host_is_github(repo: str) -> bool:
    """True iff origin's host contains 'github'. Any error -> False."""
    try:
        return "github" in _origin_host(repo)
    except Exception:
        return False


def gh_status(design: str, gh_cmd: str = "gh", repo: str = ".") -> str:
    """One of merged / not-merged / unavailable / skipped-not-github.

    Runs `gh` with cwd=`repo` so it consults the same repo as the archive
    check. When origin is not GitHub-hosted, gh is only asked if it is
    authenticated for that (custom, e.g. GHE) host; a local path has no host,
    so gh never runs. Fail-open: never raises.
    """
    try:
        cwd = str(Path(repo).resolve())
        has_origin = _git_out(repo, "remote", "get-url", "origin")[0] == 0
        # No origin at all keeps the legacy behaviour (gh infers the repo);
        # an origin without a host (a local path) has nothing for gh to ask.
        if has_origin and not origin_host_is_github(repo):
            host = _origin_host(repo)
            if not host:
                return "skipped-not-github"
            try:
                auth = subprocess.run([gh_cmd, "auth", "status", "--hostname", host],
                                      capture_output=True, timeout=15, cwd=cwd)
            except OSError:  # gh not installed: nothing can ask this host
                return "skipped-not-github"
            if auth.returncode != 0:
                return "skipped-not-github"
        result = subprocess.run(
            [gh_cmd, "pr", "view", f"tp/{design}", "--json", "state,baseRefName"],
            capture_output=True, timeout=15, cwd=cwd,
        )
        if result.returncode != 0:
            return "unavailable"
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return "merged" if data.get("state") == "MERGED" else "not-merged"
    except Exception:
        return "unavailable"


def check_gh_merged(design: str, gh_cmd: str = "gh", repo: str = ".") -> bool:
    """True if gh reports the design's PR MERGED (fail-open False)."""
    return gh_status(design, gh_cmd, repo) == "merged"


def compute_verdict(archive: bool, gh: bool, base: str,
                    ancestor: bool = False) -> dict[str, Any]:
    """Compute the merged verdict from primary and corroboration signals."""
    if archive and gh:
        via = "both"
    elif archive:
        via = "archive"
    elif gh:
        via = "pr"
    elif ancestor:
        via = "ancestor"
    else:
        via = "none"
    return {"merged": archive or gh or ancestor, "via": via, "base": base}


_REMEDY = ("archive it (/tp-design-complete), or merge it with a merge commit, "
           "then re-run /tp-post-merge")

_GH_REASONS = {
    "merged": "gh reports the PR merged",
    "not-merged": "gh reports the PR is not merged",
    "unavailable": "gh unavailable or returned an error",
    "skipped-not-github": "origin is not GitHub (gh skipped)",
}


def evaluate(repo: str, design: str, base: str, gh_cmd: str = "gh") -> dict[str, Any]:
    """Run all three checks; verdict plus per-check reasons and a remedy."""
    archive = check_archive_on_base(repo, design, base)
    gh_state = gh_status(design, gh_cmd=gh_cmd, repo=repo)
    anc, anc_reason = ancestor_status(repo, design, base)
    verdict = compute_verdict(archive=archive, gh=gh_state == "merged",
                              base=base, ancestor=anc)
    verdict["checks"] = {
        "archive": (f"archive present on {base}" if archive
                    else f"archive not found on origin/{base}"),
        "gh": _GH_REASONS.get(gh_state, gh_state),
        "ancestor": anc_reason,
    }
    verdict["remedy"] = "" if verdict["merged"] else _REMEDY
    return verdict


def main(argv: list[str]) -> int:
    """CLI entry point. Always returns 0."""
    try:
        parser = argparse.ArgumentParser(description="Verify a design's completion PR is merged.")
        parser.add_argument("--repo", default=".", help="Path to the git repo root")
        parser.add_argument("--design", required=True, help="Design slug (name)")
        parser.add_argument("--base", default=None,
                            help="Base branch name (default: the repo's resolved "
                                 "default branch, via skills/_shared/default_branch.py)")
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

        args.base = _resolve_base(args.base, args.repo)

        verdict = evaluate(args.repo, args.design, args.base, gh_cmd=args.gh_cmd)

        if args.json_output:
            print(json.dumps(verdict))
        else:
            line = f"merged={verdict['merged']} via={verdict['via']} base={verdict['base']}"
            if not verdict["merged"]:
                line += f" checks={json.dumps(verdict['checks'])} remedy={verdict['remedy']}"
            print(line)
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
