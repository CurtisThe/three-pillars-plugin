"""Structured contract checks for `skills/tp-run-full-design/SKILL.md` (dev repo only).

design: fragile-test-prevention (Part D reference integrity + frontmatter schema, Part E
cleanup, phases 16 and 17). These replace substring pins on the SKILL.md with checks on
parsed structures: the frontmatter through `skill_frontmatter`, the references through
`skill_refs`, the command spans through `skill_spans`, the registries the code uses
(`design_run_command`, `model_policy.AGENTS`, `pipeline_modes`, `agent_ref`), and the handoff
worklist through `handoffs_ignore` and `parse_tier_return`. No assert here reads a heading, a
section or a phrase out of the prose.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = SCRIPTS.parent / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
AGENTS_DIR = REPO_ROOT / "agents"
AUDIT_SCHEMA = SCRIPTS.parent / "schemas" / "audit-return.v1.json"
HANDOFF_SCHEMA = SCRIPTS.parent / "schemas" / "handoff.v1.json"
for _dir in (REPO_ROOT / "skills" / "_shared", SCRIPTS):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import skill_text  # noqa: E402

# The dispatch roles of `model_policy.AGENTS` whose agents the orchestrator spawns: the
# slot template's generator, the Slot 7 worker, and the audit fan-out's reader, council
# personas and implementation synthesizer.
SLOT_ROLES = ("generator", "phase-worker", "reader", "audit-member", "impl-audit")
AUDIT_ROLES = ("reader", "audit-member", "impl-audit")
# Claude Code's file-modifying tools: an audit agent is read-only, so none may be granted.
WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


def _frontmatter(path: Path) -> dict:
    """`{key: value}` of a SKILL.md or agent file, through the shipped parser."""
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    fields, issues = skill_frontmatter.parse(path.read_text(encoding="utf-8"))
    assert fields is not None and issues == [], f"{path.name}: unparseable frontmatter {issues}"
    return {key: value for key, (_line, value) in fields.items()}


def _invocations(script: str) -> list[list[str]]:
    """The args of every `python3 <path>/{script} ...` command the SKILL.md shows (an inline code
    span or a fenced line), read through `skill_spans`, the parser `skill_refs` reads references with."""
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for _line, span, shell in skill_spans.code_spans(skill_text.read_skill_text("tp-run-full-design")):
        try:
            tokens = skill_spans.tokens_of(span, shell)
        except ValueError:  # a span that is not a shell command at all
            continue
        if len(tokens) > 1 and tokens[0] == "python3" and tokens[1].endswith("/" + script):
            found.append(tokens[2:])
    return found


def _agents_for(roles: tuple[str, ...]) -> list[str]:
    """Every agent file whose `model_policy.AGENTS` row is one of `roles` (globs expanded)."""
    model_policy = pytest.importorskip("model_policy")
    stems = sorted(path.stem for path in AGENTS_DIR.glob("*.md"))
    return sorted({stem for pattern, (role, _source, _effort) in model_policy.AGENTS.items()
                   if role in roles for stem in stems if fnmatch.fnmatchcase(stem, pattern)})


def test_skill_frontmatter_passes_schema():
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    assert skill_frontmatter.check(SKILL_MD) == []


def test_skill_references_resolve(tmp_path):
    """Every path, `/tp-*` skill and `python3` invocation the SKILL.md spans name exists
    and parses with its script's own argparse (invariant 46's check, run in-suite)."""
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(REPO_ROOT, skill_text.skill_paths("tp-run-full-design"),
                              cache_dir=tmp_path)
    assert report.issues == []


def test_launcher_flags_are_declared_in_argument_hint():
    """A flag the shipped launchers pass to the skill must be one its frontmatter declares."""
    drc = pytest.importorskip("design_run_command")
    fields = _frontmatter(SKILL_MD)
    declared = set(re.findall(r"--[a-z][a-z-]*", fields["argument-hint"]))
    commands = [
        drc.slash_command("a-design", mode="build", skip_design=True, local=True, cheap_tier="ab"),
        drc.slash_command("a-design", cheap_tier="on"),
        drc.resume_command("a-design --skip-design --local", drc.RESUME_STAGES[0]),
    ]
    for command in commands:
        argv = shlex.split(command)
        assert argv[0] == "/" + fields["name"]
        emitted = {token.split("=", 1)[0] for token in argv if token.startswith("--")}
        assert emitted <= declared, f"{command!r} passes undeclared flags {sorted(emitted - declared)}"


def test_whole_run_token_cap_is_a_declared_flag():
    """`--max-tokens` is the interface of the whole-run token cap: the frontmatter declares it."""
    fields = _frontmatter(SKILL_MD)
    declared = set(re.findall(r"--[a-z][a-z-]*", fields["argument-hint"]))
    assert "--max-tokens" in declared


def test_review_request_flags_are_declared_in_argument_hint():
    """The completion PR's review request is steered by `--pr-reviewers <list>` (who to ask),
    `--no-review` (ask nobody) and `--no-iterate` (stop at the opened PR): the frontmatter
    declares all three, and the reviewer flag takes a value."""
    hint = _frontmatter(SKILL_MD)["argument-hint"]
    declared = set(re.findall(r"--[a-z][a-z-]*", hint))
    assert {"--pr-reviewers", "--no-review", "--no-iterate"} <= declared
    assert re.search(r"--pr-reviewers\s+<[^>]+>", hint)


def test_mode_flag_declares_every_pipeline_mode():
    """`--mode` picks the slot-range window of the run: the frontmatter declares it with exactly the
    modes `pipeline_modes` implements, and a run given neither `--mode` nor a pickup value is `full`."""
    pipeline_modes = pytest.importorskip("pipeline_modes")
    declared = re.search(r"--mode\s+\{([^}]*)\}", _frontmatter(SKILL_MD)["argument-hint"])
    assert declared is not None, "--mode must be declared with its value set ({a|b|...})"
    assert set(declared.group(1).split("|")) == set(pipeline_modes.VALID_MODES)
    assert pipeline_modes.resolve_mode() == "full"


def test_light_audit_flag_is_declared_by_plan_audit():
    """The light slot mapping merges Slots 4 and 6 into one audit through `/tp-plan-audit --light`,
    so that skill's frontmatter must declare the flag."""
    assert "--light" in re.findall(r"--[a-z][a-z-]*", _frontmatter(
        REPO_ROOT / "skills" / "tp-plan-audit" / "SKILL.md")["argument-hint"])


