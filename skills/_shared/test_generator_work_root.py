"""Task 2.4 (worktrees-under-wt-only): generator slots run without isolation; generator stop rule."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import wt_layout_scan as w  # noqa: E402

SKILL = ROOT / "skills/tp-run-full-design/SKILL.md"
GEN = ROOT / "agents/tp-generator.md"
OURS = {"skills/tp-run-full-design/SKILL.md", "agents/tp-generator.md"}


def _dispatch_paragraph() -> str:
    text = SKILL.read_text(encoding="utf-8")
    section = text.split("\n## Dispatch loop", 1)[1].split("\n## ", 1)[0]
    hits = [p for p in section.split("\n- ") if "subagent_type" in p and "tp-generator" in p]
    assert hits, "no tp-generator dispatch bullet in ## Dispatch loop"
    return hits[0]


def test_dispatch_line_names_agent_ref_and_no_isolation():
    para = _dispatch_paragraph()
    assert 'agent_ref("tp-generator")' in para
    assert "isolation" not in para


def test_dispatch_paragraph_names_working_directory():
    assert "WORKING DIRECTORY:" in _dispatch_paragraph()


def test_generator_stop_rule_tokens():
    text = GEN.read_text(encoding="utf-8")
    assert 'status: "errored"' in text
    assert "blocked:" in text


def test_layout_scan_clean_on_both_files():
    hits = w.scan([ROOT / "skills", ROOT / "agents"])
    assert [h for h in hits if h[0] in OURS] == []
