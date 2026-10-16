"""citation_frozen — frozen-vs-live exemption predicate for invariant cites.

The highest-risk surface of the invariant-citation-coherence checker, isolated
so it can be exhaustively tested in both directions:
  - a false "live" (a frozen cite wrongly classified live) blocks every commit;
  - a false "frozen" (a live cite wrongly exempted) lets rot through.

`is_frozen(rel_path, line, *, in_history, in_fence)` returns True (exempt) iff
ANY of six clauses hold:
  1. path under three-pillars-docs/completed-tp-designs/** or superseded-tp-designs/**;
  2. path under three-pillars-docs/tp-designs/** (in-flight, append-only design logs);
  3. path is a three-pillars-docs/ append-only archive
     (known_issues_resolved.md, known_issues_archive.md, product_roadmap_archive.md,
     architecture_archive.md);
  4. in_history (inside a `## …History…` H2 section) — caller-tracked;
  5. line is a date-prefixed history bullet (leading optional bullet + YYYY-MM-DD);
  6. in_fence (inside a fenced code block) — caller-tracked.

The History-boundary contract is owned by citation_liveness._in_history, which
the caller reuses to set `in_history` (imported, not re-implemented). LIVE_GLOBS
is the positive scan set the scanner iterates.

stdlib-only: re. Reuses citation_liveness._in_history.

design: invariant-citation-coherence

Ships because citation_scan.py / citation_liveness.py import is_frozen as
part of the invariant-cite scan, but that scan itself is a framework-dev
helper (dev-repo only); no-op in user repos — its only meaningful caller,
citation_liveness.run_citation_checks, is reached only from the dev-only
invariant_check.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure _shared/ is on path for sibling imports
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Reuse the History-boundary predicate CODE — do NOT re-implement it.
from citation_liveness import _in_history  # noqa: E402  (re-export for callers)
from certify_issues import COLD_ISSUE_DOCS, LIVE_ISSUE_DOCS  # noqa: E402  (shared tuples)

__all__ = ["is_frozen", "LIVE_GLOBS", "DATE_PREFIX_RE", "_in_history"]

# A date-prefixed history/changelog bullet: optional bullet marker then a
# YYYY-MM-DD date at the very start. Such a line may legitimately cite the
# invariant count of its own day, so it is frozen.
DATE_PREFIX_RE = re.compile(r"^\s*[-*]?\s*\d{4}-\d{2}-\d{2}")

# Path-class prefixes that are always frozen (POSIX-style, repo-relative).
_COMPLETED_PREFIX = "three-pillars-docs/completed-tp-designs/"
_SUPERSEDED_PREFIX = "three-pillars-docs/superseded-tp-designs/"
_TP_DESIGNS_PREFIX = "three-pillars-docs/tp-designs/"
_ARCHIVES = frozenset({
    *COLD_ISSUE_DOCS,  # known_issues_resolved.md, known_issues_archive.md
    "three-pillars-docs/product_roadmap_archive.md",
    "three-pillars-docs/architecture_archive.md",
})

# The positive scan set — the live surfaces the number-cite scan walks. Living
# History sections are excised by the in_history clause, not by the glob.
LIVE_GLOBS: tuple[str, ...] = (
    "SECURITY.md",
    "CLAUDE.md",
    "CLAUDE.plugin.md",
    "README.md",
    "CONTRIBUTING.md",
    "framework-check.sh",
    "skills/**/*.md",
    "skills/**/*.py",
    "skills/**/*.sh",
    "three-pillars-docs/architecture.md",
    "three-pillars-docs/product_roadmap.md",
    *LIVE_ISSUE_DOCS,  # known_issues.md, known_issues_low.md (live ID docs)
)


def _norm(rel_path: str) -> str:
    """Normalize a repo-relative path to forward slashes."""
    return rel_path.replace("\\", "/").lstrip("./")


def is_frozen(rel_path: str, line: str, *, in_history: bool, in_fence: bool) -> bool:
    """True iff the cite on this line is exempt from the live-cite check.

    rel_path is repo-relative (POSIX or native separators accepted). in_history
    and in_fence are tracked by the caller's per-file scan loop (in_history via
    citation_liveness._in_history on each `## ` heading).
    """
    p = _norm(rel_path)

    # Clause 1: completed-/superseded-tp-designs path class.
    if p.startswith(_COMPLETED_PREFIX) or p.startswith(_SUPERSEDED_PREFIX):
        return True
    # Clause 2: in-flight tp-designs design logs (append-only).
    if p.startswith(_TP_DESIGNS_PREFIX):
        return True
    # Clause 3: the append-only doc archives.
    if p in _ARCHIVES:
        return True
    # Clause 4: inside a `## …History…` section.
    if in_history:
        return True
    # Clause 6: inside a fenced code block.
    if in_fence:
        return True
    # Clause 5: a date-prefixed history/changelog bullet.
    if DATE_PREFIX_RE.match(line):
        return True

    return False
