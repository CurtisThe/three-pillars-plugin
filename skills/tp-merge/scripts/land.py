"""land.py — the irreversible-boundary land driver for the /tp-merge land skill.

This is the ONLY code site that crosses the irreversible boundary: it runs
`gh pr merge` to land a PR. It refuses to do so unless the deterministic merge
gate PASSES — `require_merge_gate_pass` (now FIVE predicates, including the
on-head human-approval predicate `pred_human_approved`). On a blocked gate it
raises/propagates `MergeGateBlocked`, prints the blocking predicate(s) and a
pointer to the howto, and exits non-zero WITHOUT calling `gh pr merge`.

This is the code enforcement of the design guarantee: the framework never
crosses the irreversible `gh pr merge` boundary without an explicit, current
human approval. The autonomous path cannot satisfy `pred_human_approved`
(it never applies `tp:human-approved` on the head out-of-band), so it can never
land through this skill.

Exit codes:
  0 = merged (gate PASSED, gh pr merge invoked once and succeeded)
  2 = REFUSED — gate did not PASS (MergeGateBlocked), or a usage / runtime error.

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
The only side effect on the PASS path is the `gh pr merge` subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---- sys.path: the gate enforcement lives in the base-sync half's scripts dir
# (skills/tp-merge-from-main/scripts/merge_gate.py). Add it so require_merge_gate_pass
# / MergeGateBlocked import cleanly. _shared/ is reached transitively by merge_gate.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_FROM_MAIN_SCRIPTS = _SCRIPTS_DIR.parent.parent / "tp-merge-from-main" / "scripts"
if str(_FROM_MAIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FROM_MAIN_SCRIPTS))

from merge_gate import (  # noqa: E402
    MergeGateBlocked,
    require_merge_gate_pass,
)

HOWTO = "skills/_shared/human-approval-howto.md"


def _gh_pr_merge(pr_url: str) -> None:
    """Run the irreversible `gh pr merge` for pr_url. Raises CalledProcessError on failure."""
    subprocess.run(
        ["gh", "pr", "merge", pr_url, "--merge"],
        check=True,
    )


def land(
    pr_url: str,
    *,
    require_fn=None,
    merge_fn=None,
    config=None,
) -> int:
    """Gate-then-land: enforce the merge gate, then run `gh pr merge` ONLY on PASS.

    The gate is the fail-closed enforcer: `require_merge_gate_pass` raises
    `MergeGateBlocked` on any non-PASS verdict, and we NEVER reach `merge_fn` in
    that case. On a blocked gate we print the blocking predicate(s) + the howto
    pointer and return 2. On PASS we invoke `merge_fn(pr_url)` exactly once.

    Args:
        pr_url: the PR URL to land.
        require_fn: injectable gate enforcer for tests
            (default: merge_gate.require_merge_gate_pass). Must raise
            MergeGateBlocked on a non-PASS verdict.
        merge_fn: injectable irreversible-merge action for tests
            (default: _gh_pr_merge). Called at most once, ONLY on a PASS gate.
        config: optional repo-config dict threaded into the gate.

    Returns:
        0 if the gate PASSED and the merge was invoked; 2 if the gate REFUSED
        (MergeGateBlocked) or the merge action itself errored.
    """
    if require_fn is None:
        require_fn = require_merge_gate_pass
    if merge_fn is None:
        merge_fn = _gh_pr_merge

    try:
        require_fn(pr_url, config=config)
    except MergeGateBlocked as blocked:
        # REFUSE: do NOT cross the irreversible boundary. Print blockers + howto.
        print("REFUSED — merge gate did not PASS; NOT running `gh pr merge`.")
        print(str(blocked))
        outcome = getattr(blocked, "outcome", None)
        for pred in getattr(outcome, "blocking", []) or []:
            print(f"  [{pred.name}] {pred.detail}")
        print(
            f"To authorize this merge, see {HOWTO} "
            "(apply tp:human-approved on the current head, as a human, out-of-band)."
        )
        return 2

    # Gate PASSED — cross the irreversible boundary exactly once.
    try:
        merge_fn(pr_url)
    except Exception as e:  # noqa: BLE001 — surface the merge failure as a refusal-class exit
        print(f"REFUSED — `gh pr merge` failed: {type(e).__name__}: {e}")
        return 2

    print(f"Merged {pr_url} (gate PASSED).")
    return 0


def main(argv: list[str]) -> int:
    """Parse argv (exactly one positional <pr_url>), gate-then-land, return exit code."""
    positionals = [a for a in argv if not a.startswith("-")]
    flags = [a for a in argv if a.startswith("-")]
    if flags or len(positionals) != 1:
        print(
            "Usage: land.py <pr_url>\n"
            f"Error: expected exactly one PR URL argument; got argv={argv!r}",
            file=sys.stderr,
        )
        return 2
    return land(positionals[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
