"""The `Just-do-it` column of the per-slot budget table (task 1.10).

Parsed structure, never prose: the markdown table under `## Per-slot budget table`
in `skills/tp-run-full-design/SKILL.md` gains a `Just-do-it` column. Every slot row
carries a cell in it, the slots the mapping skips say `—`, and no just-do-it budget
sits above its light counterpart (the class is cheaper, never dearer).

Run with: pytest skills/tp-run-full-design/scripts/test_budget_table_jdi.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

HEADING = "## Per-slot budget table"
JDI = "Just-do-it"
SKIPPED = ("design", "detail", "design-audit", "plan", "plan-audit", "certifier")
DASH = "—"
SIZE = re.compile(r"^(\d+)k$")


def _section() -> str:
    text = skill_text.read_skill_text("tp-run-full-design")
    body = text.split(f"\n{HEADING}", 1)[1].split("\n## ", 1)[0]
    return body.split("\n### ", 1)[0]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table() -> tuple[list[str], dict[str, list[str]]]:
    """The table's header cells and its rows keyed by their first backticked slot."""
    rows = [ln for ln in _section().splitlines() if ln.strip().startswith("|")]
    header = _cells(rows[0])
    keyed: dict[str, list[str]] = {}
    for line in rows[1:]:
        cells = _cells(line)
        if set("".join(cells)) <= set("-: "):
            continue
        name = re.findall(r"`([^`\s]+)`", cells[0])
        assert name, f"budget row names no slot: {line!r}"
        keyed[name[0]] = cells
    return header, keyed


def _column(header: list[str], rows: dict[str, list[str]], label: str) -> dict[str, str]:
    idx = header.index(label)
    return {slot: cells[idx] for slot, cells in rows.items()}


def test_budget_table_has_a_just_do_it_column():
    header, rows = _table()
    assert JDI in header, header
    for slot, cells in rows.items():
        assert len(cells) == len(header), f"{slot}: ragged row {cells}"


def test_every_slot_row_has_a_just_do_it_cell():
    header, rows = _table()
    jdi = _column(header, rows, JDI)
    for slot in rows:
        assert jdi[slot], f"{slot}: empty Just-do-it cell"
    assert set(SKIPPED) <= set(rows), set(SKIPPED) - set(rows)
    for slot in SKIPPED:
        assert jdi[slot] == DASH, f"{slot}: expected {DASH}, got {jdi[slot]!r}"


def test_no_just_do_it_budget_is_above_light():
    """Both cells a plain `Nk` size: the just-do-it figure never exceeds light's."""
    header, rows = _table()
    jdi, light = _column(header, rows, JDI), _column(header, rows, "Light")
    compared = 0
    for slot in rows:
        a, b = SIZE.match(jdi[slot]), SIZE.match(light[slot])
        if not (a and b):
            continue
        compared += 1
        assert int(a.group(1)) <= int(b.group(1)), f"{slot}: {jdi[slot]} > {light[slot]}"
    assert compared >= 4, f"too few comparable cells: {compared}"
