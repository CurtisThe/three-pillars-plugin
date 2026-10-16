"""forge_callsite_scan.py — find direct `gh` calls outside the forge chokepoint.

design: forge-interface (Task 2.4; invariant 49, advisory)

Every forge-facing call should go through `forge.py`. This scans `.py`, `.sh`
and `.md` files for a direct `gh <subcommand>` (or a `["gh", …` argv literal in
Python) and compares the per-file counts with a committed baseline that only
shrinks. `forge*.py` and `test_*.py` files are exempt.

CLI:
  forge_callsite_scan.py check --baseline FILE [--root DIR] PATH...
  forge_callsite_scan.py emit-baseline --out FILE [--root DIR] PATH...

`check` prints one finding per line and exits 0 even with findings; it exits 2
only when the baseline cannot be read.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path

GH_SUBCOMMANDS = ("pr", "api", "issue", "repo", "auth", "run", "release", "label",
                  "workflow", "search", "secret", "gist", "ruleset", "browse",
                  "status", "cache", "variable", "project")
_SHELL_RX = re.compile(r"(?<![\w./-])gh\s+(?:%s)\b" % "|".join(GH_SUBCOMMANDS))
_PY_RX = re.compile(r"""[\[(]\s*["']gh["']\s*,""")
_SKIP_DIRS = {".git", "__pycache__", ".claude", "node_modules"}
_EXEMPT = ("forge*.py", "test_*.py")
_EXTS = (".py", ".sh", ".md")
HEADER = (
    "# forge-gh-baseline — direct gh call sites outside forge.py (invariant 49, forge-interface).\n"
    "# Only shrinks: regenerate with forge_callsite_scan.py emit-baseline; never hand-raise a count.\n"
)


def _files(paths):
    for arg in paths:
        p = Path(arg)
        if p.is_dir():
            for dirpath, dirs, names in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
                for n in sorted(names):
                    yield Path(dirpath) / n
        elif p.is_file():
            yield p


def _count(path):
    rx = _PY_RX if path.suffix == ".py" else _SHELL_RX
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    return sum(1 for line in text.splitlines() if rx.search(line))


def scan(paths, root):
    """Map POSIX path (relative to `root`) -> direct gh call count, files with >0 only."""
    root_p = Path(root).resolve()
    out = {}
    for f in _files(paths):
        if f.suffix not in _EXTS or any(fnmatch.fnmatch(f.name, g) for g in _EXEMPT):
            continue
        n = _count(f)
        if n:
            try:
                rel = f.resolve().relative_to(root_p).as_posix()
            except ValueError:
                rel = f.as_posix()
            out[rel] = n
    return out


def read_baseline(path):
    """Parse `path count` lines; raises OSError/ValueError on missing or malformed."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.rsplit(None, 1)
            if len(parts) != 2 or not parts[1].isdigit():
                raise ValueError("%s:%d: malformed baseline line" % (path, no))
            out[parts[0]] = int(parts[1])
    return out


def check(paths, baseline, root):
    found = scan(paths, root)
    msgs = []
    for path in sorted(set(found) | set(baseline)):
        n, b = found.get(path, 0), baseline.get(path)
        if b is None:
            msgs.append("%s: %d direct gh call(s) outside forge.py and the baseline" % (path, n))
        elif n > b:
            msgs.append("%s: %d direct gh call(s), baseline %d (growth — route new calls "
                        "through forge.py)" % (path, n, b))
        elif n < b:
            msgs.append("%s: %d direct gh call(s), baseline %d (stale — shrink the baseline)"
                        % (path, n, b))
    return msgs


def emit_baseline(paths, out, root):
    counts = scan(paths, root)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(HEADER)
        for path in sorted(counts):
            fh.write("%s %d\n" % (path, counts[path]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forge_callsite_scan.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--baseline", required=True)
    e = sub.add_parser("emit-baseline")
    e.add_argument("--out", required=True)
    for p in (c, e):
        p.add_argument("--root", default=".")
        p.add_argument("paths", nargs="+")
    try:
        args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.cmd == "emit-baseline":
        return emit_baseline(args.paths, args.out, args.root)
    try:
        baseline = read_baseline(args.baseline)
    except (OSError, ValueError) as exc:
        print("forge_callsite_scan: cannot read baseline: %s" % exc, file=sys.stderr)
        return 2
    for line in check(args.paths, baseline, args.root):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
