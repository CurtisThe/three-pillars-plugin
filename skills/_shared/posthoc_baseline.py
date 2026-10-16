#!/usr/bin/env python3
"""posthoc_baseline.py — the pinned baseline's row manifest, and the compare that never bends.

design: cheap-tier-local-routing (detailed-design-posthoc.md, Baseline; plan Task 8.2)

    posthoc_baseline.py manifest --root R --until T [--utc-offset ±HH:MM] [--manifest M]
    posthoc_baseline.py check    --root R --until T [--utc-offset ±HH:MM] --manifest M

The scope is `posthoc_rows.load` over every worktree of R, bounded by `--until`, keeping rows
with `role == "task"` whose requested rung (`requested_rung`, else `rung`) is `local-*`. Each is
`{design, line_sha, class}`: `line_sha` is the first 16 hex of the sha256 of the row's canonical
`json.dumps(sort_keys=True)` minus the keys `load` adds (design, measure, ordinal, time,
time_src); `class` is `never-spawned` (outcome `unavailable`, or neither `served_by` nor
`started_at`), else `local` (`served_by == "local"`), else `fallback`; no router join, so a
manifest is stable. `manifest` writes `{roots, per_design, rows}` (rows sorted; `roots` omit
transient `/.tp-scratch/` and `/.claude/worktrees/` checkouts, whose rows are still read) to
`--manifest`, else stdout.

`check` compares by multiset of (design, line_sha, class): a missing row (`missing row: …`) or a
changed class (`reclassified: …`) is exit 1. Printed and never failing: `late rows: n` (in
range, not in the manifest), `drift: <design> manifest=<n> recount=<m>`, `missing root: <path>`
and `recount: …`, all counted from the rows read now. A separated negative `--utc-offset -06:00`
is accepted. Exit 2 on a bad flag, unreadable `--until` or unreadable manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import cheap_ab_state
import posthoc_rows
import scratch_root

NEVER = "never-spawned"
_ADDED = ("design", "measure", "ordinal", "time", "time_src")
_NEEDS = {"design", "line_sha", "class"}


def line_sha(row) -> str:
    raw = {k: v for k, v in row.items() if k not in _ADDED}
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _class(row) -> str:
    if row.get("outcome") == "unavailable" or not (row.get("served_by") or row.get("started_at")):
        return NEVER
    return "local" if row.get("served_by") == "local" else "fallback"


def _keys(rows) -> list[tuple[str, str, str]]:
    """`(design, line_sha, class)` of each baseline-scope row."""
    return [(r["design"], line_sha(r), _class(r)) for r in rows
            if r.get("role") == "task" and str(r.get("requested_rung") or r.get("rung") or "").startswith("local-")]


def manifest(rows, roots) -> dict:
    keys = sorted(_keys(rows))
    kept = {str(r) for r in roots if not scratch_root.is_under_scratch(r)
            and "/.claude/worktrees/" not in f"{Path(r).as_posix()}/"}
    return {"roots": sorted(kept), "per_design": dict(Counter(k[0] for k in keys)),
            "rows": [{"design": d, "line_sha": s, "class": c} for d, s, c in keys]}


def check(rows, recorded) -> int:
    """Print the comparison; 1 for a missing or reclassified row, else 0."""
    keys = _keys(rows)
    have = Counter(keys)
    want = Counter((r["design"], r["line_sha"], r["class"]) for r in recorded["rows"])
    gone, extra, code = want - have, have - want, 0
    for d, s, c in sorted(gone.elements()):
        code = 1
        now = next((e for e in sorted(extra.elements()) if e[:2] == (d, s)), None)
        if now is None:
            print(f"missing row: {d} {s} {c}")
        else:
            extra[now] -= 1
            print(f"reclassified: {d} {s} {c} -> {now[2]}")
    counts, per, was = Counter(k[2] for k in keys), Counter(k[0] for k in keys), recorded["per_design"]
    notes = [f"drift: {d} manifest={was.get(d, 0)} recount={per[d]}" for d in sorted(set(per) | set(was))
             if per[d] != was.get(d, 0)]
    notes += [f"missing root: {r}" for r in recorded["roots"] if not Path(r).is_dir()]
    if (late := sum(n for n in extra.values() if n > 0)) > 0:
        notes.append(f"late rows: {late}")
    print("\n".join(notes + [f"recount: local={counts['local']} fallback={counts['fallback']} "
                             f"{NEVER}={counts[NEVER]} total={len(keys)}"]))
    return code


def _offset(text) -> str:
    if not re.fullmatch(r"[+-]\d{2}:\d{2}", str(text)):
        raise argparse.ArgumentTypeError(f"--utc-offset wants ±HH:MM, got {text!r}")
    return text


def _argv(argv) -> list[str]:
    """Join `--utc-offset V` into `--utc-offset=V`, so a negative offset is not read as a flag."""
    out, args = [], iter(argv)
    for arg in args:
        nxt = next(args, None) if arg == "--utc-offset" else None
        out.append(f"{arg}={nxt}" if nxt is not None else arg)
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="posthoc_baseline.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("manifest", "check"):
        one = sub.add_parser(name)
        one.add_argument("--root", default=".")
        one.add_argument("--until", required=True)
        one.add_argument("--utc-offset", dest="utc_offset", type=_offset, default=None)
        one.add_argument("--manifest", required=name == "check", default=None)
    return parser


def _read(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ok = isinstance(data, dict) and isinstance(data.get("roots"), list) and isinstance(data.get("rows"), list)
    if not (ok and isinstance(data.get("per_design"), dict)
            and all(isinstance(r, dict) and _NEEDS <= r.keys() for r in data["rows"])):
        raise ValueError(f"not a baseline manifest: {path}")
    return data


def main(argv=None, env=None) -> int:
    """`env` (default `os.environ`) is injectable; every bad input returns 2, never raises."""
    try:
        args = _parser().parse_args(_argv(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 2
    try:
        roots = cheap_ab_state.worktree_roots(args.root)
        rows = posthoc_rows.load(args.root, until=args.until, roots=roots, env=env)
        if args.cmd == "check":
            return check(rows, _read(args.manifest))
        text = json.dumps(manifest(rows, roots), indent=2, sort_keys=True) + "\n"
        if args.manifest:
            Path(args.manifest).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (OSError, ValueError) as exc:
        print(f"posthoc_baseline: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
