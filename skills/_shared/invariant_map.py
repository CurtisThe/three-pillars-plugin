"""invariant_map — canonical invariant map parsed from framework-check.sh headers.

Single source of truth for the invariant enumeration: parses the top-level
`# N. <title>` headers out of framework-check.sh into a `dict[int, Invariant]`.
There is NO json sidecar — retirement is expressed purely by a header marker
`# N. [RETIRED] <title>`. `active_count()` counts non-retired headers;
`valid_numbers()` includes retired numbers (so a cite of a retired number is
in-range-but-retired, reportable with its status).

stdlib-only: re, pathlib, dataclasses.

design: invariant-citation-coherence
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A top-level invariant header in framework-check.sh:
#   "# 12. Some title ..."
# A retirement marker sits immediately after the number/dot:
#   "# 12. [RETIRED] Some title ..."
INVARIANT_HEADER_RE = re.compile(r"^# (?P<n>\d+)\. (?P<title>.+)$")
_RETIRED_RE = re.compile(r"^# (?P<n>\d+)\. \[RETIRED\]")


@dataclass
class Invariant:
    number: int
    title: str
    status: str  # "active" | "retired"


def parse_invariant_map(framework_check_path) -> dict[int, Invariant]:
    """Parse `# N. <title>` headers from framework-check.sh into the canonical map.

    Derived from headers ONLY — no sidecar. A `[RETIRED]` marker after the
    number/dot sets status="retired", else "active". On a duplicate number the
    last header wins (headers are unique in practice).
    """
    path = Path(framework_check_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    result: dict[int, Invariant] = {}
    for line in text.splitlines():
        m = INVARIANT_HEADER_RE.match(line)
        if not m:
            continue
        number = int(m.group("n"))
        is_retired = bool(_RETIRED_RE.match(line))
        title = m.group("title").strip()
        status = "retired" if is_retired else "active"
        if is_retired:
            # Strip the leading "[RETIRED]" marker from the stored title.
            title = title[len("[RETIRED]"):].strip()
        result[number] = Invariant(number=number, title=title, status=status)
    return result


def active_count(m: dict[int, Invariant]) -> int:
    """Count of non-retired invariants (the number the banner reports)."""
    return sum(1 for inv in m.values() if inv.status != "retired")


def valid_numbers(m: dict[int, Invariant]) -> set[int]:
    """All header numbers, including retired (the in-range set for cite checks)."""
    return set(m.keys())
