"""Tests for closeout_gate.check: one test per row of the design's verdict table."""

from pathlib import Path

import closeout_gate

DOCS = "three-pillars-docs"


def _live(root: Path, slug: str, design_md="# D\n", extra=()) -> Path:
    d = root / DOCS / "tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    if design_md is not None:
        (d / "design.md").write_text(design_md)
    for name in extra:
        (d / name).write_text("x\n")
    return d


def test_unarchived(tmp_path):
    _live(tmp_path, "demo", extra=("implementation-audit.md",))
    v = closeout_gate.check(tmp_path, "demo")
    assert v.status == "unarchived"
    assert v.slug == "demo"
    assert "/tp-design-learn demo" in v.remedy
    assert "/tp-design-complete demo" in v.remedy


def test_unarchived_without_evidence_still_refuses(tmp_path):
    _live(tmp_path, "demo")
    assert closeout_gate.check(tmp_path, "demo").status == "unarchived"


def test_archived_by_move(tmp_path):
    d = tmp_path / DOCS / "completed-tp-designs" / "demo"
    d.mkdir(parents=True)
    (d / "design.md").write_text("---\ncompleted: 2026-10-13\n---\n# D\n")
    assert closeout_gate.check(tmp_path, "demo").status == "archived"


def test_archived_by_stamp(tmp_path):
    _live(tmp_path, "demo", "---\ncompleted: 2026-10-13\n---\n# D\n")
    assert closeout_gate.check(tmp_path, "demo").status == "archived"


def test_exempt_orchestration(tmp_path):
    _live(tmp_path, "orchestration", extra=("implementation-audit.md",))
    assert closeout_gate.check(tmp_path, "orchestration").status == "exempt"


def test_exempt_seed_only_dir(tmp_path):
    _live(tmp_path, "demo", None, extra=("seed.md",))
    assert closeout_gate.check(tmp_path, "demo").status == "exempt"


def test_exempt_no_dir(tmp_path):
    assert closeout_gate.check(tmp_path, "demo").status == "exempt"


def test_spike_results_routes_to_spike_learn(tmp_path):
    _live(tmp_path, "demo", extra=("spike-results.md",))
    v = closeout_gate.check(tmp_path, "demo")
    assert v.status == "unarchived"
    assert "/tp-spike-learn demo" in v.remedy
    assert "/tp-design-complete demo" in v.remedy
