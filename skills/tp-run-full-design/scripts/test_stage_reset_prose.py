"""Stage-reset prose: `--resume-stage`, throughput.md §Stage reset, the stage-boundary handoff.

design: run-throughput 7.4 (detailed-design-stage-reset.md §When a reset fires, §Handoff,
§Data flow at a boundary; Decision 8 re-entry, Decision 9 prose placement, Decision 12
measurement obligation). Content checks only: each place names the flag, helper or section
it wires.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS = SKILL_DIR.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
THROUGHPUT_MD = SKILL_DIR / "throughput.md"
SAVE_MD = SKILLS / "tp-session-save" / "SKILL.md"
LEASE_PY = SKILLS / "_shared" / "local_lease.py"


def _text(path: Path) -> str:
    if path == SKILL_MD:
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, head: str) -> str:
    start = text.index(f"\n{head}\n")
    level = head.split(" ", 1)[0]
    end = text.find(f"\n{level} ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _stage_reset() -> str:
    return _section(_text(THROUGHPUT_MD), "## Stage reset")


def test_skill_md_lists_resume_stage():
    text = _text(SKILL_MD)
    hint = text.split("\n---\n", 1)[0]
    assert "--resume-stage <plan|implement|review>" in hint
    args = _section(text, "## Arguments")
    entry = [ln for ln in args.splitlines() if ln.startswith("- `--resume-stage")]
    assert len(entry) == 1
    assert "`--resume-stage <plan|implement|review>`" in entry[0]
    assert "throughput.md" in entry[0] and "Stage reset" in entry[0]


def test_skill_md_execution_flow_points_at_stage_reset():
    flow = _flat(_section(_text(SKILL_MD), "## Execution flow"))
    assert "throughput.md" in flow and "§Stage reset" in flow


def test_gate_names_the_three_conditions_and_skip_line():
    sec = _flat(_stage_reset())
    assert "stage_reset.should_reset" in sec
    assert "TP_STAGE_RESET=pane" in sec and "$TMUX_PANE" in sec
    assert "[orchestrator] stage-reset skipped (<why>)" in sec
    for why in ("non-interactive", "no tmux pane", "outside mode window"):
        assert f"`{why}`" in sec, why


def test_stage_reset_is_marked_dormant():
    sec = _flat(_stage_reset())
    note = sec[sec.index("**Dormant.**"):sec.index("### Gate")]
    assert "dormant" in note and "stage-reset-supervisor" in note
    assert "`non-interactive`" in note and "classifier" in note and "/clear" in note
    assert "exported only by the interactive launchers" not in sec


def test_boundary_table_per_mode_and_weight():
    rows = [ln for ln in _stage_reset().splitlines() if ln.startswith("| `")]
    table = {ln.split("|")[1].strip(): ln.split("|")[2].strip() for ln in rows}
    assert set(table) == {"`full`, `weight-class: full`", "`full`, `weight-class: light`",
                          "`design`", "`plan`", "`build`"}
    full = table["`full`, `weight-class: full`"]
    assert "design→plan" in full and "plan→implement" in full and "implement→review" in full
    light = table["`full`, `weight-class: light`"]
    assert "design→plan (after" not in light and "plan→implement" in light and "implement→review" in light
    assert table["`design`"].startswith("none") and table["`plan`"].startswith("none")
    assert table["`build`"].startswith("implement→review") and "plan→" not in table["`build`"]


def test_five_step_flow_in_order():
    flow = _section(_stage_reset(), "### Flow at a boundary")
    steps = [_flat(chunk) for chunk in re.split(r"\n(?=\d\. )", flow)[1:]]
    assert [s[:2] for s in steps] == ["1.", "2.", "3.", "4.", "5."]
    wants = [
        ["/tp-session-save <slug> --stage-boundary", "## Run budget"],
        ["Commit and push"],
        ["resume_command", "stage_reset.py schedule", "end the turn"],
        ["/clear", "--resume-stage <S>", "stage-reset: idle-timeout", ".handoffs/stage-reset.log"],
        ["/tp-session-restore <slug>", "## Run budget", "lock", "first slot"],
    ]
    for step, needles in zip(steps, wants):
        for needle in needles:
            assert needle in step, (needle, step)


def test_resume_budget_restore_and_halt():
    sec = _flat(_stage_reset())
    assert "before its first slot" in sec
    for key in ("tokens_used", "started_epoch", "retry_counters", "argv"):
        assert f"`{key}`" in sec, key
    assert "[orchestrator] resume-budget-missing" in sec
    assert "never restart" in sec.lower()


def test_open_obligations_carry_measurement_and_homelab_note():
    sec = _flat(_section(_stage_reset(), "### Open obligations (implement→review)"))
    assert "`## Open obligations`" in sec
    assert "Decision 12" in sec
    assert "before/after timing" in sec and "local-heavy rerun" in sec
    assert "Homelab" in sec and "max_tokens" in sec and "local-llm-skills" in sec


def test_session_save_stage_boundary_sections():
    text = _text(SAVE_MD)
    hint = text.split("\n---\n", 1)[0]
    assert "--stage-boundary" in hint
    body = _section(text, "## Stage boundary (`--stage-boundary`)")
    for head in ("## Rulings", "## Ladder decisions", "## Open obligations", "## Run budget"):
        assert f"`{head}`" in body, head
    blocks = re.findall(r"```json\n(.*?)\n```", body, re.S)
    assert len(blocks) == 1
    budget = json.loads(blocks[0])
    assert set(budget) == {"argv", "tokens_used", "started_epoch", "retry_counters"}
    assert "resume-budget-missing" in body


def test_local_lease_docstring_points_at_follow_on():
    doc = _text(LEASE_PY).split('"""', 2)[1]
    assert "gpu-fair-share-parallel-phases" in doc
    # Q1 (operator ruling): the lease is the real slot check now, no longer a noop.
    assert "run-throughput not landed" not in _text(LEASE_PY)


def test_pre_split_budget_moved_to_throughput():
    handoff = _section(_text(SKILL_MD), "## Handoff protocol — pre-split (M2)")
    assert "throughput.md" in handoff and "Pre-splitting is purely" not in handoff
    moved = _flat(_section(_text(THROUGHPUT_MD), "## Pre-split budget"))
    assert "subagent_tokens" in moved and "--max-tokens" in moved and "overshoot" in moved
