"""throughput.md sections and the SKILL.md headroom it buys (run-throughput 4.4).

design: run-throughput (detailed-design.md §Data Flow 2; detailed-design-part-a.md
§Telemetry; Decision 9: new orchestrator prose lives in throughput.md, SKILL.md keeps
pointers). Content checks only: each section names the agents / helpers it wires.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
THROUGHPUT_MD = SKILL_DIR / "throughput.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
SKILL_CHAR_TARGET = 116_500  # plan 4.4 Done-when; the never-grow pins stay where they are
THROUGHPUT_MAX_LINES = 250


def _text(path: Path) -> str:
    if path == SKILL_MD:
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(head: str) -> str:
    text = _text(THROUGHPUT_MD)
    start = text.index(f"\n## {head}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _skill_section(head: str) -> str:
    text = _text(SKILL_MD)
    start = text.index(f"\n## {head}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _agent_row(agent: str) -> str:
    rows = [ln for ln in _section("Slot agents").splitlines()
            if ln.startswith("|") and f"`{agent}`" in ln]
    assert len(rows) == 1, f"{agent}: expected one §Slot agents row, got {rows!r}"
    return rows[0]


def test_slot_agents_generator_row():
    row = _agent_row("tp-generator")
    assert re.search(r"Slots 1, 2, 3, 5, 9, 10", row)
    assert "template default" in row


def test_slot_agents_reader_synth_and_worker_rows():
    reader = _agent_row("tp-readonly-auditor")
    assert "Slot 4/6" in reader and "reader" in reader and "synthesizer" in reader
    assert "Slot 8 synthesizer" in _agent_row("tp-impl-auditor")
    assert "Slot 7" in _agent_row("tp-worker")


def test_slot_agents_review_and_certifier_rows():
    assert "Tier 7" in _agent_row("tp-review-confirmer")
    assert "certif" in _agent_row("tp-certifier").lower()


def test_dispatch_selection_names_floor_and_task_start():
    sec = _flat(_section("Dispatch selection"))
    assert "dispatch_select.py floor --role" in sec
    assert "task_start" in sec
    for pair in ("`local` → `local-medium`", "`sonnet` → `sonnet-xhigh`",
                 "`opus` → `opus-xhigh`"):
        assert pair in sec, pair
    clerical = sec[sec.index("**Kind**: clerical"):]
    assert clerical.index("`sonnet-medium`") < clerical.index("`opus-medium`")


def test_dispatch_logging_names_record_and_decisions():
    sec = _flat(_section("Dispatch logging"))
    assert "dispatch_log.py record" in sec and "--decisions" in sec
    assert "local_route_log.append_entry" in sec
    assert "dispatch-telemetry.ndjson" in sec


def test_dispatch_logging_names_agent_id_usage_source():
    """task-worker-sonnet 1.5 (M47): slot rows read the spawn's transcript usage."""
    sec = _flat(_section("Dispatch logging"))
    assert "--agent-id" in sec
    assert "usage_source" in sec and "tokens_harness" in sec
    assert "tokens_by_source" in sec
    assert "message_start" in sec and "mixed" in sec


def test_retry_with_advice_holds_the_moved_subsections():
    sec = _section("Retry with advice (audits)")
    for head in ("\n### When it fires\n", "\n### File-reference re-spawn\n"):
        assert head in sec, head
    assert "**Map-check exemption:**" in sec
    assert "git diff --name-only" in sec and "only those phase(s)" in sec



def test_retry_with_advice_patches_and_measures():
    """run-throughput 5.6 (dd Data Flow 3): a Slot 4/6 retry is a `tp-generator` patch."""
    sec = _flat(_section("Retry with advice (audits)"))
    assert "`tp-generator`" in sec and "--patch" in sec
    assert "artifact_patch_delta.py" in sec and "patch-delta" in sec
    assert "flag: patch-overreach" in sec and "ratio > 0.5" in sec


def test_retry_with_advice_recheck_rule():
    """review-convergence 12.4 (§F1): one patch, then `recheck` — not the lows-only rule."""
    sec = _flat(_section("Retry with advice (audits)"))
    for needle in ("audit_retry_rules.py recheck", "one patch", "one re-check",
                   "artifact_patch_delta.py", "<attempt-1 head>..HEAD", "PASS WITH NOTES",
                   "tp-readonly-auditor", "tp-impl-auditor", "finalizer"):
        assert needle in sec, needle
    lows = sec[sec.index("audit_retry_rules.py recheck"):]
    assert "critical" in lows and "medium" in lows and "--max-attempts" in lows


def test_skill_md_retry_counter_is_one_patch_plus_one_recheck():
    sec = _flat(_skill_section("Retry-with-advice counter"))
    assert "one patch" in sec and "one re-check" in sec
    assert "--max-attempts" in sec and "supersede" in sec.lower()


def test_skill_md_step2b_gates_the_certifier_with_cert_once():
    text = _text(SKILL_MD)
    start = text.index("### Step 2 — `impl-audit` slot")
    step2 = text[start:text.index("### Step 3 — `design-learn` slot", start)]
    assert "cert_once.py should-run" in step2

def test_skill_md_keeps_heading_and_pointers():
    text = _text(SKILL_MD)
    retry = text.split("\n## Retry-with-advice (audits)\n", 1)[1].split("\n## ", 1)[0]
    assert "throughput.md" in retry
    assert "\n### When it fires\n" not in text and "\n### File-reference re-spawn\n" not in text
    slots = text.split("\n## Slots\n", 1)[1].split("\n### ", 1)[0]
    assert "throughput.md" in slots
    boundary = text.split("\n### Tier-boundary check", 1)[1].split("\n### ", 1)[0]
    assert "throughput.md" in boundary


def test_sizes():
    assert len(_text(SKILL_MD)) <= SKILL_CHAR_TARGET
    assert len(_text(THROUGHPUT_MD).splitlines()) <= THROUGHPUT_MAX_LINES
