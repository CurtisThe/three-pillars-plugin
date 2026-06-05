"""verify_learn.py — learn-verification: do as-built retired/renamed symbols
still appear in the living + archived docs?

"learn ran" != "docs match as-built". After a design ships, /tp-design-learn (and
/tp-spike-learn) should have scrubbed retired mechanisms from the docs; this helper
catches the residue. It is a deterministic, re-runnable, ADVISORY diff-grep:

  retired_identifiers(diff)  → the set of symbols/files a diff *removed*
  scan_docs(repo, identifiers) → every three-pillars-docs/** line that still names
                                 one of those retired identifiers (a StaleRef)

`main()` ALWAYS exits 0 (advisory, never a gate) and every function fails open
(any error → empty), so a grep heuristic can never hard-block on a historical-doc
mention. The HARD enforcement is framework-check.sh invariant #27; this is the
soft, propagation-quality check (Q3).

Range note: callers pass `--range {default}...tp/{slug}` so `git diff` surfaces the
DESIGN BRANCH's deletions (merge-base → tp/slug). The detailed-design literal wrote
`tp/{slug}...{default}`, which diffs merge-base → {default} and would surface the
WRONG side (empty when {default} hasn't advanced); corrected per intent. main()
itself is range-agnostic — it passes the string straight to `git diff`.

Design refs:
  - three-pillars-docs/tp-designs/merged-design-closeout/detailed-design.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DOCS_SUBDIR = "three-pillars-docs"

# Removed-line (-) identifier forms. Concrete (audit fix): Python def/class,
# shell `function name` / `name() {`, module-level UPPER_SNAKE const.
_RULES = (
    re.compile(r"^-\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),      # python def
    re.compile(r"^-\s*class\s+([A-Za-z_]\w*)"),                  # python class
    re.compile(r"^-\s*function\s+([A-Za-z_]\w*)"),              # shell `function name`
    re.compile(r"^-\s*([A-Za-z_]\w*)\s*\(\)\s*\{?\s*$"),       # shell `name() {`
    re.compile(r"^-\s*([A-Z][A-Z0-9_]+)\s*=(?!=)"),            # UPPER_SNAKE const
)
_DELFILE_RE = re.compile(r"^---\s+a/(.+?)\s*$")
_RENAME_RE = re.compile(r"^rename from\s+(.+?)\s*$")


def retired_identifiers(diff_text) -> set[str]:
    """Symbols/files a unified diff REMOVED. Renames reduce to the deleted old
    name (the - side). Additions (+) are never extracted. Fail-open → set()."""
    ids: set[str] = set()
    try:
        lines = diff_text.splitlines()
        for i, line in enumerate(lines):
            # Deleted file: '--- a/path' immediately followed by '+++ /dev/null'.
            m = _DELFILE_RE.match(line)
            if m:
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ /dev/null"):
                    ids.add(Path(m.group(1)).name)
                continue  # never treat a ---/+++ header as a removed symbol line
            if line.startswith("+++"):
                continue
            r = _RENAME_RE.match(line)
            if r:
                ids.add(Path(r.group(1)).name)
                continue
            if not line.startswith("-"):
                continue
            for rx in _RULES:
                mm = rx.match(line)
                if mm:
                    ids.add(mm.group(1))
                    break
    except Exception:
        return set()  # fail-open: advisory check must never raise
    return ids


@dataclass
class StaleRef:
    """A doc line that still names a retired identifier."""

    doc: str          # path relative to repo_root
    line: int         # 1-based
    identifier: str


def scan_docs(repo_root, identifiers) -> list[StaleRef]:
    """Every three-pillars-docs/** line (living + completed-tp-designs/) that still
    names a retired identifier, whole-word. Fail-open → partial/empty, never raises."""
    if not identifiers:
        return []
    root = Path(repo_root)
    docs_root = root / DOCS_SUBDIR
    refs: list[StaleRef] = []
    # whole-word patterns (sorted for deterministic output) — substring matches
    # like "foo" inside "foobar" are excluded to cut false positives.
    patterns = [(ident, re.compile(r"\b" + re.escape(ident) + r"\b")) for ident in sorted(identifiers)]
    try:
        if not docs_root.is_dir():
            return []
        for path in sorted(docs_root.rglob("*.md")):
            try:
                text = path.read_text(errors="replace")
                rel = str(path.relative_to(root))
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for ident, rx in patterns:
                    if rx.search(line):
                        refs.append(StaleRef(doc=rel, line=lineno, identifier=ident))
    except OSError:
        return refs  # fail-open with whatever was gathered
    return refs


def _read_diff(repo_root, rng) -> str:
    """Diff text from `git diff <range>` (range-agnostic) or stdin. Fail-open → ''."""
    if rng:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_root), "diff", rng],
                capture_output=True, text=True,
            )
            return out.stdout
        except Exception:
            return ""
    try:
        return sys.stdin.read()
    except Exception:
        return ""


def main(argv=None) -> int:
    """CLI. ALWAYS returns 0 (advisory). Prints stale doc refs (--json or
    `doc:line: identifier`). Fail-open on every error."""
    parser = argparse.ArgumentParser(
        description="Learn-verification: as-built retired symbols still named in three-pillars-docs/."
    )
    parser.add_argument("--repo", default=".", help="repo root (default: cwd)")
    parser.add_argument(
        "--range",
        dest="rng",
        default=None,
        metavar="A...B",
        help="git diff range; callers pass {default}...tp/{slug}. Omit to read a diff from stdin.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON")
    args = parser.parse_args(argv)
    try:
        identifiers = retired_identifiers(_read_diff(args.repo, args.rng))
        refs = scan_docs(args.repo, identifiers)
        if args.as_json:
            print(json.dumps([asdict(r) for r in refs]))
        else:
            for r in refs:
                print(f"{r.doc}:{r.line}: {r.identifier}")
    except Exception:
        pass  # advisory: never a gate
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
