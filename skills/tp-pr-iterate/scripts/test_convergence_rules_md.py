"""Task 9.5 — convergence-rules.md content and the loop pointers to it.

Pins the D1-D8 + Caps section set in skills/tp-pr-iterate/convergence-rules.md,
the SKILL.md pointer with its line/char budget, and the round-topology.md
clauses that pass --review-weight, --dispositions and frozen= through the loop.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "skills/tp-pr-iterate/convergence-rules.md"
SKILL = ROOT / "skills/tp-pr-iterate/SKILL.md"
TOPO = ROOT / "skills/tp-pr-iterate/round-topology.md"
SCHEMA = ROOT / "skills/tp-pr-iterate/schemas/round-tail.v1.json"

HEADINGS = [
    "## D1 — Severity authority",
    "## D2 — Freeze after a clean verdict",
    "## D3 — Delta rounds",
    "## D4 — Audit dispositions",
    "## D5 — Review weight",
    "## D6 — Round plan",
    "## Caps",
    "## D8 — Evidence-complete terminal",
]

LITERALS = [
    "is-frozen",
    "frozen=True",
    "--review-weight",
    "--dispositions",
    "evidence-complete",
    "one PR comment",
    "spawned",
    "watch",
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _paragraph_containing(text: str, needle: str) -> str:
    for para in text.split("\n\n"):
        if needle in para:
            return _collapse(para)
    return ""


def test_rules_doc_exists_in_size_band():
    assert RULES.exists(), "convergence-rules.md missing"
    lines = _text(RULES).splitlines()
    assert 80 <= len(lines) <= 300, f"{len(lines)} lines outside 80-300"


def test_headings_present_and_in_order():
    text = _text(RULES)
    positions = []
    for heading in HEADINGS:
        idx = text.find(heading)
        assert idx != -1, f"missing heading: {heading}"
        positions.append(idx)
    assert positions == sorted(positions), "headings out of order"


def test_key_literals_present():
    text = _text(RULES).lower()
    for literal in LITERALS:
        assert literal.lower() in text, f"missing literal: {literal}"


def test_d1_severity_authority_claims():
    text = _collapse(_section("## D1 — Severity authority"))
    assert "blocking" in text and "final" in text
    assert "severity.finalize" in text
    assert "note" in text


def test_d2_freeze_claims():
    text = _collapse(_section("## D2 — Freeze after a clean verdict"))
    assert "frozen_at" in text
    assert "round_freeze.py is-frozen --state-path <state_path>" in text
    assert "frozen=True" in text
    assert "fix_round.run_round" in text
    assert "round_freeze.py post" in text


def test_d3_delta_claims():
    text = _collapse(_section("## D3 — Delta rounds"))
    assert "delta-check" in text
    assert "delta_text(prior head, head)" in text
    assert "trust_boundary" in text


def test_d4_disposition_claims():
    text = _collapse(_section("## D4 — Audit dispositions"))
    assert "--dispositions" in text
    assert "audit-dispositions.json" in text
    assert "reproduce.py" in text


def test_d5_review_weight_claims():
    text = _collapse(_section("## D5 — Review weight"))
    assert "--review-weight" in text
    assert "weight_class.py review-weight <design_dir>" in text
    assert "round_scratch.py prepare" in text
    assert "pdw.guards.round_cap" in text


def test_d6_round_plan_claims():
    text = _collapse(_section("## D6 — Round plan"))
    assert "security" in text
    assert "delta" in text


def test_caps_claims():
    text = _collapse(_section("## Caps"))
    assert "agent_caps.py spawned --slot-root" in text
    assert "agent_caps.py watch --slot-root" in text
    assert "not evidence" in text


def test_d8_evidence_complete_claims():
    text = _collapse(_section("## D8 — Evidence-complete terminal"))
    assert '"terminal": "evidence-complete"' in text
    assert "accept hint" in text
    assert "forge.comment_post" in text
    assert "one pr comment" in text.lower()


def _section(heading: str) -> str:
    text = _text(RULES)
    start = text.find(heading)
    assert start != -1, f"missing heading: {heading}"
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt] if nxt != -1 else text[start:]


def test_skill_md_pointer_and_cap():
    text = _text(SKILL)
    assert "convergence-rules.md" in text
    assert len(text.splitlines()) <= 484
    assert len(text) <= 43000


def test_skill_md_helper_bullet_collapse_keeps_names():
    text = _text(SKILL)
    for name in ("_compute_next_wait", "_poll_step", "_detect_conflicts", "_apply_conflicts"):
        assert name in text, f"helper dropped from SKILL.md: {name}"
    assert "round_budget.tick(state," in text
    assert "test_loop_driver.py" in text


def test_topo_run_round_carries_frozen():
    para = _paragraph_containing(_text(TOPO), "fix_round.run_round(")
    assert para, "no paragraph with fix_round.run_round("
    assert "frozen=" in para
    assert "round_freeze.py is-frozen --state-path <state_path>" in para
    assert "exits 0" in para


def test_topo_review_weight_and_dispositions():
    text = _text(TOPO)
    assert "--review-weight" in text
    assert "--dispositions" in text


# --- impl-audit §D8 fix (Task 9.5): the loop procedure names the exit-4 branch ---

EXIT4_NEEDLES = [
    "exit 4",
    "evidence-complete",
    'action: "noop"',
    "fix_commit: null",
    "converged: false",
    "head_after",
    "head_reviewed",
    "iterate-state",
    "zeros",
    "accept_hint",
    "§D8",
]


def _step(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_topo_step3_names_the_converge_exit4_branch():
    """Step 3.2 carries the `converge.py` exit-4 envelope — no run_round, no budget."""
    step = _collapse(_step(_text(TOPO), "2. on a clean round", "3. otherwise captures"))
    for needle in EXIT4_NEEDLES:
        assert needle in step, f"step 3.2 never names the exit-4 branch: {needle!r}"


def test_topo_step4_posts_the_accept_hint_as_one_pr_comment():
    """Step 4 posts the hint as one PR comment, then flushes the log and stops."""
    step = _collapse(_step(_text(TOPO), "4. **Orchestrator.**", "## Reproducer outcomes"))
    assert "accept_hint" in step
    assert "one PR comment" in step
    assert "forge.comment_post" in step
    assert "never starts another round" in step


def test_evidence_complete_envelope_validates_against_the_schema():
    """The exit-4 tail has no budget: a zeros envelope passes `round-tail.v1.json`."""
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    envelope = {
        "schema": "tp-pr-iterate/round-tail/v1", "round": 3,
        "head_reviewed": "a" * 40, "head_after": "a" * 40,
        "tally": {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0},
        "downgraded": 0, "notes": 2, "action": "noop", "fix_commit": None,
        "terminal": "evidence-complete", "converged": False,
        "budget": {"iteration": 0, "round_cap": 0, "signal": None, "holding": []},
        "finalizer_stop": None,
        "summary": "evidence-complete: " + "tp-accept: " + "a" * 40 + " state file absent",
    }
    assert not list(Draft202012Validator(schema).iter_errors(envelope))


BASE_SYNC_HEADING = "## Base-sync carry check"
CARRY_CLI = "carry_check.py --repo . --pr-url <url>"
PREPARE_WORDING = "before the next round is prepared"
FLUSH_WORDING = "round_scratch.py flush"


def _section_with(path: Path, heading: str) -> str:
    text = _text(path)
    start = text.find(heading)
    assert start != -1, f"{path.name} missing heading: {heading}"
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt] if nxt != -1 else text[start:]


def test_base_sync_carry_check_order():
    """§Base-sync carry check runs the carry question before the next round and before any flush."""
    for path in (RULES, TOPO):
        section = _collapse(_section_with(path, BASE_SYNC_HEADING))
        carry = section.find(CARRY_CLI)
        assert carry != -1, f"{path.name}: base-sync text must name {CARRY_CLI}"
        prepare = section.find(PREPARE_WORDING)
        assert prepare != -1, f"{path.name}: base-sync text must gate the next round's prepare"
        assert carry < prepare, f"{path.name}: carry check must precede the next round prepare"
        flush = section.find(FLUSH_WORDING)
        assert flush != -1, f"{path.name}: base-sync text must gate {FLUSH_WORDING}"
        assert carry < flush, f"{path.name}: carry check must precede any log flush commit"


def test_topo_prepare_rulings_pin():
    text = _collapse(_text(TOPO))
    start = text.find("## One round")
    end = text.find("## Reproducer outcomes")
    assert start != -1 and end != -1 and start < end
    slice_ = text[start:end]
    for match in re.finditer(r"round_scratch\.py prepare", slice_):
        window = slice_[match.start(): match.start() + 500]
        assert "--rulings <proof_root>/rounds/<pr>/rulings.md" in window, window[:200]
        assert "[--rulings" not in window
