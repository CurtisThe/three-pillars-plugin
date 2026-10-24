"""The review-stop prose: round tail, finalizer-first, schema, step 10b.

design: seat-escalate-first (Phase 1, Task 1.5)

Oracle: example. The docs are the contract a round-tail or orchestrator agent
follows, so each test pins the commands, flags and result names that procedure
needs, read from the file itself (cite `skills/_shared/test-fragility.md`:
identifiers and CLI tokens only, never a sentence's wording). Slices are cut at
structural anchors (a heading, a numbered step), never at a line number.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOPO = ROOT / "skills/tp-pr-iterate/round-topology.md"
FIRST = ROOT / "skills/_shared/finalizer-first.md"
SKILL = ROOT / "skills/tp-pr-iterate/SKILL.md"
TAIL_SCHEMA = ROOT / "skills/tp-pr-iterate/schemas/round-tail.v1.json"
REPO_SCHEMA = ROOT / "skills/_shared/repo-config.schema.json"

SECTION_NEEDLES = [
    "review_stop.py settle", "--config", "--scope", "skills/_shared/escalation.md",
    "label", "fix", "card", "escalate", "halt", "unmappable-choice", "already-finalized",
    "classified=<settle notes>", "ruling_cli.py answer", "r<N>.1", "review_stop.iteration",
]


def _text(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


def _review_stop() -> str:
    text = _text(TOPO)
    i = text.index("## Review stop")
    nxt = text.find(" ## ", i + 1)
    return text[i:nxt] if nxt != -1 else text[i:]


def _step4() -> str:
    return _slice(_text(TOPO), "4. **Orchestrator.**", "## Reproducer outcomes")


def _step32() -> str:
    return _slice(_text(TOPO), "2. on a clean round", "3. otherwise captures")


def test_review_stop_section_names_the_commands_and_results():
    section = _review_stop()
    for needle in SECTION_NEEDLES:
        assert needle in section, f"## Review stop never names {needle!r}"


def test_review_stop_section_is_per_pr_with_no_blanket_policy():
    section = _review_stop().lower()
    assert "per pr" in section
    assert "no blanket" in section


def test_review_stop_section_runs_the_stop_through_the_run_entry():
    section = _review_stop()
    assert "finalizer_cli" in section and "--entry run" in section
    assert section.index("--entry run") < section.index("review_stop.py settle")


def test_review_stop_label_reshell_accepts_the_second_proof_digest():
    section = _review_stop().lower()
    assert "converge.py" in section
    assert "second proof digest" in section


def test_step4_routes_the_terminal_null_question_stop_to_the_section():
    step = _step4()
    assert "terminal-null" in step
    assert "§Review stop" in step


def test_step4_terminal_null_rule_comes_before_the_rerun_review_sentence():
    step = _step4()
    assert step.index("terminal-null") < step.index("On `rerun-review`")


def test_step4_keeps_the_budget_terminal_finalizer_first_rule():
    step = _step4()
    assert "budget" in step and "finalizer_cli.py prepare" in step


def test_step32_converge_rounddir_exits_3_never_4_with_a_finalizer_stop():
    step = _step32()
    for needle in ("converge_rounddir", "exits 3, never 4", "`finalizer_stop`",
                   "exit 4 never carries"):
        assert needle in step, f"step 3.2 never names {needle!r}"


def test_step32_review_stop_envelope_is_terminal_null_rerun_review():
    step = _step32()
    assert "review stop" in step
    assert "terminal` null" in step
    assert 'action: "rerun-review"' in step
    assert "r<N>.1" in step


def test_round_tail_schema_describes_the_review_stop():
    schema = json.loads(TAIL_SCHEMA.read_text(encoding="utf-8"))
    description = schema["properties"]["finalizer_stop"]["description"]
    assert "review stop" in description


def test_finalizer_first_stop_table_has_the_review_stop_row():
    rows = [ln for ln in FIRST.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    assert any("review_stop" in ln and "decision" in ln for ln in rows), rows


def test_skill_step_10b_points_at_the_review_stop_section():
    text = SKILL.read_text(encoding="utf-8")
    para = re.sub(r"\s+", " ", _slice(text, "10b. **Two-stable", "\n\n"))
    assert "`round-topology.md` §Review stop" in para
    assert "`question`" in para


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


def test_repo_config_schema_has_no_review_stop_key():
    schema = json.loads(REPO_SCHEMA.read_text(encoding="utf-8"))
    assert not [k for k in _keys(schema) if "review_stop" in k]


def test_review_stop_settles_the_id_escalate_prints():
    section = _review_stop()
    escalate = _slice(section, "**`escalate`**", "**`halt`**")
    assert "ruling_id" in escalate
    assert "ruling_id" in section[section.index("**`halt`**"):]
