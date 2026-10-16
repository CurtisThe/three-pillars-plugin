"""Pins for `local-routing.md` (Task 5.1): the who-checks table rendered as prose.

design: hybrid-routing-hardening. Split from `test_local_routing_docs.py` (dispatch, piped-call
scan, agents, phase-implement pins live there) per the plan's size-cap note; this file pins only
`local-routing.md` itself — the run-full-design side of the who-checks table (dd `:171-206`),
with the plan's L1 delta (Task 2.3): the exit report is always one `summary --decisions` command,
never `end`, falling back to the last recorded routing line.
"""
from __future__ import annotations

import re
from pathlib import Path

import skill_text

ROOT = Path(__file__).resolve().parent.parent.parent
DOC = ROOT / "skills" / "_shared" / "local-routing.md"
RUN_SKILL_DOC = ROOT / "skills" / "tp-run-full-design" / "SKILL.md"

FORBIDDEN = ("/health", "curl", "$ANTHROPIC_BASE_URL", "HEAD /api/hello")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _run_skill_text() -> str:
    return skill_text.read_skill_text("tp-run-full-design")


def _section(text: str, heading: str) -> str:
    marker = f"\n{heading}\n"
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def _line_starting(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"no line starting with {prefix!r}")


def _line_containing(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"no line containing {needle!r}")


def _paragraph_starting(text: str, prefix: str) -> str:
    for para in text.split("\n\n"):
        if para.startswith(prefix):
            return para
    raise AssertionError(f"no paragraph starting with {prefix!r}")


def _missing(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def test_doc_exists_within_size_cap():
    assert DOC.exists(), DOC
    lines = _text().splitlines()
    assert len(lines) <= 300, f"{len(lines)} lines"


def test_headings_present_once_in_order():
    text = _text()
    for heading in ("## Interactive", "## Orchestrator", "## End"):
        assert text.count(heading) == 1, heading
    assert text.index("## Interactive") < text.index("## Orchestrator") < text.index("## End")


def test_interactive_section_names_scope_and_route_from():
    section = _section(_text(), "## Interactive")
    missing = _missing(section, "run-start", '--scope "phase <N>"', "--route-from")
    assert not missing, missing


def test_orchestrator_tier1_check_is_printed_never_logged():
    section = _section(_text(), "## Orchestrator")
    assert "Tier 1" in section
    assert "printed" in section
    assert "never logged" in section


def test_orchestrator_slot7_dispatch_covers_retries_and_reaudit():
    section = _section(_text(), "## Orchestrator")
    missing = _missing(section, "Slot 7 dispatch", "retries", "impl-audit re-dispatch")
    assert not missing, missing


def test_orchestrator_names_route_line_and_task_eligibility_flag():
    section = _section(_text(), "## Orchestrator")
    missing = _missing(section, "ROUTE:", "task_eligibility.py", "--route")
    assert not missing, missing


def test_orchestrator_exit_report_is_one_summary_command_l1():
    section = _section(_text(), "## Orchestrator")
    missing = _missing(
        section,
        "summary --decisions",
        "never `end`",
        "one command",
        "current dir",
        "completed-tp-designs",
        "no before/after-`end` branch",
        "the last recorded routing line",
    )
    assert not missing, missing


def test_end_section_content():
    section = _section(_text(), "## End")
    missing = _missing(section, "Tier 5.6", "no-op", "read back", "completed-tp-designs")
    assert not missing, missing


def test_every_check_and_end_invocation_is_piped_to_append():
    offenders = [
        line for line in _text().splitlines()
        if re.search(r"local_route_check\.py (check|end)\b", line)
        and "--decisions" in line
        and "local_route_log.py append" not in line
    ]
    assert offenders == [], offenders


def test_summary_is_never_piped_to_append():
    offenders = [
        line for line in _text().splitlines()
        if "local_route_check.py summary" in line and "local_route_log.py append" in line
    ]
    assert offenders == [], offenders


def test_no_health_endpoint_language():
    text = _text()
    present = [needle for needle in FORBIDDEN if needle in text]
    assert present == [], present


def test_run_tier1_check_unlogged():
    line = _line_starting(_run_skill_text(), "**Local preflight**")
    assert "unlogged" in line
    assert "--decisions" not in line


def test_run_compose_carries_route():
    line = _line_containing(_run_skill_text(), "worker_prompt = compose(")
    assert "route=R if --local" in line


def test_run_dispatch_rechecks_with_retries():
    line = _line_starting(_run_skill_text(), "1. **Branch setup**")
    assert "retries" in line
    assert "ROUTE:" in line


def test_run_closeout_reads_back():
    line = _line_starting(_run_skill_text(), "- **Closeout status**")
    assert "read back" in line
    assert "under `--local`" not in line.lower()


def test_run_cleanup_cites_summary_never_end():
    text = _run_skill_text()
    section = _section(text, "## Cleanup")
    assert "summary" in section
    assert "local_route_check.py end" not in section
    assert "routing `end`" not in section

    tier5_intro = _paragraph_starting(
        text, "Tier 5 takes the validated single candidate"
    )
    tier35_section = _section(text, "### Tier 3.5 outcomes")
    tier35_success = _line_starting(tier35_section, "- **Success**:")
    every_terminal = _line_starting(text, "- **Every terminal outcome above**")
    for snippet in (tier5_intro, tier35_success, every_terminal):
        assert "routing `end`" not in snippet
        assert "§End" not in snippet


def test_run_tier56_end_unconditional():
    para = _paragraph_starting(
        _run_skill_text(), "**This is the closeout-before-merge terminal.**"
    )
    sentence = para.rsplit(". ", 1)[-1]
    assert "Tier 5.6 first runs" in sentence
    assert "routing `end`" in sentence
    assert "no-op" in sentence
    assert "local-routing.md` §End" in sentence
    assert "Under `--local`" not in sentence

    cleanup_line = _line_starting(
        _run_skill_text(), "1. Append the terminal decisions.md entry"
    )
    assert "Under `--local`" in cleanup_line


def test_protocol_end_every_run():
    section = _section(_text(), "## End")
    missing = _missing(section, "every run", "no-op", "cold resume", "Row 3")
    assert not missing, missing


def _subsection(text: str, heading: str) -> str:
    marker = f"\n{heading}\n"
    start = text.index(marker) + len(marker)
    match = re.search(r"\n#{2,3} ", text[start:])
    end = start + match.start() if match else -1
    return text[start:] if end == -1 else text[start:end]


def test_protocol_fold_conflict_and_block_exits():
    section = _section(_text(), "## End")
    missing = _missing(
        section,
        "Fold conflict",
        "`/tp-design-complete --auto` BLOCKs",
        "legacy",
        "summary --decisions",
        "tp-designs/{slug}/decisions.md",
        "committed",
    )
    assert not missing, missing

    every_run_idx = section.index("Every run, no condition.")
    fold_idx = section.index("Fold-conflict and BLOCK exits.")
    assert every_run_idx < fold_idx

    tier56_section = _subsection(_run_skill_text(), "### Tier 5.6 outcomes")
    missing_skill = _missing(
        tier56_section, "**Fold conflict**", "`/tp-design-complete --auto` BLOCKs"
    )
    assert not missing_skill, missing_skill
