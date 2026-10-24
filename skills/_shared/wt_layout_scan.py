#!/usr/bin/env python3
"""wt_layout_scan.py — the worktrees-under-wt-only invariant's scanner.

design: worktrees-under-wt-only (Task 1.4)

Scans the shipped surfaces (``skills/`` and ``agents/``) for three literal patterns
that put a checkout under the harness's hidden directory. The input domain is closed:
three regexes over a fixed file set, no prose interpretation.

    wt_layout_scan.py <root-dir> [<root-dir> ...]

Output ``path:line: rule X: <text>`` per hit (path relative to the parent of the roots);
exit 0 clean, 1 on hits, 2 when a root is missing or unreadable. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EXTS = {".md", ".py", ".sh", ".json"}
RULE_A = re.compile(r"""isolation\\?["']?\s*[=:]\s*\\?["']?worktree(?![\w-])""")
RULE_B = re.compile(
    r"""\.claude"\s*\)?\s*/\s*"worktrees|["']\.claude/worktrees|\.claude/worktrees[^"'\s]*["']"""
)
RULE_C = re.compile(r"git worktree add[^\n]*\.claude/worktrees")

# Readers and GC only; relpath (from the repo root) -> reason.
WAIVERS = {
    "skills/_shared/gc_agent_worktrees.py": "reaps harness agent-* worktrees",
    "skills/tp-" + "worktree/scripts/list_worktrees.py": "hides harness agent-* worktrees",
    "skills/_shared/scratch_root.py": "legacy scan",
    "skills/_shared/task_scope.py": "legacy prefix",
    "skills/_shared/posthoc_baseline.py": "filter",
    "skills/_shared/attempt_fixture.py": "simulates the harness agent worktree for guard tests",
    "skills/tp-run-full-design/demos/p1-nested-dispatch-probe.md": "historical spike record",
    "skills/_shared/wt_layout_scan.py": "its own patterns",
}


def _rules_for(path: Path) -> list[tuple[str, re.Pattern]]:
    rules = [("A", RULE_A)]
    if path.suffix in (".py", ".sh"):
        rules.append(("B", RULE_B))
    if path.suffix == ".md":
        rules.append(("C", RULE_C))
    return rules


def _skip(path: Path) -> bool:
    n = path.name
    return path.suffix not in EXTS or n == "conftest.py" or (n.startswith("test_") and n.endswith(".py"))


def scan(roots, base=None):
    """Return a list of (relpath, lineno, rule, text). Raises OSError on a bad root."""
    roots = [Path(r) for r in roots]
    base = Path(base) if base else (roots[0].resolve().parent if roots else Path("."))
    hits = []
    present = [r for r in roots if r.is_dir()]
    if not present:  # a single absent root (e.g. no agents/) is tolerated; none at all is not
        raise OSError(f"unreadable root: {', '.join(map(str, roots)) or '(none)'}")
    for root in present:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or _skip(path):
                continue
            rel = path.resolve().relative_to(base.resolve()).as_posix()
            if rel in WAIVERS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rules = _rules_for(path)
            for i, line in enumerate(text.splitlines(), 1):
                for name, rx in rules:
                    if rx.search(line):
                        hits.append((rel, i, name, line.strip()))
    return hits


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: wt_layout_scan.py <root-dir> ...", file=sys.stderr)
        return 2
    try:
        hits = scan(args)
    except OSError as exc:
        print(f"wt-layout-scan: {exc}", file=sys.stderr)
        return 2
    for rel, line, rule, text in hits:
        print(f"{rel}:{line}: rule {rule}: {text}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
