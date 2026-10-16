"""handoffs_ignore.py — .gitignore rules for .handoffs/ bundles vs worklists.

The round-bundle JSON under every design's ``.handoffs/`` is never committed,
but the cold-resume worklists (the ``.md`` files ``/tp-run-full-design``
commits) stay tracked. So each root needs a pair: ignore everything under
``.handoffs/`` and re-include the ``.md`` files. Both roots are needed because
``/tp-design-complete``'s ``git mv`` carries the bundles into
``completed-tp-designs/{name}/.handoffs/``.

`check` exits 0 when all four rules are present in the repo-root .gitignore,
1 otherwise (a missing .gitignore counts as rules missing). `apply` appends
the missing rules under one comment (idempotent), creating the file when
absent, and prints exactly the lines it adds.

CLI: `handoffs_ignore.py check|apply [--root DIR]` (default root = cwd's git
top-level, or cwd when not in a repo). Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

COMMENT = (
    "# .handoffs/ holds the round-bundle JSON that is never committed, but the\n"
    "# cold-resume worklists (the .md files that tp-run-full-design commits) stay\n"
    "# tracked: ignore the bundle and re-include the *.md worklist. Both roots —\n"
    "# design-complete's `git mv` carries the bundles into completed-tp-designs/."
)
RULES = (
    "three-pillars-docs/tp-designs/*/.handoffs/*",
    "!three-pillars-docs/tp-designs/*/.handoffs/*.md",
    "three-pillars-docs/completed-tp-designs/*/.handoffs/*",
    "!three-pillars-docs/completed-tp-designs/*/.handoffs/*.md",
)


def default_root(cwd: str | None = None) -> Path:
    """The default root: cwd's git top-level, or cwd when not in a repo."""
    cwd = Path(cwd or os.getcwd())
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return cwd
    return Path(r.stdout.strip())


def _gitignore(root: Path) -> Path:
    return root / ".gitignore"


def _present(root: Path) -> set[str]:
    path = _gitignore(root)
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}


def check(root: Path | str) -> bool:
    """True when all four rules are present in the root's .gitignore."""
    return all(rule in _present(Path(root)) for rule in RULES)


def apply(root: Path | str) -> list[str]:
    """Append the missing rules under the comment; return the lines added.

    Creates the .gitignore when absent."""
    root = Path(root)
    missing = [r for r in RULES if r not in _present(root)]
    if not missing:
        return []
    path = _gitignore(root)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + COMMENT + "\n" + "\n".join(missing) + "\n",
                     encoding="utf-8")
    return missing


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=".gitignore rules for .handoffs/ bundles vs worklists")
    ap.add_argument("action", choices=["check", "apply"])
    ap.add_argument("--root", default=None,
                    help="repo root (default: cwd's git top-level, or cwd)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else default_root()
    if args.action == "check":
        return 0 if check(root) else 1
    for line in apply(root):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
