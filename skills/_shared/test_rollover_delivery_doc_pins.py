"""Doc pins for fleet-watcher-reliability task 1.8: rollover, launch and promote docs."""
from pathlib import Path

SHARED = Path(__file__).resolve().parent
ROOT = SHARED.parents[1]


def _text(path):
    return " ".join(path.read_text(encoding="utf-8").split())


def test_context_rollover_states_new_rules():
    text = _text(SHARED / "context-rollover.md")
    assert "config dir" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "shell still running" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "background agents" in text and "`parked`" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "completed" in text and "handoff" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "`unavailable`" in text and "no design dir" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)


def test_design_run_launch_lists_outcomes_and_registration():
    text = _text(SHARED / "design-run-launch.md")
    assert "`queued`" in text and "`occupied`" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "occupied` even when busy" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "registers the run on the roster" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
    assert "not registered" in text  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)


def test_promote_step_11_says_launcher_registers():
    text = (ROOT / "skills/tp-promote/SKILL.md").read_text(encoding="utf-8")
    step = text[text.index("11. **Launch the design run"):text.index("## Edge cases")]
    assert "registers the run" in " ".join(step.split())  # tp-allow-fragile: design-mandated doc pin (fleet-watcher-reliability task 1.8)