def test_briefing_emit_is_a_cli_step_that_never_serves():
    """The per-tier briefing refresh shells `emit_run_briefing.py` with the tier id and the running
    token total (`skill_refs` checks every flag is the script's own), and never `--serve`: serving
    is the human-initiated, blocking surface, which would hang the unattended loop."""
    invocations = _invocations("emit_run_briefing.py")
    assert invocations, "the orchestrator must run emit_run_briefing.py after each tier"
    for argv in invocations:
        flags = {token.split("=", 1)[0] for token in argv if token.startswith("--")}
        assert {"--tier", "--tokens"} <= flags, argv
        assert "--serve" not in flags, argv


def test_orphan_branch_sweep_is_a_cli_step_of_the_exit_path():
    """The Option B backstop: the SKILL.md shells `sweep_orphan_branches.py`, the always-exit-0
    wrapper over the name-guarded `worktree-agent-*` sweep (`skill_refs` checks that the script
    exists and that every flag the invocation passes is its own)."""
    invocations = _invocations("sweep_orphan_branches.py")
    assert invocations, "the orchestrator must run sweep_orphan_branches.py on its exit path"
    assert (SCRIPTS / "sweep_orphan_branches.py").is_file()


def test_audit_retry_budget_is_a_declared_flag_that_retries_by_default():
    """`--max-attempts` bounds each self-healing cycle: the frontmatter declares it, and its
    declared default is above 1, since 1 would escalate a `needs-work` audit on first rejection."""
    hint = _frontmatter(SKILL_MD)["argument-hint"]
    declared = re.search(r"--max-attempts\s+N=(\d+)", hint)
    assert declared is not None, "--max-attempts must be declared with a default (N=<int>)"
    assert int(declared.group(1)) > 1


