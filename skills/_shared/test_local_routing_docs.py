"""test_local_routing_docs.py — prose pins for the local-dispatch / routing wiring.

design: hybrid-routing-hardening (detailed-design.md §Spawn-model wiring, test spec :425-438)

Pins the Task 5.2 slice of the doc wiring: `local-dispatch.md`'s §1 Routing step (mode branch,
single writer B14), §2's `start` route flags, the single §3 spawn template (`model="{model}"`,
the `CONTRACT FIRST` prompt naming `attempt_start_check.py`), §4's interactive halt, and the two
`agents/*.md` sites. `test_every_routing_invocation_is_piped_to_append` (dd:427-428) also scans
`tp-phase-implement/SKILL.md`, `tp-run-full-design/SKILL.md` and `local-routing.md` (wired by
Tasks 5.3 / 5.4): every `check --decisions` / `end` line must feed `| python3 …local_route_log.py
append` — a `;` or `&&` before `append` is not a pipe and is flagged.
"""
from __future__ import annotations

import re
from pathlib import Path

import skill_text

ROOT = Path(__file__).resolve().parent.parent.parent
DISPATCH = ROOT / "skills" / "_shared" / "local-dispatch.md"
ROUTING = ROOT / "skills" / "_shared" / "local-routing.md"
TASK_WORKER_AGENT = ROOT / "agents" / "tp-task-worker.md"
WORKER_AGENT = ROOT / "agents" / "tp-worker.md"
PHASE_IMPLEMENT_SKILL = ROOT / "skills" / "tp-phase-implement" / "SKILL.md"
RUN_FULL_DESIGN_SKILL = ROOT / "skills" / "tp-run-full-design" / "SKILL.md"

BANNED = ("/health", "curl", "$ANTHROPIC_BASE_URL", "HEAD /api/hello")


