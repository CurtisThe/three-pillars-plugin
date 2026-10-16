"""Tests for cheap_ab.summarize / flip_verdict / report over the served-arm dimension.

design: cheap-tier-local-routing 5.2 (detailed-design.md §Interfaces `cheap_ab_served.py`, the
`cheap_ab.summarize` paragraph). `summarize` still pairs by `cheap_ab.arm` (`cheap|opus`); each
complete pair's cheap cell is also rated under `cheap_ab_served.served_arm`, and a pair whose
cheap cell is `fallback` drops from that rating. A slot whose pair asked for a local rung is a
`local_slot`: `flip_verdict` runs every check on its served `local` cell vs `opus`.

Rows are the shapes `dispatch_log.record` writes, held in memory or written under a tmp
`three-pillars-docs/`: nothing reads operator state, the router log or a measure window. The
report is checked through its parsed table cells, never whole-text equality
(skills/_shared/test-fragility.md, fixes 2 and 3).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_ab as ab  # noqa: E402

LOCAL = "local-medium"
SLOT = "docs_draft"
BARE_KEYS = ("cheap", "opus", "unpaired_on")  # the summary as it was before the served arm


def _row(rung, served_by, ok, *, pair, slot, **extra) -> dict:
    row = {"role": "drafter", "slot": slot, "rung": rung, "oracle": "pass" if ok else "fail",
           "tokens": 1000, "ab_pair": pair, **extra}
    return row if served_by is None else {**row, "served_by": served_by}


def _cheap(kind, ok, pair, slot) -> dict:
    """The cheap row of one pair, by how it was served."""
    asked = {"requested_rung": LOCAL}
    if kind == "local":
        return _row(LOCAL, "local", ok, pair=pair, slot=slot, **asked)
    if kind == "mirror":
        return _row("sonnet-medium", "sonnet", ok, pair=pair, slot=slot, fallback="local-busy",
                    **asked)
    if kind == "never":  # the local spawn never happened: the served arm is `fallback`
        return _row(LOCAL, None, ok, pair=pair, slot=slot,
                    fallback="background-spawn-failed", **asked)
    if kind == "legacy-local":  # no requested_rung: the rung itself asked for local
        return _row(LOCAL, "local", ok, pair=pair, slot=slot)
    if kind == "legacy":  # a pre-served_by Sonnet row
        return _row("sonnet-medium", None, ok, pair=pair, slot=slot)
    return _row("sonnet-medium", "sonnet", ok, pair=pair, slot=slot)  # a deliberate Sonnet slot


def _pairs(*specs, slot=SLOT) -> list[dict]:
    """One `cheap|opus` pair per `(cheap kind, cheap passed, opus passed)`."""
    rows = []
    for i, (kind, cheap_ok, opus_ok) in enumerate(specs):
        rows += [_cheap(kind, cheap_ok, f"p{i}", slot),
                 _row("opus-medium", "opus", opus_ok, pair=f"p{i}", slot=slot)]
    return rows


def _bare(summary: dict) -> dict:
    return {slot: {k: s[k] for k in BARE_KEYS} for slot, s in summary.items()}


def _served(cells: dict) -> dict:
    return {a: (c["n"], c["pass"]) for a, c in cells.items() if isinstance(c, dict)}


# --- summarize: the served-arm dimension --------------------------------------------------


def test_summarize_keeps_the_cheap_opus_pairing_and_rates_cheap_cells_by_served_arm():
    rows = _pairs(("local", True, True), ("local", False, True), ("mirror", True, True))
    s = ab.summarize(rows)[SLOT]
    assert (s["cheap"]["n"], s["cheap"]["pass"]) == (3, 2)  # the cheap|opus cells as today
    assert (s["opus"]["n"], s["opus"]["pass"]) == (3, 3)
    assert _served(s["served"]) == {"local": (2, 1), "sonnet-mirror": (1, 1), "opus": (2, 2)}
    assert s["local_slot"] is True  # so `opus` holds only the local-served pairs' opus halves


def test_a_fallback_cheap_cell_drops_from_the_served_rating_only():
    s = ab.summarize(_pairs(("local", True, True), ("never", False, True)))[SLOT]
    assert (s["cheap"]["n"], s["opus"]["n"]) == (2, 2)  # still counted in the cheap|opus cells
    assert "fallback" not in s["served"]
    assert _served(s["served"]) == {"local": (1, 1), "opus": (1, 1)}  # the whole pair left


LOCAL_SLOT = [
    ("deliberate-sonnet", _pairs(("sonnet", True, True)), False),
    ("legacy-sonnet", _pairs(("legacy", True, True)), False),
    ("requested-local", _pairs(("local", True, True)), True),
    ("legacy-local-rung", _pairs(("legacy-local", True, True)), True),
    ("busy-mirror", _pairs(("mirror", True, True)), True),
    ("dropped-pair", _pairs(("never", False, True)), True),
]


@pytest.mark.parametrize("rows,expected", [c[1:] for c in LOCAL_SLOT],
                         ids=[c[0] for c in LOCAL_SLOT])
def test_local_slot_marks_a_slot_whose_pair_member_asked_for_a_local_rung(rows, expected):
    assert ab.summarize(rows)[SLOT]["local_slot"] is expected


def test_an_unpaired_local_row_is_not_a_pair_member():
    plain = {**_cheap("local", True, "p0", SLOT), "ab_pair": None}
    s = ab.summarize([plain])[SLOT]
    assert s["unpaired_on"] == 1 and not s.get("local_slot")


# --- flip_verdict: the local-slot rule ----------------------------------------------------

# (id, pairs, the verdict on the served local cell, the verdict the cheap cell alone gives)
LOCAL_RULE = [
    ("insufficient-local-n",
     [("local", True, True), ("mirror", True, True), ("mirror", True, True)],
     "insufficient", "flip"),
    ("no-baseline-hold",
     [("local", True, False), ("local", True, False), ("never", False, True),
      ("never", False, True)],
     "hold", "flip"),
    ("lower-rate-hold",
     [("local", True, True), ("local", False, True), ("mirror", True, False),
      ("mirror", True, False)],
     "hold", "flip"),
    ("a-fallback-is-not-held-against-local",
     [("local", True, True), ("local", True, True), ("never", False, True)],
     "flip", "hold"),
    ("flip", [("local", True, True), ("local", True, True)], "flip", "flip"),
]


@pytest.mark.parametrize("specs,local,cheap_only", [c[1:] for c in LOCAL_RULE],
                         ids=[c[0] for c in LOCAL_RULE])
def test_a_local_slot_runs_every_check_on_its_served_local_cell(specs, local, cheap_only):
    summary = ab.summarize(_pairs(*specs))
    assert summary[SLOT]["local_slot"] is True
    assert ab.flip_verdict(summary, SLOT)[0] == local
    assert ab.flip_verdict(_bare(summary), SLOT)[0] == cheap_only  # the rule decided it


def test_mirror_pairs_do_not_move_the_local_flip_verdict():
    # local 1/2 vs opus 2/2 on the pairs the local arm served: hold. Busy-GPU pairs (the
    # Sonnet mirror served, opus failed) must not drag the opus baseline down to a flip.
    local_only = _pairs(("local", True, True), ("local", False, True))
    mixed = _pairs(("local", True, True), ("local", False, True), ("mirror", False, False),
                   ("mirror", False, False), ("mirror", False, False))
    for rows in (local_only, mixed):
        assert ab.flip_verdict(ab.summarize(rows), SLOT)[0] == "hold"


NON_LOCAL = [
    ("insufficient", [("sonnet", True, True)]),
    ("lower-rate-hold", [("sonnet", True, True), ("sonnet", False, True)]),
    ("no-baseline-hold", [("sonnet", True, False), ("sonnet", True, False)]),
    ("flip", [("sonnet", True, True), ("sonnet", True, True)]),
    ("legacy-rows-without-served-by", [("legacy", True, True), ("legacy", True, True)]),
]


@pytest.mark.parametrize("specs", [c[1] for c in NON_LOCAL], ids=[c[0] for c in NON_LOCAL])
def test_a_non_local_slot_verdict_is_unchanged_by_the_served_dimension(specs):
    summary = ab.summarize(_pairs(*specs))
    assert not summary[SLOT]["local_slot"]
    assert ab.flip_verdict(summary, SLOT) == ab.flip_verdict(_bare(summary), SLOT)


def test_a_review_prep_slot_still_delegates_when_its_prep_arm_is_local():
    findings = {"n": 1, "classes": [["a.py", "A"]]}

    def rp(pr, ab_arm, rung, served_by, tokens):
        return _row(rung, served_by, True, pair=f"rp:{pr}:1:s{pr}", slot="review_slice",
                    ab_arm=ab_arm, shape=f"s{pr}", findings=findings, tokens=tokens)

    rows = [rp(12, "base", "opus-medium", "opus", 100), rp(12, "prep", LOCAL, "local", 80),
            rp(13, "base", "opus-medium", "opus", 200), rp(13, "prep", LOCAL, "local", 150)]
    summary = ab.summarize(rows)
    assert summary["review_slice"]["local_slot"] is True
    assert ab.flip_verdict(summary, "review_slice", rows) == ab.review_prep_verdict(
        rows, "review_slice")
    assert ab.flip_verdict(summary, "task")[0] == "exempt"


# --- report: the served-arm, fallback and reach tables ------------------------------------


def _write(root: Path, rows: list[dict]) -> None:
    path = root / "three-pillars-docs" / "tp-designs" / "d" / "dispatch-telemetry.ndjson"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _cells(text: str) -> list[list[str]]:
    """The data rows of every markdown table in `text`, split into stripped cells."""
    return [[c.strip() for c in line.strip("|").split("|")] for line in text.splitlines()
            if line.startswith("|") and not set(line) <= set("|- ")]


def test_report_rates_a_local_slot_on_its_local_cell_and_appends_the_tables(tmp_path):
    _write(tmp_path, _pairs(("local", True, False), ("local", False, True),
                            ("mirror", True, True), ("mirror", True, True),
                            ("never", False, True)))
    main, _, appended = ab.report(tmp_path).partition("\n\n")
    row = next(c for c in _cells(main) if c[0] == SLOT)
    assert row[-1].split()[0] == "flip"  # local 0.50 vs opus 0.50 on the same two pairs
    # (cheap alone is 0.60 vs 0.80, a hold: the served local cell decided it)
    cells = _cells(appended)
    assert [SLOT, "local", "2", "1", "0.50"] in cells
    assert [SLOT, "sonnet-mirror", "2", "2", "1.00"] in cells
    assert [SLOT, "opus", "2", "1", "0.50"] in cells  # the local-served pairs' opus halves only
    assert [SLOT, "local-busy", "2"] in cells
    assert [SLOT, "background-spawn-failed", "1"] in cells  # the dropped pair shows here
    assert [SLOT, "organic", "5", "2", "0.40"] in cells


def test_report_fallback_table_lists_local_requests_only(tmp_path):
    _write(tmp_path, _pairs(("legacy", True, True)) + _pairs(("never", False, True),
                                                               slot="handoff"))
    appended = ab.report(tmp_path).partition("\n\n")[2]
    cells = _cells(appended)
    assert ["handoff", "background-spawn-failed", "1"] in cells
    assert not [c for c in cells if c[0] == SLOT]  # a non-local row is no local fallback
