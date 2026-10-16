"""Doc pins for the per-phase check wiring (review-convergence 9.4).

`skills/_shared/phase-check.md` is the procedure the orchestrator follows after every
Tier 3.5 `ok`; `skills/tp-run-full-design/SKILL.md` carries only pointers to it (the
grandfathered monolith). Every assertion here is line-anchored: it reads a numbered step
line, or a pointer line inside the section its heading names, so a mention elsewhere in
the 1k-line SKILL.md cannot satisfy it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
MD = REPO_ROOT / "skills" / "_shared" / "phase-check.md"
SKILL_MD = REPO_ROOT / "skills" / "tp-run-full-design" / "SKILL.md"

# The fixed step sequence, in order, each on a line starting `N. **<Name>**`.
STEPS = ["Prepare", "Finder", "Checker", "Worker once", "Tier 3.5", "Close", "Commit"]
STEP_LINE = re.compile(r"^(\d+)\. \*\*([^*]+)\*\*", re.MULTILINE)

# A top-level numbered step (`N. ` — bold or plain) ends the region of the step before it.
TOP_LEVEL_STEP = re.compile(r"^\d+\. ")

# The one pointer line Slot 7 gains, verbatim, directly after the Tier 3.5 step.
SLOT7_POINTER = (
    "6. **Per-phase check** after each Tier 3.5 `ok` (its envelope carries `sha`): "
    "follow `skills/_shared/phase-check.md` before the next phase dispatch."
)


def _md() -> str:
    return MD.read_text(encoding="utf-8")


def _skill() -> str:
    return skill_text.read_skill_text("tp-run-full-design")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def _between(text: str, start: str, end: str) -> str:
    return _flat(_section(text, start, end))


def _step_body(name: str) -> str:
    """One numbered step of §Steps (Slot 7): from its line to the next numbered step."""
    lines = _section(_md(), "## Steps (Slot 7)", "\n## ").splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(f"{name}"))
    end = next((i for i in range(at + 1, len(lines)) if STEP_LINE.match(lines[i])), len(lines))
    return _flat("\n".join(lines[at:end]))


def test_phase_check_md_exists_within_size_bounds():
    assert MD.is_file(), f"missing {MD}"
    n = len(_md().splitlines())
    assert 90 <= n <= 300, f"phase-check.md is {n} lines (expected 90-300)"


def test_steps_section_has_the_seven_steps_in_order():
    found = [(n, name) for n, name in STEP_LINE.findall(_section(_md(), "## Steps (Slot 7)", "\n## "))]
    assert [name for _n, name in found] == STEPS, f"steps are {found}"
    assert [n for n, _name in found] == [str(i) for i in range(1, 8)], f"numbering: {found}"


def test_step_1_prepare_names_the_range_and_the_three_statuses():
    body = _step_body("1. **Prepare**")
    assert not [s for s in ("phase_check.py prepare", "--base <phase_base_sha> --head <sha>",
                            "sha", "skip", "resume", "ready") if s not in body], body


def test_step_2_finder_is_the_cheap_class_and_puts_its_reply():
    body = _step_body("2. **Finder**")
    assert not [s for s in ("review_finder", "cheap_engine.py resolve review_finder --local",
                            "phase_check.py put --scratch <scratch> --slot finder")
                if s not in body], body


def test_step_3_checker_is_the_pinned_judge_agent():
    body = _step_body("3. **Checker**")
    assert not [s for s in ("tp-phase-checker", "opus", "medium",
                            "phase_check.py put --scratch <scratch> --slot checker")
                if s not in body], body


def test_step_4_findings_go_back_to_the_same_worker_once():
    body = _step_body("4. **Worker once**")
    assert not [s for s in ("SAME phase worker", "SendMessage", "agent_meta.agentId",
                            "tp-worker", "--local", "never a loop") if s not in body], body


def test_step_5_reruns_tier_3_5_on_the_follow_up():
    body = _step_body("5. **Tier 3.5**")
    assert not [s for s in ("run_tier_3_5.py", "same base", "retry table",
                            "never blocks the phase") if s not in body], body


def test_step_6_close_is_the_cli_call():
    body = _step_body("6. **Close**")
    assert "phase_check.py close --design-dir <d> --phase <N> --scratch <scratch> --worker-reply <file>" in body, body


def test_step_7_commits_the_carry_before_the_next_dispatch():
    body = _step_body("7. **Commit**")
    assert not [s for s in ("phase-check-carry.json", "git add", "next phase") if s not in body], body


def test_caps_section_names_the_spawned_record_and_the_watch():
    body = _between(_md(), "## Caps", "\n## ")
    assert not [s for s in ("agent_caps.py spawned", "agent_caps.py watch --slot-root <scratch>",
                            "background") if s not in body], body


def test_worker_reply_shape_is_the_literal():
    body = _between(_md(), "## Worker reply shape", "\n## ")
    assert '{"fixed": [ids], "disputed": [{"id", "reason"}]}' in body, body


def test_just_do_it_section_runs_the_same_steps_as_phase_jdi():
    body = _between(_md(), "## Just-do-it", "\n## ")
    assert not [s for s in ("weight_class.py read", "just-do-it", "step 6g", "--phase jdi",
                            "git merge-base origin/<base> HEAD", "prepare --jdi",
                            "phase_check.py jdi-warn --design-dir <d>", "exit 0")
                if s not in body], body


def test_impl_audit_section_names_the_synth_args_and_known():
    body = _between(_md(), "## Impl audit", "\n## ")
    assert not [s for s in ("build_synth_prompt(", "design_dir=<d>", "repo=<repo>",
                            "phase-check-carry.json", "phase_check.py known")
                if s not in body], body


def _top_level_step_region(text: str, start_prefix: str) -> str:
    """One top-level numbered step: from its line to the next `**` / `## ` / numbered step."""
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(start_prefix))
    end = next((i for i in range(at + 1, len(lines))
                if lines[i].startswith("**") or lines[i].startswith("## ")
                or TOP_LEVEL_STEP.match(lines[i])), len(lines))
    return "\n".join(lines[at:end])


def test_just_do_it_reads_the_weight_class_positionally():
    """`weight_class.py read` takes the design dir POSITIONALLY — `--design-dir` exits 2."""
    body = _between(_md(), "## Just-do-it", "\n## ")
    assert "weight_class.py read <d>" in body, body
    assert "weight_class.py read --design-dir" not in _md(), "positional read, not --design-dir"


def test_tier_7_step_4_terminal_list_names_evidence_complete():
    """The terminal list must name the D8 terminal and point at the rules that own it."""
    body = _top_level_step_region(_skill(), "4. Loop until the envelope reports a")
    assert not [s for s in ("evidence-complete", "convergence-rules.md", "§D8") if s not in body], body


def test_slot_7_pointer_is_the_line_after_the_tier_3_5_step():
    lines = _skill().splitlines()
    at = next(i for i, line in enumerate(lines)
              if line.startswith("5. **Orchestrator runs `run_tier_3_5.py`"))
    assert lines[at + 1] == SLOT7_POINTER, f"line after step 5 is {lines[at + 1]!r}"


def test_tier_5_step_2_pointer_names_known_items_security_and_dispositions():
    body = _between(_skill(), "### Step 2 — `impl-audit` slot", "### Step 3")
    assert not [s for s in ("phase-check-carry.json", "security", "audit_dispositions.write",
                            "skills/_shared/phase-check.md") if s not in body], body


def test_tier_6_pointer_names_jdi_warn_and_review_time():
    body = _between(_skill(), "## Tier 6 — Completion PR", "## Tier 7 — PR-iterate")
    assert not [s for s in ("pr-create", "phase_check.py jdi-warn --design-dir <d>",
                            "review_time.py --design-dir <d> --phase impl", "PR body")
                if s not in body], body


def test_tier_7_pointer_names_the_convergence_rules_and_review_weight():
    body = _between(_skill(), "## Tier 7 — PR-iterate", "### Step 1")
    assert not [s for s in ("skills/tp-pr-iterate/convergence-rules.md", "--review-weight",
                            "round_scratch.py prepare") if s not in body], body


def test_skill_md_gained_at_most_six_lines():
    """The grandfathered monolith takes pointers only: ≤ 6 lines over its 1029-line base."""
    assert len(_skill().splitlines()) <= 1035, f"SKILL.md is {len(_skill().splitlines())} lines"
