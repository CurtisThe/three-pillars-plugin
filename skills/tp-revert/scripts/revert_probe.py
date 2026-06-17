"""revert_probe — read-only reporter for /tp-revert.

Classify only; always exits 0; performs no writes.
gh_fn injection seam for hermetic tests (pattern: merged_pr_number in
reconcile_docs.py, derive_base_ref in diff_balloon_guard.py).

CLI: revert_probe.py --repo . (--pr N | --sha SHA) [--base master] --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _run(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git"] + list(args), cwd=repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _fetch_origin(repo: str) -> bool:
    r = subprocess.run(["git", "fetch", "--quiet", "origin"],
                       cwd=repo, capture_output=True, text=True)
    if r.returncode == 0:
        return True
    print(f"warning: `git fetch origin` failed (repo={repo}), proceeding with "
          f"locally cached origin refs:\n{r.stderr.strip()}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# merge_depth
# ---------------------------------------------------------------------------

def merge_depth(repo: str, merge_sha: str, base: str) -> int:
    """First-parent distance from merge_sha to origin/{base}. 0 = newest."""
    return int(_run(repo, "rev-list", "--first-parent", "--count",
                    f"{merge_sha}..origin/{base}"))


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------

@dataclass
class MergeTarget:
    merge_sha: str
    pr_number: int | None
    slug: str | None
    base: str
    error: str | None = None


def resolve_target(repo: str, pr: int | None = None, sha: str | None = None,
                   base: str = "master", gh_fn=None) -> MergeTarget:
    """Resolve --pr or --sha into a MergeTarget; error field set on failure."""
    if gh_fn is None:
        gh_fn = lambda cmd, **kw: subprocess.run(cmd, **kw)

    if pr is not None:
        try:
            r = gh_fn(["gh", "pr", "view", str(pr),
                        "--json", "mergeCommit,headRefName,baseRefName,state"],
                       capture_output=True, text=True, cwd=repo)
            data = json.loads(r.stdout)
        except Exception as exc:
            return MergeTarget("", pr, None, base, error=f"gh error: {exc}")
        state = data.get("state", "")
        mc = data.get("mergeCommit")
        if state != "MERGED" or not mc:
            return MergeTarget("", pr, None, base,
                               error=f"PR #{pr} is not merged (state={state})")
        head = data.get("headRefName", "")
        slug = head[len("tp/"):] if head.startswith("tp/") else None
        return MergeTarget(mc["oid"], pr, slug, data.get("baseRefName", base))

    if sha is not None:
        # normalize abbreviated sha to full 40-char sha
        norm = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
            cwd=repo, capture_output=True, text=True,
        )
        if norm.returncode != 0 or not norm.stdout.strip():
            return MergeTarget(sha, None, None, base,
                               error=f"unknown object: {sha}")
        full_sha = norm.stdout.strip()
        # count parents
        try:
            parents = _run(repo, "rev-list", "--parents", "-n", "1", full_sha).split()
        except subprocess.CalledProcessError:
            parents = [full_sha]
        if len(parents) < 3:  # sha + at least 2 parents
            return MergeTarget(full_sha, None, None, base,
                               error=f"sha {full_sha[:12]} is not a merge commit")
        # check first-parent reachability
        try:
            fps = set(_run(repo, "rev-list", "--first-parent",
                           f"origin/{base}").splitlines())
        except subprocess.CalledProcessError as exc:
            return MergeTarget(full_sha, None, None, base,
                               error=f"could not resolve origin/{base}: {exc}")
        if full_sha not in fps:
            return MergeTarget(full_sha, None, None, base,
                               error=f"sha {full_sha[:12]} not on origin/{base} first-parent")
        return MergeTarget(full_sha, None, None, base)

    return MergeTarget("", None, None, base, error="must supply --pr or --sha")


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

@dataclass
class Forecast:
    clean: bool | None
    conflicted: list[str] = field(default_factory=list)
    error: str | None = None


def forecast(repo: str, merge_sha: str, base: str) -> Forecast:
    """Dry-run git revert -m 1 --no-commit in a scratch worktree (always cleaned up)."""
    wt = Path(repo) / ".claude" / "worktrees" / f"revert-probe-{merge_sha[:8]}"
    wt_created = False
    try:
        add_result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(wt), f"origin/{base}"],
            cwd=repo, capture_output=True, text=True,
        )
        if add_result.returncode != 0:
            err = f"forecast worktree-add failed: {add_result.stderr.strip()}"
            return Forecast(clean=None, conflicted=[], error=err)
        wt_created = True
        r = subprocess.run(
            ["git", "revert", "-m", "1", "--no-commit", merge_sha],
            cwd=str(wt), capture_output=True, text=True,
        )
        if r.returncode == 0:
            return Forecast(clean=True)
        conflicted = [
            l for l in subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=str(wt), capture_output=True, text=True,
            ).stdout.splitlines() if l.strip()
        ]
        return Forecast(clean=False, conflicted=conflicted)
    finally:
        if wt_created and wt.exists():
            subprocess.run(["git", "revert", "--abort"],
                           cwd=str(wt), capture_output=True, text=True)
        if wt_created:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=repo, capture_output=True, text=True)
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None, gh_fn=None, runner=None) -> int:
    p = argparse.ArgumentParser(description="Revert probe — read-only reporter")
    p.add_argument("--repo", default=".")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", type=int)
    g.add_argument("--sha")
    p.add_argument("--base", default="master")
    p.add_argument("--json", dest="json_out", action="store_true")
    args = p.parse_args(argv)
    repo = str(Path(args.repo).resolve())
    _fetch_origin(repo)
    t = resolve_target(repo, pr=args.pr, sha=args.sha, base=args.base, gh_fn=gh_fn)
    out: dict = {"merge_sha": t.merge_sha or None, "pr": t.pr_number,
                 "slug": t.slug, "base": t.base, "depth": None,
                 "clean": None, "conflicted": [], "error": t.error}
    if t.error is None:
        try:
            out["depth"] = merge_depth(repo, t.merge_sha, t.base)
        except subprocess.CalledProcessError as exc:
            out["error"] = f"merge_depth failed: {exc}"
            if args.json_out:
                print(json.dumps(out))
            return 0
        fc = forecast(repo, t.merge_sha, t.base)
        if fc.error is not None:
            out["error"] = fc.error
        out["clean"] = fc.clean
        out["conflicted"] = fc.conflicted
    if args.json_out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
