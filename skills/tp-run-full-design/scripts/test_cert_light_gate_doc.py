"""tier-5-closeout.md Step 2b passes the light gate flags to cert_once should-run.

design: light-run-ceremony-diet 1.2 (B1). Content pin on load-bearing literals
only (skills/_shared/test-fragility.md): the orchestrator prose must name the
command, its two flags and the log tag it writes when the certifier is skipped.
"""
from __future__ import annotations

import re
from pathlib import Path

CLOSEOUT = Path(__file__).resolve().parent.parent / "tier-5-closeout.md"


def _step_2b() -> str:
    text = CLOSEOUT.read_text(encoding="utf-8")
    start = text.index("**Step 2b")
    return text[start:text.index("### Step 3", start)]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_step_2b_light_command_names_the_flags():
    paragraphs = [_flat(p) for p in _step_2b().split("\n\n")]
    light = [p for p in paragraphs
             if "cert_once.py should-run" in p and "--light" in p and "--base" in p]
    assert light, "no Step 2b paragraph passes --light and --base to cert_once.py should-run"


def test_step_2b_logs_certification_skipped():
    assert "certification-skipped" in _step_2b()
