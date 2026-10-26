"""round_scratch_cli — the `prepare | flush | stop | remove | tail-check | put` CLI.

design: review-convergence (Task 4.6, detailed-design-pr-loop §D3)

The command half of `round_scratch.py`, split out to keep that module under its size
cap. `round_scratch.main` is a thin wrapper that lazily imports here and calls
`main`, so `round_scratch.py prepare …` as a subprocess and `rs.main([...])` in a
test both still work. Every round_scratch function is reached as a module attribute
(`rs.prepare(...)`, never a from-import), so a test that monkeypatches
`rs.<name>` (e.g. `rs.datetime`) still reaches the code running here.

`prepare` no longer decides the round: it asks `round_plan.plan` for the angle set,
the base to review and the plan's own keys, and hands them to `round_scratch.prepare`
as `meta`. So the manifest separates `base` (what this round reviewed — the prior
head on a delta round) from `pr_base` (the PR base the growth budget measures).
Exit codes are unchanged: bad angles / unknown scope / a cheap round without
`--rulings` → `angles-invalid`; a non-PR url or a refused plan → `prepare-refused`;
a tail with no valid envelope → `tail-failed`; a second rerun-review → `rerun-limit`.

`prepare --proof-root` names the proof root, which sits outside the working tree: a root
inside it (`--root .` once wrote an untracked `rounds/` into the worktree) → `prepare-refused`
before anything is written. `--root` is the deprecated alias and prints one stderr line. The
default root (under the git dir) and the root `proof_root.py` resolves (the repo config's
`review.proof_dir` names an in-tree one) are not refused.

Stdlib only.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import round_scratch as rs  # noqa: E402 — attributes only: monkeypatching `rs` reaches this


def _in_tree(root):
    """→ the work-tree toplevel `root` sits inside (refuse it), or None when it is allowed.

    Allowed: outside the cwd's work tree, under its git dir (the default proof root), or
    the very root `proof_root.py` resolves. Fail-open: no git or no work tree → None.
    """
    import proof_root  # noqa: PLC0415 — lazy: only `prepare` checks its root
    found = proof_root._git_locate(None, None)
    if found is None:
        return None
    gitdir, top = (Path(os.path.realpath(x)) for x in found)
    target = Path(os.path.realpath(root))
    if target != top and top not in target.parents:
        return None
    if target == gitdir or gitdir in target.parents:
        return None
    if target == Path(os.path.realpath(proof_root.resolve_proof_root(err=io.StringIO()))):
        return None
    return top


def _cmd_prepare(a) -> int:
    def refuse(reason, detail):
        return rs._refuse({"terminal": "needs-human-attention", "reason": reason,
                           "detail": str(detail)})

    cfg = rs._load_config(a.config)
    try:  # the url first: `plan` resolves the rounds dir (and so the round number) through it
        rs._pr_number(a.pr_url)
    except ValueError as exc:
        return refuse("prepare-refused", exc)
    top = _in_tree(a.root)
    if top is not None:  # before the plan, the state stamp or any dir: nothing is written
        return refuse("prepare-refused", f"proof root {a.root} is inside the git working tree "
                      f"{top}; pass a proof root outside it (proof_root.py prints the default)")
    try:
        import round_plan  # noqa: PLC0415 — lazy: round_plan imports round_scratch lazily
        p = round_plan.plan(cfg, root=a.root, pr_url=a.pr_url, pr_base=a.base,
                            head=a.head, repo=".", rulings_path=a.rulings,
                            scope=a.scope.split(",") if a.scope else None,
                            review_weight=a.review_weight, state_path=a.state)
    except rs.RerunLimit as exc:
        return refuse("rerun-limit", exc)
    except rs.TailFailed as exc:
        return rs._refuse({**rs.TAIL_FAILED, "detail": str(exc)})
    except round_plan.PlanRefused as exc:
        return refuse("prepare-refused", exc)
    except (ValueError, OSError) as exc:  # bad angles, unknown scope, cheap round w/o rulings
        return refuse("angles-invalid", exc)
    try:
        r = rs.prepare(a.root, a.pr_url, p["angles"], base=p["base"], head=a.head,
                       effort=a.effort, state_path=a.state, log_path=a.log,
                       plugin_root=a.plugin_root, prep_dir=a.prep_dir, config=cfg,
                       meta={k: p[k] for k in ("mode", "pr_base", "security", "diff_lines")})
    except rs.RerunLimit as exc:
        return refuse("rerun-limit", exc)
    except rs.TailFailed as exc:
        return rs._refuse({**rs.TAIL_FAILED, "detail": str(exc)})
    except (ValueError, OSError) as exc:  # unsafe angle name, unwritable root
        return refuse("prepare-refused", exc)
    print(r)
    return 0


def _cmd_remove(a) -> int:
    try:
        rs.safe_remove(a.target, a.owner)
    except rs.RemoveRefused as exc:
        return rs._refuse({"refused": str(exc)})
    print(json.dumps({"removed": str(a.target)}))
    return 0


def _cmd_tail_check(a) -> int:
    failed = rs.tail_check(a.round_dir)
    # Read the coverage line BEFORE the cleanup: a closing round's strip can remove
    # the merged file the line reads (design finder-cap-coverage Task 1.13).
    import finder_coverage  # noqa: PLC0415 — lazy: only `tail-check` prints the line
    cov = None if failed else finder_coverage.coverage_line(a.round_dir)
    rs.cleanup_round(a.round_dir, strip=not failed and rs._closing(a.round_dir))
    if failed:
        return rs._refuse(failed)
    print(json.dumps({"ok": True, "coverage": cov}))
    return 0


def _cmd_flush(a) -> int:
    stop = a.cmd == "stop"
    if not stop and bool(a.root) != bool(a.pr_url):
        return rs._refuse({"refused": "flush needs --root and --pr-url together, or neither"})
    out = {"appended": rs.flush_log(a.log, a.decisions)}
    if not stop and a.root and not (Path(a.root) / "rounds").is_dir():
        return rs._refuse({"refused": f"no rounds dir {Path(a.root) / 'rounds'} under --root "
                           "(log appended); pass the root proof_root.py prints"})
    if stop or a.root:
        try:
            root = a.root
            if not root:
                import proof_root  # noqa: PLC0415 — lazy: only `stop` defaults the root
                root = proof_root.default_proof_root()
            out["pruned"] = rs.proof_reap.close_and_prune(
                root, rs._pr_number(a.pr_url), closed_by="stop" if stop else "flush")
        except ValueError as exc:
            return rs._refuse({"refused": str(exc)})
    print(json.dumps(out))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Per-round scratch dirs for /tp-pr-iterate.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    pr = p.add_mutually_exclusive_group(required=True)
    pr.add_argument("--proof-root",
                    help="proof root (outside the working tree), not the repo root")
    pr.add_argument("--root", help="deprecated alias of --proof-root")
    for flag in ("--pr-url", "--base", "--head", "--state", "--log"):
        p.add_argument(flag, required=True)
    p.add_argument("--effort", default="high")
    p.add_argument("--config", default=".three-pillars/config.json")
    p.add_argument("--scope", default=None, help="comma-separated angle names to run")
    p.add_argument("--rulings", default=None, help="context rulings path for local finders")
    p.add_argument("--review-weight", default=None,
                   help="this round's review weight (stamped into iterate-state)")
    p.add_argument("--plugin-root", default=None, help="framework root for agent_ref")
    p.add_argument("--prep-dir", default=None, help="prep work dir W (fail-open)")
    f = sub.add_parser("flush")
    f.add_argument("--log", required=True)
    f.add_argument("--decisions", required=True)
    f.add_argument("--root")
    f.add_argument("--pr-url")
    st = sub.add_parser("stop", help="operator stop: flush the log, close and reap the round")
    st.add_argument("--log", required=True)
    st.add_argument("--decisions", required=True)
    st.add_argument("--pr-url", required=True)
    st.add_argument("--root")
    r = sub.add_parser("remove")
    r.add_argument("--target", required=True)
    r.add_argument("--owner", required=True)
    t = sub.add_parser("tail-check")
    t.add_argument("--round-dir", required=True)
    u = sub.add_parser("put", help="stdin → one slot's reply/envelope (round_put.py)")
    u.add_argument("--round-dir", required=True)
    u.add_argument("--slot", required=True, help="an angle name, or 'tail'")
    a = ap.parse_args(argv)
    if a.cmd == "put":
        import round_put  # noqa: PLC0415 — lazy: round_put imports round_scratch
        return round_put.cmd_put(a)
    if a.cmd == "prepare":
        if a.root is not None:
            print("round_scratch.py: prepare --root is deprecated; use --proof-root",
                  file=sys.stderr)
        a.root = a.proof_root if a.proof_root is not None else a.root
        return _cmd_prepare(a)
    if a.cmd in ("flush", "stop"):
        return _cmd_flush(a)
    if a.cmd == "remove":
        return _cmd_remove(a)
    return _cmd_tail_check(a)