def _read(path: Path) -> str:
    if path == RUN_FULL_DESIGN_SKILL:
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def _section(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.index(start_marker)
    if end_marker is None:
        return text[start:]
    end = text.index(end_marker, start + len(start_marker))
    return text[start:end]


# --- §1 Routing step (mode branch, single writer B14) -----------------------

def _step4_routing() -> str:
    return _section(_read(DISPATCH), "4. **Routing**", "5. **Tier table**")


def test_step1_routing_names_both_dispatchers():
    step4 = _step4_routing()
    assert "/tp-phase-implement" in step4
    assert "tp-worker" in step4
    assert "/tp-run-full-design" in step4


def test_full_design_branch_has_no_check_or_end_invocation():
    step4 = _step4_routing()
    full_design = step4[step4.index("full-design"):]
    assert "python3" not in full_design, "full-design branch must not invoke the CLI directly"
    assert "never" in full_design
    assert "[routing]" in full_design
    assert "ROUTE:" in full_design
    assert "no route flag" in " ".join(full_design.split())


def test_step1_tier_table_line_carries_a_route_flag():
    step5 = _section(_read(DISPATCH), "5. **Tier table**", "## 2. Per row")
    assert "task_eligibility.py" in step5
    assert "--route-from" in step5 or "--route" in step5


# --- §2 `start` line and the printed-tier branch -----------------------------

def _section2() -> str:
    return _section(_read(DISPATCH), "## 2. Per row", "## 3. Spawn templates")


def test_step2_start_line_has_root_and_both_route_flags():
    sec2 = _section2()
    start_line = next(ln for ln in sec2.splitlines() if "tier_ladder.py start" in ln)
    assert "--root ." in start_line
    assert "--route-from" in start_line
    assert "--route '" in start_line


def test_step2_2_branches_on_the_printed_tier():
    do_task = _section(_section2(), "2. **Do the task**", "3. **Read the reply**")
    assert "printed" in do_task


def test_config_first_attempt_sentence_and_the_old_note_are_gone():
    text = _read(DISPATCH)
    assert "On the first attempt of a rung the model is the config's" not in text
    assert "are the config defaults; pass the model the ladder names" not in text
    assert "start" in text and "next" in text  # the replacement still names both


# --- §3 the single spawn template + CONTRACT FIRST ---------------------------

def _section3() -> str:
    return _section(_read(DISPATCH), "## 3. Spawn templates", "## 4. Halt")


def test_step3_one_template_with_the_model_placeholder():
    # prompt-cache-aware-dispatch 1.5: one background template for every rung (4.3 variants,
    # by resolved reference).
    sec3 = _section3()
    assert sec3.count('subagent_type="{agent_ref}"') == 1
    assert sec3.count('model="{model}"') == 1
    assert 'model="{model}"' in sec3
    assert 'model="haiku"' not in sec3
    assert 'model="sonnet"' not in sec3


def test_step3_contract_first_names_attempt_start_check():
    sec3 = _section3()
    assert "```\nCONTRACT FIRST" in sec3
    first_line = sec3[sec3.index("```\nCONTRACT FIRST") + 4:].splitlines()[0]
    assert first_line.startswith("CONTRACT FIRST")
    assert "attempt_start_check.py" in first_line


# --- §4 interactive halt names `end` -----------------------------------------

def test_step4_interactive_halt_names_end():
    sec4 = _section(_read(DISPATCH), "## 4. Halt", "## 5. Full-design differences")
    interactive = _section(sec4, "**Interactive**", "**Full-design**")
    assert "`end`" in interactive


# --- the two `agents/*.md` sites ---------------------------------------------

def test_tp_task_worker_item1_names_attempt_start_check():
    item1 = _section(_read(TASK_WORKER_AGENT),
                     "1. **Pin your cwd first.**", "2. **Stay in the attempt.**")
    assert "attempt_start_check.py" in item1


def test_tp_worker_names_route_and_carries_no_sonnet():
    content = _read(WORKER_AGENT)
    assert "ROUTE:" in content
    # strata-spend-leaks 2.1: the worker's own model pin (frontmatter `model: sonnet` + the
    # identity "`sonnet` model default" sentence) is allowed; it names no *rung* anywhere else.
    rest = "\n".join(line for line in content.splitlines()
                     if line != "model: sonnet" and "`sonnet` model default" not in line)
    assert "sonnet" not in rest
    assert re.search(r"sonnet", rest, re.I) is None  # no case variant either


# --- no routing logic (health probes, curl, env names) leaks into markdown --

def test_no_routing_logic_in_these_docs():
    for path in (DISPATCH, TASK_WORKER_AGENT, WORKER_AGENT):
        content = _read(path)
        for banned in BANNED:
            assert banned not in content, f"{path.name}: leaked {banned!r}"


# --- every check/end invocation is piped to `append` on the same line -------

_INVOKE_RE = re.compile(
    r"^(?=.*\bpython3\b).*local_route_check\.py\s+(?:check\b[^\n]*--decisions|end\b)[^\n]*$",
    re.M,
)
# The WHOLE segment from the `check`/`end` invocation to `append` is anchored:
# it may hold no `|`, `;` or `&` except exactly ONE bare `|` right before the
# `python3 … append`. So `||`/`|&`/`;`/`&&` anywhere in it (e.g. `|| true |`)
# and a second pipe (`| tee x |`) are all "not piped".
_APPEND_RE = re.compile(
    r"local_route_check\.py\s+(?:check|end)\b[^|;&\n]*\|\s*"
    r"python3\s+\S*local_route_log\.py\s+append\b")


def _unpiped_invocations(text: str) -> list[str]:
    return [line for line in _INVOKE_RE.findall(text) if not _APPEND_RE.search(line)]


def _piped_check_targets() -> list[Path]:
    paths = [DISPATCH, ROUTING, PHASE_IMPLEMENT_SKILL, RUN_FULL_DESIGN_SKILL]
    paths += sorted((ROOT / "agents").glob("*.md"))
    return paths


def test_every_routing_invocation_is_piped_to_append():
    violations = []
    for path in _piped_check_targets():
        if not path.is_file():
            continue
        for line in _unpiped_invocations(_read(path)):
            violations.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert violations == []


def test_synthetic_unpiped_end_line_is_flagged():
    synthetic = ('python3 "$TP_ROOT"/skills/_shared/local_route_check.py end '
                '--decisions <d>/decisions.md\n')
    assert _unpiped_invocations(synthetic) != []
    piped = (synthetic.rstrip("\n") +
            ' | python3 "$TP_ROOT"/skills/_shared/local_route_log.py append '
            '--decisions <d>/decisions.md\n')
    assert _unpiped_invocations(piped) == []


def test_synthetic_non_pipe_append_is_flagged():
    """`append` on the same line but not fed by a single `|` (`;`, `&&`, `||`,
    `|&`) is not piped — `||` runs it only when the check fails."""
    base = ('python3 "$TP_ROOT"/skills/_shared/local_route_check.py end '
            '--decisions <d>/decisions.md')
    tail = (' python3 "$TP_ROOT"/skills/_shared/local_route_log.py append '
            '--decisions <d>/decisions.md\n')
    assert _unpiped_invocations(base + " ;" + tail) != []
    assert _unpiped_invocations(base + " &&" + tail) != []
    assert _unpiped_invocations(base + " ||" + tail) != []
    assert _unpiped_invocations(base + "||" + tail) != []
    assert _unpiped_invocations(base + " |&" + tail) != []
    assert _unpiped_invocations(base + " |" + tail) == []
    assert _unpiped_invocations(base + "|" + tail) == []


def test_synthetic_operator_before_the_pipe_is_flagged():
    """Any `||`/`;`/`&&`/`&`/`|&` ANYWHERE between the check and `append`, or
    a second pipe, is not the one bare pipe — even when a `|` sits right before
    `append` (`check … || true | python3 … append` only pipes `true`)."""
    base = ('python3 "$TP_ROOT"/skills/_shared/local_route_check.py check '
            '--decisions <d>/decisions.md --scope run-start')
    tail = (' python3 "$TP_ROOT"/skills/_shared/local_route_log.py append '
            '--decisions <d>/decisions.md\n')
    for middle in (" || true |", " ; true |", " && true |", " & true |",
                   " |& true |", " | tee x |", " | cat |"):
        assert _unpiped_invocations(base + middle + tail) != [], middle
    assert _unpiped_invocations(base + " |" + tail) == []


def test_synthetic_bare_check_with_no_decisions_is_never_flagged():
    """`check` alone (no `--decisions`) is the intentional print-only Tier 1 preflight."""
    synthetic = 'python3 "$TP_ROOT"/skills/_shared/local_route_check.py check\n'
    assert _unpiped_invocations(synthetic) == []


# --- `tp-phase-implement/SKILL.md` wiring (Task 5.3) -------------------------

def test_phase_implement_4b_runs_routing():
    step4b = _section(_read(PHASE_IMPLEMENT_SKILL),
                       "4b. **Local ladder", "5. **For each task in the phase**")
    assert "routing, then the tier table with effective tiers" in step4b


def test_phase_implement_auto_advance_scope():
    bullet = _section(_read(PHASE_IMPLEMENT_SKILL),
                       "**Auto-advance across phase boundaries.**",
                       "**Retry-and-simplify on task failure")
    assert '--scope "phase <N>"' in bullet


def test_phase_implement_step9_end_once():
    step9 = _section(_read(PHASE_IMPLEMENT_SKILL),
                      "9. **Commit the phase wrap-up**", "10. **Report**")
    assert "`end`" in step9
    assert "last" in step9
    assert "never between" in step9
    assert "Interactive" in step9
    assert "read back" in step9