def test_finding_confidence_never_gates_the_audit_retry():
    """Findings of every confidence the audit-return schema allows reach the orchestrator whole
    through the clip point (`parse_tier_return`), and the retry predicate reads severity, not confidence."""
    parse_tier_return = pytest.importorskip("parse_tier_return")
    audit_retry_rules = pytest.importorskip("audit_retry_rules")
    schema = json.loads(AUDIT_SCHEMA.read_text(encoding="utf-8"))
    confidences = schema["properties"]["findings"]["items"]["properties"]["confidence"]["enum"]
    assert len(confidences) > 1
    for confidence in confidences:
        for severity, lows_only in (("minor", True), ("major", False)):
            findings = [{"confidence": confidence, "severity": severity, "category": "logic",
                         "description": "d", "suggested_fix": "f"}]
            envelope = {"schema": schema["properties"]["schema"]["const"], "slot": "design-audit",
                        "status": "needs-work", "summary": "s", "verdict": "needs-work",
                        "findings": findings}
            reply = "scratch reasoning\n```json\n" + json.dumps(envelope) + "\n```\n"
            assert parse_tier_return.parse_tier_return(reply, str(AUDIT_SCHEMA)) == envelope
            assert audit_retry_rules.lows_only(findings) is lows_only, (confidence, severity)


def test_slot_agents_are_valid_and_resolve():
    """The agent each slot dispatch names exists, has valid frontmatter, and resolves to a spawn reference."""
    agent_ref = pytest.importorskip("agent_ref")
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    for role in SLOT_ROLES:
        names = _agents_for((role,))
        assert names, f"no agent file for the {role!r} dispatch role"
        for name in names:
            assert skill_frontmatter.check(AGENTS_DIR / f"{name}.md") == [], name
            assert agent_ref.resolve(name, REPO_ROOT).endswith(f":{name}")


def test_audit_agents_are_read_only():
    """The audit fan-out's reader, council personas and synthesizer share `tp/{slug}` read-only,
    so none of their agent files grants a file-modifying tool (and each lists its tools)."""
    for name in _agents_for(AUDIT_ROLES):
        raw = _frontmatter(AGENTS_DIR / f"{name}.md").get("tools")
        assert raw is not None, f"{name} lists no tools, so it would inherit every tool"
        tools = json.loads(raw)
        assert not WRITE_TOOLS & set(tools), f"{name} grants {sorted(WRITE_TOOLS & set(tools))}"


def test_handoff_worklist_is_committable_and_cold_resumable(tmp_path):
    """A pre-split checkpoint is a worklist `.handoffs/{slot}-{attempt}-{N}.md` under
    `tp-designs/{slug}/`: git would commit it (the shipped ignore rules keep the `.md` and
    ignore the round-bundle JSON beside it), and a cold resume recovers the partial state,
    next action, files and remaining budget from its embedded `handoff.v1` envelope."""
    handoffs_ignore = pytest.importorskip("handoffs_ignore")
    parse_tier_return = pytest.importorskip("parse_tier_return")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True,
                              capture_output=True, text=True).stdout

    git("init", "-q")
    handoffs_ignore.apply(tmp_path)
    folder = tmp_path / "three-pillars-docs" / "tp-designs" / "a-design" / ".handoffs"
    folder.mkdir(parents=True)
    envelope = {"schema": "tp-run-full-design/handoff/v1", "slot": "plan-audit", "attempt": 2,
                "partial_state": "dimensions 1-2 audited", "next_action": "audit dimension 3",
                "files_to_continue_with": ["three-pillars-docs/tp-designs/a-design/plan.md"],
                "remaining_budget_estimate": 90000}
    worklist = folder / f"{envelope['slot']}-{envelope['attempt']}-3.md"
    worklist.write_text("# Checkpoint\n\n```json\n" + json.dumps(envelope) + "\n```\n", encoding="utf-8")
    (folder / "round1-bundle.json").write_text("{}", encoding="utf-8")

    committable = git("ls-files", "--others", "--exclude-standard").splitlines()
    assert worklist.relative_to(tmp_path).as_posix() in committable
    assert not [path for path in committable if path.endswith("round1-bundle.json")]
    assert parse_tier_return.parse_tier_return(worklist.read_text(encoding="utf-8"),
                                               HANDOFF_SCHEMA) == envelope
