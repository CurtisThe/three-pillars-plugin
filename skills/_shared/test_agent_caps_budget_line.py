"""Task 7.4 — the budget line reaches cheap finders only, and §Caps names the caps CLI.

`angles.build_prompt` appends `agent_caps.BUDGET_LINE` for a `role == "finder"` angle;
the Opus confirmer, the delta check and the Opus check angle get no budget line.
`skills/council/strata-members.md` §Caps replaces the manual per-poll prose with the
budget line, the `FINDING {json}` delivery rule, `spawned` and a background
`watch --role council_member`. Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SKILLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_SKILLS / "tp-pr-iterate" / "scripts"))

import agent_caps  # noqa: E402
import angles  # noqa: E402
import finder_round  # noqa: E402
import round_plan  # noqa: E402

REPLY = "/r/rounds/1/r1/f1/reply.md"


def _prompt(angle: dict) -> str:
    return angles.build_prompt(angle, base="b", head="h", effort="high", reply_path=REPLY)


def test_finder_prompt_ends_with_the_budget_line():
    p = _prompt({"name": "f1", "role": "finder", "model": "local", "prompt": "Look."})
    assert p.endswith(agent_caps.BUDGET_LINE)


def test_confirmer_prompt_has_no_budget_line():
    p = _prompt({"name": "c1", "role": "confirmer", "model": "opus", "prompt": "Look."})
    assert agent_caps.BUDGET_LINE not in p


def test_delta_check_angle_has_no_budget_line():
    angle = round_plan.delta_check_angle("/x/tail/findings.json")
    assert agent_caps.BUDGET_LINE not in _prompt(angle)


def test_opus_check_angle_has_no_budget_line(tmp_path):
    rulings = tmp_path / "rulings.md"
    rulings.write_text("# rulings\n", encoding="utf-8")
    assert agent_caps.BUDGET_LINE not in finder_round.check_angle(str(rulings))["prompt"]


def _caps_section() -> str:
    text = (_SKILLS / "council" / "strata-members.md").read_text(encoding="utf-8")
    rest = text.split("## Caps", 1)[1]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def test_caps_section_names_the_caps_cli_and_delivery():
    caps = _caps_section()
    for needle in ("agent_caps.py budget-line", "FINDING {json}", "agent_caps.py spawned",
                   "watch --role council_member", "capped_members"):
        assert needle in caps, needle
