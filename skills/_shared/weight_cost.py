#!/usr/bin/env python3
"""Per-weight-class token cost — measured median or static estimate.

design: weight-class-lean-default (Task 1.3, Behavior 3)

Reads each completed design's ``decisions.md`` for its last ``[cache]`` line
(the shape ``cache_measure.py`` emits), sums every segment's ``read=`` and
``write=`` (M tokens), groups by ``weight_class.read_class`` and takes the
median per class. With fewer than ``MIN_SAMPLES`` measured designs a class
shows the static estimate (seeded from this repo's measured medians).
"""
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weight_class import read_class  # noqa: E402

MIN_SAMPLES = 3
CLASSES = ("just-do-it", "light", "full")
STATIC_MTOK = {"just-do-it": 34.0, "light": 86.0, "full": 168.0}
SPIKE_ROW = "spike  no figure (experiment)"
_SEG_RE = re.compile(r"\b(?:read|write)=([0-9]+(?:\.[0-9]+)?)M")


def _design_total(decisions: Path):
    """Summed read+write (Mtok) of the file's last ``[cache]`` line, or None."""
    try:
        lines = decisions.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    cache = [ln for ln in lines if ln.startswith("[cache] ")]
    if not cache:
        return None
    return sum(float(x) for x in _SEG_RE.findall(cache[-1]))


def measured(root: Path) -> dict:
    """``{class: [Mtok totals]}`` over completed designs carrying a ``[cache]`` line."""
    base = Path(root) / "three-pillars-docs" / "completed-tp-designs"
    result = {}
    if not base.is_dir():
        return result
    for design in sorted(base.iterdir()):
        if not design.is_dir():
            continue
        total = _design_total(design / "decisions.md")
        if total is None:
            continue
        result.setdefault(read_class(design)[0], []).append(total)
    return result


def cost_table(root) -> str:
    """One line per class: ``<class>  ~<N> Mtok  measured n=<k> | estimate``."""
    data = measured(Path(root))
    rows = []
    for klass in CLASSES:
        vals = data.get(klass, [])
        if len(vals) >= MIN_SAMPLES:
            rows.append(f"{klass}  ~{statistics.median(vals):.1f} Mtok  "
                        f"measured n={len(vals)}")
        else:
            rows.append(f"{klass}  ~{STATIC_MTOK[klass]:.1f} Mtok  estimate")
    rows.append(SPIKE_ROW)
    return "\n".join(rows)


if __name__ == "__main__":
    print(cost_table(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()))
