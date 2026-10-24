"""Tests for slot_entry.py: slot headings carry wall-clock minutes (B6)."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_retro_collect as rc  # noqa: E402
import slot_entry  # noqa: E402

S = "2026-10-23T00:10:00Z"


def test_heading_whole_minutes():
    assert slot_entry.heading("tier-5", "impl-audit pass", S, "2026-10-23T00:22:30Z") == (
        "### [orchestrator/tier-5] impl-audit pass (13 min)"
    )


def test_heading_short_and_negative_are_zero():
    assert slot_entry.heading("t", "x", S, "2026-10-23T00:10:29Z").endswith("(0 min)")
    assert slot_entry.heading("t", "x", S, "2026-10-23T00:05:00Z").endswith("(0 min)")


def test_append_cli_writes_headings(tmp_path):
    f = tmp_path / "decisions.md"
    args = ["append", "--decisions", str(f), "--slot", "tier-1", "--title", "pickup",
            "--started", S, "--ended", "2026-10-23T00:12:00Z", "--body", "**Status**: pass"]
    assert slot_entry.main(args) == 0
    assert slot_entry.main(args) == 0
    text = f.read_text(encoding="utf-8")
    heads = [ln for ln in text.splitlines() if ln.startswith("### [orchestrator/")]
    assert len(heads) == 2
    assert all(re.search(r"\(\d+ min\)$", h) for h in heads)
    assert text.startswith("#")
    entries = rc.parse_entries(text)
    assert entries and entries[0]["prefix"] == "orchestrator/tier-1"


def test_bad_iso_exits_2(tmp_path):
    rc_ = slot_entry.main(["append", "--decisions", str(tmp_path / "d.md"), "--slot", "a",
                           "--title", "b", "--started", "nonsense"])
    assert rc_ == 2


def test_skill_md_names_slot_entry():
    skill = HERE.parent / "tp-run-full-design" / "SKILL.md"
    assert "slot_entry.py append" in skill.read_text(encoding="utf-8")
