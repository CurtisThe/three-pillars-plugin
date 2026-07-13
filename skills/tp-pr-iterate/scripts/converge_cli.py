"""converge_cli.py — argparse `main()` for the converge.py primitive.

Split from converge.py (which carries the core `converge()` orchestration) so
neither file nears the file-size cap. The CLI shape is:

    converge.py --base <sha> --head <sha> --pr-url <url> --config <path>
                --angle-file r1.txt [--angle-file r2.txt …]
                [--label-count correctness:0 …] [--state <path>] [--review-base <sha>]

Stdlib-only, C1-clean. `main(argv, *, seams=None)` accepts an optional `seams`
dict so the end-to-end path is unit-testable with every external interaction
injected; production invocation passes no seams (all live defaults).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import converge  # noqa: E402
import review_proof  # noqa: E402


def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="converge.py",
        description="Finalize a structurally-clean review round to two-stable "
                    "[code-review-only] (the Tier-7 reviewed-stable finish).",
    )
    p.add_argument("--base", required=True, help="PR base SHA")
    p.add_argument("--head", required=True, help="current PR head SHA (full)")
    p.add_argument("--pr-url", required=True, dest="pr_url", help="PR URL")
    p.add_argument("--config", required=True, help="path to .three-pillars/config.json")
    p.add_argument("--angle-file", action="append", default=[], dest="angle_file",
                   help="path to a /code-review angle reply (repeatable)")
    p.add_argument("--label-count", action="append", default=[], dest="label_count",
                   help="LABEL:COUNT digest angle-count (repeatable)")
    p.add_argument("--state", default=None,
                   help="path to the (untracked) iterate-state.v1.json")
    p.add_argument("--review-base", default=None, dest="review_base",
                   help="base SHA for the run_round proof re-derivation (default: --base)")
    return p.parse_args(argv)


def main(argv=None, *, seams=None) -> int:
    args = _parse_args(argv)
    try:
        label_counts = converge.parse_label_counts(args.label_count)
    except ValueError as exc:
        sys.stderr.write(f"converge.py: {exc}\n")
        return 2
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"converge.py: could not read config {args.config!r}: {exc}\n")
        return 2

    call_kwargs = dict(
        base=args.base, head=args.head, pr_url=args.pr_url, config=config,
        angle_files=args.angle_file, label_counts=label_counts,
        state_path=args.state, review_base=args.review_base or args.base,
        proof_root=review_proof.default_proof_root(),
    )
    # seams (tests) may override any kwarg incl. proof_root / state_path / out / err.
    call_kwargs.update(seams or {})
    return converge.converge(**call_kwargs)


if __name__ == "__main__":
    sys.exit(main())
