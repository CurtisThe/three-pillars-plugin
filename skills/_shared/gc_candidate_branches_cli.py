"""gc_candidate_branches_cli.py — the reaper's CLI (dry-run default; fail-closed).

Split out of gc_candidate_branches.py so the classifier core stays under the
file-size soft-warn (the design §Constraints anticipates a classify/apply/CLI
split, mirroring gc_residue / gc_residue_apply / gc_residue_fetch).

`main(argv)`:
  1. best-effort `git fetch --prune --quiet origin` (fail-open → fetch_ok bool);
  2. classify inside a try/except — on the fail-closed RAISE, report the failure,
     delete NOTHING, skip apply;
  3. print the classification table (or a --json {rows, verdicts} object);
  4. under --apply, call apply_deletions(..., fetch_ok=fetch_ok);
  5. ALWAYS return 0 (reporter contract, like sweep_candidates.main) — a
     classification failure is never a non-zero exit nor a permissive delete.

Dry-run is the default; --apply is the explicit mutation gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from gc_candidate_branches import CandidateRow, classify_candidates  # noqa: E402
from gc_candidate_branches_apply import apply_deletions  # noqa: E402


def _fetch_origin(repo: Path) -> bool:
    """Best-effort `git fetch --prune --quiet origin`. Fail-open → bool.

    --prune so origin-deleted candidates don't linger as stale tracking rows.
    A failure never aborts the reap: the caller invoked it deliberately, so we
    proceed on the cached refs and record fetch_ok=False (the apply path then
    suppresses age-axis remote deletes so stale data can't drive a delete).
    """
    result = subprocess.run(
        ["git", "fetch", "--prune", "--quiet", "origin"],
        cwd=repo, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    print(
        f"warning: `git fetch` failed (cwd={repo}); proceeding on cached refs, "
        f"age-axis remote deletes suppressed:\n{result.stderr.strip()}",
        file=sys.stderr,
    )
    return False


def _parse_live(values) -> set:
    """Parse `--live-candidate` args into a set of (slug, cand_id) tuples.

    Accepts either `candidate/{slug}/{id}` or the bare `{slug}/{id}` shape;
    anything else is ignored (never widens the delete set on a malformed arg).
    """
    live: set = set()
    for raw in values or []:
        v = raw.strip()
        if v.startswith("candidate/"):
            v = v[len("candidate/"):]
        parts = v.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            live.add((parts[0], parts[1]))
    return live


def _row_to_dict(row: CandidateRow) -> dict:
    return {
        "branch": row.branch, "slug": row.slug, "cand_id": row.cand_id,
        "surface": row.surface, "classification": row.classification,
        "action": row.action, "evidence": row.evidence,
    }


def _verdict_to_dict(v) -> dict:
    return {
        "branch": v.branch, "surface": v.surface,
        "action_taken": v.action_taken, "command": v.command,
        "error": v.error,
    }


def _print_table(rows: list) -> None:
    if not rows:
        print("no candidate/* branches found")
        return
    print(f"{'CLASSIFICATION':<15} {'SURFACE':<7} BRANCH")
    for r in rows:
        print(f"{r.classification:<15} {r.surface:<7} {r.branch}  {r.evidence}")


def _print_verdicts(verdicts: list, *, apply: bool) -> None:
    if not verdicts:
        return
    header = "deletes applied:" if apply else "deletes that WOULD run (dry-run):"
    print(f"\n{header}")
    for v in verdicts:
        suffix = f"  [{v.error}]" if v.error else ""
        print(f"  {v.action_taken:<22} {v.command}{suffix}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gc_candidate_branches",
        description="Classify and (with --apply) reap candidate/* branches.",
    )
    p.add_argument("--repo", default=".", help="repo path (default: .)")
    p.add_argument("--slug", default=None, help="scope to one design slug")
    p.add_argument("--live-candidate", action="append", default=[],
                   help="candidate/{slug}/{id} to protect (repeatable)")
    p.add_argument("--apply", action="store_true", default=False,
                   help="perform deletions (default: dry-run)")
    p.add_argument("--batch-size", type=int, default=10,
                   help="max remote refs per push --delete batch")
    p.add_argument("--json", action="store_true", default=False,
                   help="emit a machine-readable JSON object {rows, verdicts}")
    return p


def main(argv=None) -> int:
    """Reporter entry point. ALWAYS returns 0 (reporter contract)."""
    args = _build_parser().parse_args(argv)
    repo = Path(args.repo)

    # Guard a bogus --batch-size WITHOUT breaking the reporter contract (always
    # exit 0): rejecting at argparse would SystemExit(2), so clamp here (and
    # apply_deletions clamps again defensively) and warn.
    if args.batch_size < 1:
        print(
            f"warning: --batch-size {args.batch_size} < 1 is invalid; "
            f"clamping to 1",
            file=sys.stderr,
        )
        args.batch_size = 1

    fetch_ok = _fetch_origin(repo)
    live = _parse_live(args.live_candidate)

    try:
        rows = classify_candidates(repo, slug=args.slug, live=frozenset(live))
    except Exception as exc:
        # Fail-closed: enumeration / worktree-scan failure ⇒ delete NOTHING.
        msg = f"error: candidate classification failed; nothing deleted: {exc}"
        if args.json:
            print(json.dumps({"error": str(exc), "rows": [], "verdicts": []}))
        print(msg, file=sys.stderr)
        return 0

    verdicts = apply_deletions(
        rows, repo=repo, apply=args.apply,
        batch_size=args.batch_size, fetch_ok=fetch_ok,
    )

    if args.json:
        # Surface BOTH the classification and the delete outcomes so a
        # destructive --json --apply run is machine-observable, not silent.
        print(json.dumps({
            "rows": [_row_to_dict(r) for r in rows],
            "verdicts": [_verdict_to_dict(v) for v in verdicts],
        }))
    else:
        _print_table(rows)
        _print_verdicts(verdicts, apply=args.apply)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
