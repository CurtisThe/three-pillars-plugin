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

Land-boundary backstop (Decision 7): even before the gate runs, land() resolves
review.require_human_approval from the committed HEAD config. If it resolves
false, land() refuses immediately — the require_fn and merge_fn are NEVER called.
This closes the residual: a committed opt-out that passes the gate-level predicate
omission cannot bypass the irreversible boundary without a human setting that flag
true at HEAD via a reviewed PR, then applying tp:human-approved.

Exit codes:
  0 = merged (gate PASSED, gh pr merge invoked once and succeeded)
  2 = REFUSED — gate did not PASS (MergeGateBlocked), backstop refused, or
      a usage / runtime error.

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
_SHARED_DIR = _SCRIPTS_DIR.parent.parent / "_shared"
if str(_FROM_MAIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FROM_MAIN_SCRIPTS))
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from merge_gate import (  # noqa: E402
    MergeGateBlocked,
    require_merge_gate_pass,
)
from deterministic_gate import _load_repo_config  # noqa: E402
from human_approval import _require_human_approval  # noqa: E402
from single_account_detect import approval_collision_signature_live  # noqa: E402

HOWTO = "skills/_shared/human-approval-howto.md"
HOWTO_FLIP_SECTION = f"{HOWTO} §Single-account operator"


def _print_roster(outcome) -> None:
    """Print the ROSTER block for a GateOutcome. Fail-open: never raises.

    Printing must never block a refusal or a merge decision, so all errors
    are silently swallowed. Called on both PASS and refuse paths.
    """
    try:
        if outcome is None:
            return
        import gate_roster  # noqa — in _shared/ beside deterministic_gate
        roster_lines = gate_roster.render_roster(outcome)
        if roster_lines:
            print("ROSTER:")
            for line in roster_lines:
                print(line)
    except Exception:
        pass  # fail-open


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

    # ---- Land-boundary backstop (Decision 7) --------------------------------
    # Resolve the config from committed HEAD for the backstop check only.
    # The backstop uses its OWN config read — independent of what the gate chain
    # sees. The gate chain (require_fn) is called with config=None so that
    # evaluate_gate performs the binding check itself (W4 provenance). Passing
    # config=cfg here would skip the binding check on the irreversible path
    # because evaluate_gate only binds when config is None.
    #
    # If review.require_human_approval resolves false, refuse IMMEDIATELY —
    # before the gate runs, before require_fn is called, before merge_fn is
    # called. The irreversible boundary is unreachable under any opt-out.
    if config is not None:
        # Explicit config injected (tests): use it for both backstop and gate.
        backstop_cfg = config
        gate_config = config
    else:
        # Live path: backstop reads config independently; gate binds itself.
        backstop_cfg = _load_repo_config()
        gate_config = None
    if not _require_human_approval(backstop_cfg):
        # _require_human_approval only returns False when review IS a dict and
        # require_human_approval is explicitly false — so the .get chain here is
        # type-safe (review is guaranteed dict at this point).
        _rha_raw = backstop_cfg.get("review", {}).get("require_human_approval", True)  # type: ignore[union-attr]
        print("REFUSED — land-boundary backstop: review.require_human_approval resolves false.")
        print("  predicate: human_approved")
        print(f"  resolved: review.require_human_approval = {_rha_raw!r}")
        print(
            "  To authorize: set review.require_human_approval = true at HEAD via a "
            "reviewed PR, then apply tp:human-approved:<head-sha> per "
            f"{HOWTO}."
        )
        return 2
    # -------------------------------------------------------------------------

    try:
        outcome = require_fn(pr_url, config=gate_config)
    except MergeGateBlocked as blocked:
        # REFUSE: do NOT cross the irreversible boundary. Print blockers + howto.
        print("REFUSED — merge gate did not PASS; NOT running `gh pr merge`.")
        print(str(blocked))
        blocked_outcome = getattr(blocked, "outcome", None)
        blocking_preds = getattr(blocked_outcome, "blocking", []) or []
        for pred in blocking_preds:
            print(f"  [{pred.name}] {pred.detail}")
        # Print roster on the refuse path (fail-open: never blocks the refusal)
        _print_roster(blocked_outcome)
        # T1.5: When threads_resolved blocks, print a pointer to the dispose gesture.
        # pred_threads_resolved and require_merge_gate_pass are NOT modified — only
        # the human-facing refusal text gains this remediation pointer.
        if any(getattr(p, "name", "") == "threads_resolved" for p in blocking_preds):
            print(
                "  Hint: to reply-and-resolve open review threads out-of-band, run:\n"
                "    /tp-pr-iterate {design} --dispose-only"
            )
        # Collision branch: when human_approved blocks AND the collision signature holds
        # (a tp:human-approved label is present but the labeling actor == the self-login),
        # print identity-flip instructions instead of the generic howto line.
        # Message-only — require_fn, the gate roster, and the return code (2) are untouched.
        _human_approved_blocks = any(
            getattr(p, "name", "") == "human_approved" for p in blocking_preds
        )
        if _human_approved_blocks and approval_collision_signature_live(
            pr_url, runners=None
        ):
            print(
                f"  Single-account collision detected: your approval login is the "
                f"framework's own gh-auth login. The gate rejects it because it "
                f"cannot distinguish your human action from a framework self-apply.\n"
                f"  Remedy — create a separate GitHub machine account for automation:\n"
                f"    1. Create a new GitHub account (e.g. YourNameBot).\n"
                f"    2. Add it as a repo collaborator and authenticate gh as that account.\n"
                f"    3. Re-apply tp:human-approved:<head-sha> from your HUMAN account.\n"
                f"  See {HOWTO_FLIP_SECTION} for the full flip walk-through."
            )
        else:
            print(
                f"To authorize this merge, see {HOWTO} "
                "(apply tp:human-approved:<head-sha> on the current head, as a human, out-of-band)."
            )
        return 2

    # Gate PASSED — print roster, then cross the irreversible boundary exactly once.
    _print_roster(outcome)
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
