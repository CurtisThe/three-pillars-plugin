"""converge_cli.py — argparse `main()` for the converge.py primitive.

Split from converge.py (which carries the core `converge()` orchestration) so
neither file nears the file-size cap. The CLI shape is:

    converge.py --base <sha> --head <sha> --pr-url <url> --config <path>
                --angle-file r1.txt [--angle-file r2.txt …]
                [--label-count correctness:0 …] [--state <path>] [--review-base <sha>]
    converge.py --round-dir R --config <path> [--state <path>] [--class-log-path <path>]

`--round-dir` (converge_rounddir) takes base/head/PR url and every path from the
round manifest. The legacy `--angle-file` form refuses when the config declares
custom `review.angles` (their confirmer rule needs the manifest).

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
import converge_rounddir  # noqa: E402
import review_proof  # noqa: E402
import ready_ping  # noqa: E402 — skills/_shared, on sys.path via converge's shim


def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="converge.py",
        description="Finalize a structurally-clean review round to two-stable "
                    "[code-review-only] (the Tier-7 reviewed-stable finish).",
    )
    p.add_argument("--base", help="PR base SHA")
    p.add_argument("--head", help="current PR head SHA (full)")
    p.add_argument("--pr-url", dest="pr_url", help="PR URL")
    p.add_argument("--config", required=True, help="path to .three-pillars/config.json")
    p.add_argument("--angle-file", action="append", default=[], dest="angle_file",
                   help="path to a /code-review angle reply (repeatable)")
    p.add_argument("--label-count", action="append", default=[], dest="label_count",
                   help="LABEL:COUNT digest angle-count (repeatable)")
    p.add_argument("--state", default=None,
                   help="path to the (untracked) iterate-state.v1.json")
    p.add_argument("--review-base", default=None, dest="review_base",
                   help="base SHA for the run_round proof re-derivation (default: --base)")
    p.add_argument("--round-dir", default=None, dest="round_dir",
                   help="round dir whose angles.json manifest is the path authority")
    p.add_argument("--class-log-path", default=None, dest="class_log_path",
                   help="(--round-dir) where run_round appends the per-round class line")
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
    # Production (no seams) wires the ready-ping on every path, round-dir first.
    if seams is None:
        seams = {"ready_ping_fn": ready_ping.ping_ready}
    if args.round_dir:
        return converge_rounddir.run(args.round_dir, config=config, state_arg=args.state,
                                     class_log_path=args.class_log_path, seams=seams)
    err = (seams or {}).get("err") or sys.stderr
    if not (args.base and args.head and args.pr_url):
        err.write("converge.py: --base, --head and --pr-url are required "
                         "without --round-dir\n")
        return 2
    if isinstance(config, dict) and (config.get("review") or {}).get("angles"):
        err.write("converge.py: config declares custom review.angles — use "
                         "--round-dir (the confirmer rule needs the manifest)\n")
        return 2

    call_kwargs = dict(
        base=args.base, head=args.head, pr_url=args.pr_url, config=config,
        angle_files=args.angle_file, label_counts=label_counts,
        state_path=args.state, review_base=args.review_base or args.base,
        proof_root=review_proof.default_proof_root(),
    )
    # seams is always a dict here (production wires the ping above; tests pass
    # their own and expect nothing extra wired).
    call_kwargs.update(seams)
    return converge.converge(**call_kwargs)


if __name__ == "__main__":
    sys.exit(main())
