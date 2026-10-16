#!/usr/bin/env python3
"""carry_check.py — the loop's ONE carry question, always with the COMMITTED config.

design: review-convergence Phase 10 (detailed-design-gates §E1).

The #246 run read the carry as "off" because it evaluated with no config. This module
makes that shape impossible: the config is read with
`repo_config_load.load_repo_config(repo_root, source="head")` — `git show HEAD:` — so an
uncommitted worktree edit can never flip the answer, and there is deliberately NO
`--config` flag on the CLI (argparse rejects it with exit 2: the config is never
injected).

  carry_status(repo_root) -> (on, reason)          # exact §E1 reason strings
  check(repo_root, pr_url, head, *, runners=None)  # {"carried", "reason", "detail"}
  CLI: carry_check.py --repo P --pr-url U [--head SHA] [--json]
       exit 0 carried / 1 not carried / 2 error (bad repo, git failure, usage)

Ordering (convergence-rules §Base-sync): after any mid-loop `/tp-merge-from-main` push
the loop runs this BEFORE preparing the next round and before any `round_scratch.py
flush` commit. Carried → straight to the converge oracle on the synced head; not
carried → the next round is a delta round, never a full re-review.

"on" is decided by `base_sync_cert.carry_enabled(config)` — True only for a literal
`true` at `review.approval_survives_safe_base_sync`. Carried means
`proof_predicate.pred_review_proof_on_head(...) == GateVerdict.PASS`, with the
predicate's own detail passed through. Stdlib-only; `check` never raises (any internal
error fails closed to `carried=False` with a `carry check error: …` reason).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

OFF_NO_CONFIG = "carry off: no committed .three-pillars/config.json at HEAD"
OFF_UNREADABLE_FMT = "carry off: config unreadable at HEAD ({error})"
OFF_KEY = ("carry off: review.approval_survives_safe_base_sync is not true "
           "in the committed config")
ON = "carry on"


def _head_load(repo_root):
    import repo_config_load  # lazy — keeps module import cheap and cycle-free

    return repo_config_load.load_repo_config(repo_root, source="head")


def _status_of(load) -> "tuple[bool, str]":
    """(on, reason) for one `ConfigLoad`. `unreadable` quotes the FIRST warning — the
    reader's own reason text — inside the §E1 wrapper."""
    import base_sync_cert  # lazy — config interpreter lives with the certifier

    if load.status == "absent":
        return False, OFF_NO_CONFIG
    if load.status == "unreadable":
        error = (load.warnings or ["unreadable"])[0]
        return False, OFF_UNREADABLE_FMT.format(error=error)
    if not base_sync_cert.carry_enabled(load.config):
        return False, OFF_KEY
    return True, ON


def carry_status(repo_root) -> "tuple[bool, str]":
    """The carry posture of `repo_root` as of its COMMITTED config at HEAD.

    Never raises (`load_repo_config` is total; a non-repo or a repo with no HEAD reads
    as `absent`). Reasons are the §E1 strings verbatim; `("carry on", "carry on")` only
    for a literal-true `review.approval_survives_safe_base_sync`."""
    return _status_of(_head_load(repo_root))


def check(repo_root, pr_url, head, *, runners=None) -> dict:
    """{"carried", "reason", "detail"} for one PR head.

    Carry off → the `carry_status` reason, `detail ""` (the predicate is never reached).
    Carry on → `pred_review_proof_on_head` with the HEAD config and `repo_root`, plus
    the seams named in `runners` (`comments_fn`, `self_login_fn`, `run_git`,
    `derive_base_ref_fn`; an absent key is the predicate's own default). `carried` is
    the verdict being PASS; `detail` is the predicate's detail; reason "carry on".

    Total: any internal exception fails closed to `carried=False` with
    `"carry check error: <exc>"` (exit 1 at the CLI — an error is never a carry)."""
    try:
        load = _head_load(repo_root)
        on, reason = _status_of(load)
        if not on:
            return {"carried": False, "reason": reason, "detail": ""}
        import proof_predicate  # lazy — only the carry-on path needs the predicate
        from deterministic_gate import GateVerdict  # late, circular-safe

        seams = runners or {}
        verdict = proof_predicate.pred_review_proof_on_head(
            pr_url, head,
            comments_fn=seams.get("comments_fn"),
            config=load.config,
            self_login_fn=seams.get("self_login_fn"),
            run_git=seams.get("run_git"),
            derive_base_ref_fn=seams.get("derive_base_ref_fn"),
            repo_root=repo_root,
        )
        return {"carried": verdict.verdict == GateVerdict.PASS,
                "reason": ON,
                "detail": verdict.detail}
    except Exception as exc:  # noqa: BLE001 — total by contract, fail closed
        return {"carried": False, "reason": f"carry check error: {exc}", "detail": ""}


def _git_ok(repo: str, *args: str) -> "tuple[bool, str]":
    try:
        proc = subprocess.run(["git", "-C", repo, *args],
                              capture_output=True, text=True)
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or "").strip()
    return True, proc.stdout.strip()


def main(argv=None) -> int:
    """`carry_check.py --repo P --pr-url U [--head SHA] [--json]`.

    `--head` defaults to `git -C P rev-parse HEAD`. Prints the reason line (or the whole
    result dict as JSON with `--json`). Exit 0 carried / 1 not carried / 2 error (bad
    repo, git failure, usage). NO `--config` flag exists — argparse rejects it with 2."""
    import argparse

    parser = argparse.ArgumentParser(prog="carry_check.py")
    parser.add_argument("--repo", required=True, help="repository to read HEAD from")
    parser.add_argument("--pr-url", required=True)
    parser.add_argument("--head", default=None,
                        help="head sha (default: git -C <repo> rev-parse HEAD)")
    parser.add_argument("--json", action="store_true", help="print the result dict")
    args = parser.parse_args(argv)  # a usage error exits 2

    ok, out = _git_ok(args.repo, "rev-parse", "--git-dir")
    if not ok:
        print(f"error: {args.repo!r} is not a git repository ({out})", file=sys.stderr)
        return 2
    head = args.head
    if head is None:
        ok, head = _git_ok(args.repo, "rev-parse", "HEAD")
        if not ok:
            print(f"error: cannot resolve HEAD in {args.repo!r} ({head})",
                  file=sys.stderr)
            return 2

    result = check(args.repo, args.pr_url, head)
    print(json.dumps(result) if args.json else result["reason"])
    return 0 if result["carried"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
