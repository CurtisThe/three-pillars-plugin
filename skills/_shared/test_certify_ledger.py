"""test_certify_ledger.py — design-dir resolution and the sweep coherence state.

design: audit-pass-does-not-bind (Task 9.3; detailed-design.md §Interfaces [F10][R1], N2, N6).

`resolve_design_dir(root, slug)` finds the in-flight design dir first, then the
archived one, else raises `FileNotFoundError`. `coherence_state(root, slug)`
maps (ledger present?, open "sweep ledger pending" entry?) onto `certified` /
`pending` / `stale-pending` / `missing`; an unresolvable slug is `missing` (N6).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import certify_ledger  # noqa: E402

SLUG = "demo-design"
DOCS = Path("three-pillars-docs")
HEADING = f"### M7: sweep ledger pending — {SLUG} B13/B15 await post-merge certify-sweep"


def _design(root: Path, where: str) -> Path:
    d = root / DOCS / where / SLUG
    d.mkdir(parents=True)
    return d


def _issues(root: Path, open_text: str = "", resolved_text: str = "") -> None:
    (root / DOCS).mkdir(parents=True, exist_ok=True)
    (root / DOCS / "known_issues.md").write_text(
        f"# Known issues\n\n## Medium\n\n{open_text}\n### M1: other\n\n## Low\n", encoding="utf-8")
    (root / DOCS / "known_issues_resolved.md").write_text(
        f"# Resolved\n\n{resolved_text}\n", encoding="utf-8")


def test_resolve_prefers_in_flight(tmp_path):
    archived = _design(tmp_path, "completed-tp-designs")
    in_flight = _design(tmp_path, "tp-designs")
    assert certify_ledger.resolve_design_dir(tmp_path, SLUG) == in_flight
    in_flight.rmdir()
    assert certify_ledger.resolve_design_dir(tmp_path, SLUG) == archived


def test_resolve_raises_when_neither_exists(tmp_path):
    with pytest.raises(FileNotFoundError, match=SLUG):
        certify_ledger.resolve_design_dir(tmp_path, SLUG)


def test_resolve_ignores_a_plain_file(tmp_path):
    (tmp_path / DOCS / "tp-designs").mkdir(parents=True)
    (tmp_path / DOCS / "tp-designs" / SLUG).write_text("not a dir", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        certify_ledger.resolve_design_dir(tmp_path, SLUG)


def test_state_certified(tmp_path):
    d = _design(tmp_path, "completed-tp-designs")
    (d / certify_ledger.LEDGER_NAME).write_text("# ledger\n", encoding="utf-8")
    _issues(tmp_path)
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "certified"


def test_state_pending(tmp_path):
    _design(tmp_path, "tp-designs")
    _issues(tmp_path, open_text=HEADING + "\n\nbody\n")
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "pending"
    assert certify_ledger.open_pending_heading(tmp_path, SLUG) == HEADING.lstrip("# ")


def test_state_stale_pending(tmp_path):
    d = _design(tmp_path, "tp-designs")
    (d / certify_ledger.LEDGER_NAME).write_text("# ledger\n", encoding="utf-8")
    _issues(tmp_path, open_text=HEADING + "\n")
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "stale-pending"


def test_state_missing(tmp_path):
    _design(tmp_path, "tp-designs")
    _issues(tmp_path)
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "missing"


def test_pending_entry_only_in_the_resolved_archive_is_not_open(tmp_path):
    _design(tmp_path, "tp-designs")
    _issues(tmp_path, resolved_text=HEADING.replace("M7:", "M7 (RESOLVED 2026-10-01):") + "\n")
    assert certify_ledger.open_pending_heading(tmp_path, SLUG) is None
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "missing"


def test_unresolvable_slug_is_missing_not_an_exception(tmp_path):
    """N6: resolve_design_dir raising maps to `missing`, even with an open entry."""
    _issues(tmp_path, open_text=HEADING + "\n")
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "missing"


@pytest.mark.parametrize("line", [
    f"#### M7: sweep ledger pending — {SLUG}",          # not an ### heading
    f"sweep ledger pending — {SLUG} in prose",           # not a heading at all
    "### M7: sweep ledger pending — some-other-design",  # another slug
    f"### M7: ledger for {SLUG} is pending",             # not the literal phrase
])
def test_open_entry_needs_an_h3_heading_with_the_phrase_and_the_slug(tmp_path, line):
    _design(tmp_path, "tp-designs")
    _issues(tmp_path, open_text=line + "\n")
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "missing"


def test_absent_known_issues_file_means_no_open_entry(tmp_path):
    _design(tmp_path, "tp-designs")
    assert certify_ledger.coherence_state(tmp_path, SLUG) == "missing"


def test_design_dir_cli_prints_the_resolved_dir(tmp_path, capsys):
    """10.3 (P10): the runbook resolves `D` through `certify_ledger.py design-dir`."""
    archived = _design(tmp_path, "completed-tp-designs")
    assert certify_ledger.main(["design-dir", SLUG, "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == str(archived)


def test_design_dir_cli_exits_2_when_unresolvable(tmp_path, capsys):
    assert certify_ledger.main(["design-dir", SLUG, "--root", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and SLUG in captured.err


@pytest.mark.parametrize("state,outcome", [
    ("certified", "assert"), ("pending", "skip"), ("missing", "fail"),
    ("stale-pending", "fail")])
def test_gate_outcome_per_state(state, outcome):
    """F3: `pending` is the only skip; widening it fails here, not silently in the gate."""
    assert certify_ledger.gate_outcome(state) == outcome


def test_gate_outcome_covers_every_state_and_rejects_others():
    assert {s: certify_ledger.gate_outcome(s) for s in certify_ledger.STATES} == {
        "certified": "assert", "pending": "skip", "stale-pending": "fail", "missing": "fail"}
    with pytest.raises(ValueError):
        certify_ledger.gate_outcome("unknown")
