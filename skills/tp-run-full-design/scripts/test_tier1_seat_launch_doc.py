"""Tier 1 pickup doc pin: both gate sites call one script, and it works.

Designs: run-friction-1022 Task 1.15, followups-1023 Task 2.1. The Tier 1
"Confirmation prompt" section and the Tier 0 backstop section of
design-run-launch.md each name `skills/_shared/autonomous_gate.py` as the one
go-autonomous check (exit 0 skip, exit 1 ask). The test runs that documented
command's entry point, so the doc cannot drift from the script's behaviour.

Run with: pytest skills/tp-run-full-design/scripts/test_tier1_seat_launch_doc.py -q
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TIER1 = ROOT / "skills" / "tp-run-full-design" / "tier-1-pickup.md"
LAUNCH_RULE = ROOT / "skills" / "_shared" / "design-run-launch.md"
GATE = "skills/_shared/autonomous_gate.py"
PREFIX = 'python3 "$TP_ROOT"/'
SPAN_RE = re.compile(r"`([^`]+)`")


def _confirmation_section() -> str:
    text = TIER1.read_text(encoding="utf-8")
    start = text.index("### Confirmation prompt")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def _backstop_section() -> str:
    text = LAUNCH_RULE.read_text(encoding="utf-8")
    start = text.index("## Backstop inside the design run (Tier 0)")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def _py_spans(section: str) -> list[str]:
    return [s for s in SPAN_RE.findall(section) if ".py" in s]


def _command_path(span: str) -> str:
    return span[len(PREFIX):] if span.startswith(PREFIX) else span


def _load_gate():
    spec = importlib.util.spec_from_file_location("autonomous_gate_doc", ROOT / GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_gate_site_names_the_one_script() -> None:
    for name, section in (("confirmation", _confirmation_section()),
                          ("backstop", _backstop_section())):
        spans = _py_spans(section)
        assert len(spans) == 1, f"{name} section: expected one .py span, got {spans}"
        path = _command_path(spans[0])
        assert path == GATE, f"{name} section names {path!r}, not {GATE}"
        assert (ROOT / path).is_file(), f"{name} section: {path} is not a file"


def test_documented_gate_skips_a_seat_launch_and_asks_a_child() -> None:
    gate = _load_gate()
    seat = {"TP_DESIGN_RUN": "1"}
    child = {"TP_DESIGN_RUN": "1", "TP_CHILD_SESSION": "1"}
    assert gate.main([], env=seat) == 0
    assert gate.main([], env=child) == 1


def test_seat_launch_logs_and_advances() -> None:
    section = _confirmation_section()
    assert "autonomous-continue (seat launch)" in section
    assert "Tier 2" in section


def test_prompt_stays_after_the_gate() -> None:
    section = _confirmation_section()
    assert "Go autonomous from here?" in section
    gate_span = _py_spans(section)[0]
    assert section.index(gate_span) < section.index("Go autonomous from here?")
