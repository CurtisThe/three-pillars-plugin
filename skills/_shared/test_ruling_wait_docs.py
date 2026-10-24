"""Doc pins: a design run waits on the ruling file instead of opening a card (plan task 1.3)."""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ESC = _ROOT / "skills" / "_shared" / "escalation.md"
_TOPO = _ROOT / "skills" / "tp-pr-iterate" / "round-topology.md"


def _escalate_section() -> str:
    text = _ESC.read_text(encoding="utf-8")
    start = text.index("### 3. `escalate`")
    end = text.find("\n## ", start)
    return text[start:end if end != -1 else len(text)]


def test_escalate_section_tells_a_design_run_to_wait():
    sec = _escalate_section()
    for needle in (
        "TP_DESIGN_RUN=1",
        "awaiting-operator: ruling <ruling-id>",
        "ruling_cli.py wait --id <ruling-id>",
        "ruling_cli.py answer",
        "answer-in-text",
        "second line",
        "ruling_cli.py card",
    ):
        # tp-allow-fragile: design-mandated doc pin (plan task 1.3: a design run must be told to wait on the ruling file)
        assert needle in sec, needle


def test_round_topology_card_bullet_points_to_wait():
    lines = _TOPO.read_text(encoding="utf-8").splitlines()
    bullets = [ln for ln in lines if ln.startswith("- **`card`**")]
    assert bullets
    bullet = bullets[0]
    for needle in ("ruling_cli.py wait", "TP_DESIGN_RUN=1", "answer-in-text"):
        # tp-allow-fragile: design-mandated doc pin (plan task 1.3: a design run must be told to wait on the ruling file)
        assert needle in bullet, needle
