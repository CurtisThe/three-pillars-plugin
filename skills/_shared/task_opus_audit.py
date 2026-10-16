#!/usr/bin/env python3
"""task_opus_audit.py — which plan tasks land on Opus, and why.

design: cheap-tier-offload (Phase 3)

Tests the design assumption that inline-Opus task execution is the dominant task
spend. Two sources, one row each `{design, task, landed, reason, source}`:

- `source: "plan"` — `task_eligibility.corpus_rows` over every
  `three-pillars-docs/completed-tp-designs/*/plan.md`, the rows whose tier is `opus`.
  Since 2026-10-09 only an excluded row (Done / Skipped / Blocked) has that tier, so
  `reason` reads `excluded:<status>`;
- `source: "telemetry"` — the `role: "task"` rows of every design's
  `dispatch-telemetry.ndjson` (live and archived) whose rung is `opus-*` or
  `inline`. `reason` is `ladder:<class>`, the ladder verdict class
  (`failure_class.classify` of the row's outcome and why).

    python3 "$TP_ROOT"/skills/_shared/task_opus_audit.py [--root R] [--grouped]

prints one `counts (N tasks): reason=n, …` line (most common first), then a markdown
table of the rows; `--grouped` prints the design × reason counts instead of one row
per task. Read-only; stdlib-only; no model is ever called here.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import dispatch_log  # noqa: E402 — in-repo, stdlib-only sibling
import failure_class  # noqa: E402 — in-repo, stdlib-only sibling
import task_eligibility  # noqa: E402 — in-repo, stdlib-only sibling

_TREES = ("tp-designs", "completed-tp-designs")


def _plan_rows(root: Path) -> list[dict]:
    pattern = str(root / "three-pillars-docs" / "completed-tp-designs" / "*" / "plan.md")
    rows = task_eligibility.corpus_rows(pattern, exists=lambda p: (root / p).exists())
    return [{"design": r["design"], "task": r["task_id"], "landed": "opus",
             "reason": (r["reasons"] or ["-"])[0], "source": "plan"}
            for r in rows if r["tier"] == "opus"]


def _opus_rung(rung) -> bool:
    return isinstance(rung, str) and (rung.startswith("opus-") or rung == "inline")


def _telemetry_rows(root: Path) -> list[dict]:
    out = []
    for tree in _TREES:
        for path in sorted((root / "three-pillars-docs" / tree).glob(
                f"*/{dispatch_log.NDJSON_NAME}")):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (not isinstance(row, dict) or row.get("role") != "task"
                        or row.get("slot") or not _opus_rung(row.get("rung"))):
                    continue
                klass = failure_class.classify(str(row.get("outcome")),
                                               str(row.get("reason") or ""))
                out.append({"design": path.parent.name, "task": str(row.get("task_id")),
                            "landed": row["rung"], "reason": f"ladder:{klass}",
                            "source": "telemetry"})
    return out


def audit(root) -> list[dict]:
    """The plan rows, then the telemetry rows (see the module docstring)."""
    root = Path(root)
    return _plan_rows(root) + _telemetry_rows(root)


def _counts_line(rows: list[dict]) -> str:
    counts = Counter(r["reason"] for r in rows)
    return (f"counts ({len(rows)} tasks): "
            + (", ".join(f"{k}={v}" for k, v in counts.most_common()) or "none"))


def render(rows: list[dict]) -> str:
    """The counts line, then the markdown table."""
    lines = [_counts_line(rows), "",
             "| design | task | landed | reason | source |", "|---|---|---|---|---|"]
    lines += [f"| {r['design']} | {r['task']} | {r['landed']} | {r['reason']} | {r['source']} |"
              for r in rows]
    return "\n".join(lines)


def render_grouped(rows: list[dict]) -> str:
    """The counts line, then one `| design | reason | tasks |` row per pair, by design
    and then by count (most first)."""
    pairs = Counter((r["design"], r["reason"]) for r in rows)
    lines = [_counts_line(rows), "", "| design | reason | tasks |", "|---|---|---|"]
    lines += [f"| {d} | {r} | {n} |"
              for (d, r), n in sorted(pairs.items(), key=lambda kv: (kv[0][0], -kv[1], kv[0][1]))]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Which plan tasks land on Opus, and why.")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument("--grouped", action="store_true",
                        help="design x reason counts, not one row per task")
    args = parser.parse_args(argv)
    print((render_grouped if args.grouped else render)(audit(args.root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
