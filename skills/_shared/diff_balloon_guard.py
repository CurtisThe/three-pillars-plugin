"""diff_balloon_guard.py — the diff-balloon measurement + predicate.

Guards against the diff-balloon corruption class: a candidate PR whose diff
has ballooned (>= 5× the fork-point baseline) due to a bad rebase or
stale base, blocking it as a pre-merge predicate composing with evaluate_gate.

The predicate returns a deterministic_gate.PredicateResult and is appended
to evaluate_gate's predicate list in deterministic_gate.py.

Hermetic testing: inject sizes=(candidate_lines, baseline_lines) to bypass
the live git measurement path. CLI: --candidate-size / --baseline-size.

Design refs:
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/detailed-design.md
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/plan.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Ensure _shared/ is on sys.path so we can import sibling modules
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from deterministic_gate import GateVerdict, PredicateResult  # noqa: E402


# ---------------------------------------------------------------------------
# Task 2.1: balloon_factor — ratio with zero-baseline floor
# ---------------------------------------------------------------------------


def balloon_factor(candidate: int, baseline: int) -> float:
    """Compute the diff balloon factor: candidate / max(baseline, 1).

    A zero/near-zero baseline floors the denominator to 1 so a small honest
    design never causes a divide-by-zero. The factor is dimensionless.
    """
    return candidate / max(baseline, 1)


# ---------------------------------------------------------------------------
# Task 2.4: _sum_numstat + baseline_size / candidate_size
# ---------------------------------------------------------------------------


def _sum_numstat(text: str) -> int:
    """Sum insertions + deletions from `git diff --numstat` output.

    Each line is: <insertions>\\t<deletions>\\t<filename>
    Binary files show '-\\t-\\t<filename>' — those lines are skipped.
    """
    total = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        ins_str, del_str = parts[0], parts[1]
        # Binary files use '-' for both fields
        if ins_str == "-" or del_str == "-":
            continue
        try:
            total += int(ins_str) + int(del_str)
        except ValueError:
            continue
    return total


def _run_git(repo: str, args: list[str]) -> str:
    """Run a git command in `repo` and return its stdout. Raises on error."""
    result = subprocess.run(
        ["git", "-C", repo] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def baseline_size(repo: str, base_ref: str, head_ref: str) -> int:
    """The HONEST PR diff: three-dot `base_ref...head_ref` (changes on head only).

    Three-dot diffs head against the merge-base, so commits that landed on
    base_ref AFTER the fork-point are excluded. This is the size the PR *should*
    show: only the work done on the branch. For a clean branch current with base
    this equals the two-dot candidate (factor ~1.0); when the base has drifted,
    the two-dot candidate balloons above this honest baseline.
    """
    numstat = _run_git(repo, ["diff", "--numstat", f"{base_ref}...{head_ref}"])
    return _sum_numstat(numstat)


def candidate_size(repo: str, base_ref: str, head_ref: str) -> int:
    """The MEASURED diff git/GitHub would show: two-dot `base_ref..head_ref`.

    Two-dot diffs the literal tip of base_ref against head_ref. When head_ref is
    built on a stale base (bad rebase / stale-base balloon), this includes every
    line that base_ref has moved on past head's fork-point — so it inflates above
    the honest three-dot baseline, which is exactly the balloon signature.
    """
    numstat = _run_git(repo, ["diff", "--numstat", f"{base_ref}..{head_ref}"])
    return _sum_numstat(numstat)


# ---------------------------------------------------------------------------
# Task 2.2 + 2.3: pred_diff_not_ballooned
# ---------------------------------------------------------------------------


def pred_diff_not_ballooned(
    *,
    repo: str,
    base_ref: str,
    head_ref: str,
    factor: float = 5.0,
    sizes: "tuple[int, int] | None" = None,
) -> PredicateResult:
    """Gate predicate: FAIL iff the candidate diff balloons >= factor × baseline.

    Args:
        repo:      git repo root
        base_ref:  the base branch (e.g. 'master')
        head_ref:  the candidate HEAD ref
        factor:    balloon threshold (default 5.0, inclusive: >= factor → FAIL)
        sizes:     (candidate_lines, baseline_lines) override for hermetic tests;
                   when None, measures from git via fork-point.

    Returns a PredicateResult named 'diff_not_ballooned'.
    FAIL on >= threshold, PASS below, INDETERMINATE on any error (fail-closed).
    """
    try:
        if sizes is not None:
            cand, base = sizes
        else:
            cand = candidate_size(repo, base_ref, head_ref)
            base = baseline_size(repo, base_ref, head_ref)

        bf = balloon_factor(cand, base)

        if bf >= factor:
            return PredicateResult(
                name="diff_not_ballooned",
                verdict=GateVerdict.FAIL,
                detail=(
                    f"diff balloon {bf:.2f}× >= {factor}× threshold "
                    f"(candidate={cand} lines, baseline={base} lines) — "
                    f"possible bad rebase or stale base; review the diff size"
                ),
            )
        return PredicateResult(
            name="diff_not_ballooned",
            verdict=GateVerdict.PASS,
            detail=(
                f"diff balloon {bf:.2f}× < {factor}× threshold "
                f"(candidate={cand} lines, baseline={base} lines)"
            ),
        )
    except Exception as e:
        return PredicateResult(
            name="diff_not_ballooned",
            verdict=GateVerdict.INDETERMINATE,
            detail=f"could not measure diff balloon: {e}",
        )


# ---------------------------------------------------------------------------
# derive_base_ref — resolve base branch name from a PR URL via gh CLI
# ---------------------------------------------------------------------------


def derive_base_ref(pr_url: str, runner=None) -> "str | None":
    """Resolve the base branch name for a PR URL via the gh CLI.

    Args:
        pr_url: The pull request URL (e.g. https://github.com/o/r/pull/1).
        runner: Optional injection seam for hermetic tests. When provided,
                called as runner(cmd_list) -> str (stdout). When None, runs
                the real gh CLI via subprocess.

    Returns:
        The base ref name string, or None on any error (gh not found,
        non-zero exit, bad JSON, empty value, exception).
    """
    import json as _json

    cmd = ["gh", "pr", "view", pr_url, "--json", "baseRefName"]
    try:
        if runner is not None:
            output = runner(cmd)
        else:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                return None
            output = result.stdout
        data = _json.loads(output)
        base = data.get("baseRefName", "")
        return base if base else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Task 2.5: main CLI — exit codes 0/1/2 mirroring gate_cli
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    """CLI for diff_balloon_guard.

    Inject sizes via --candidate-size / --baseline-size (no git needed).
    Without injection, measures from git using --repo / --base-ref / --head-ref.

    Exit codes:
      0 → PASS (below threshold)
      1 → FAIL (balloon >= threshold)
      2 → INDETERMINATE (git/parse error)

    Mirrors gate_cli.py's PASS/FAIL/INDETERMINATE → 0/1/2 contract.
    """
    parser = argparse.ArgumentParser(
        description="Diff balloon guard: block a PR whose diff balloons vs fork-point baseline.",
    )
    parser.add_argument("--repo", default=".", help="git repo root")
    parser.add_argument("--base-ref", default="master", dest="base_ref",
                        help="base branch (default: master)")
    parser.add_argument("--head-ref", default="HEAD", dest="head_ref",
                        help="candidate HEAD ref (default: HEAD)")
    parser.add_argument("--factor", type=float, default=5.0,
                        help="balloon threshold factor (default: 5.0)")
    parser.add_argument("--candidate-size", type=int, default=None, dest="candidate_size",
                        help="override candidate size (total insertions+deletions)")
    parser.add_argument("--baseline-size", type=int, default=None, dest="baseline_size",
                        help="override baseline size (total insertions+deletions)")
    args = parser.parse_args(argv)

    # Build sizes override if both are provided
    sizes = None
    if args.candidate_size is not None and args.baseline_size is not None:
        sizes = (args.candidate_size, args.baseline_size)

    result = pred_diff_not_ballooned(
        repo=args.repo,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        factor=args.factor,
        sizes=sizes,
    )

    if result.verdict == GateVerdict.PASS:
        return 0
    elif result.verdict == GateVerdict.FAIL:
        print(f"FAIL: {result.detail}", file=sys.stderr)
        return 1
    else:  # INDETERMINATE
        print(f"INDETERMINATE: {result.detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
