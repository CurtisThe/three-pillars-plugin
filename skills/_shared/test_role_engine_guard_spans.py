"""test_role_engine_guard_spans.py — the `Agent(` spans in the routed prose name opus or role_engine.

design: local-role-routing (Task 7.2)

`test_role_engine_guard.py` guards the code. This guards the prose the orchestrator copies:
every `Agent(` code span in the two new docs (`council/strata-members.md`,
`tp-pr-iterate/strata-finders.md`), in `round-topology.md` and in the four pointer sites
(the two council fan-out SKILLs, `tp-plan-audit/SKILL.md`, `tp-pr-iterate/SKILL.md`,
`tp-run-full-design/SKILL.md`) is read with `skill_spans.spans` — the same helper
`test_review_models_opus._agent_spans` uses — and must satisfy one predicate:

- a span that names a model names `opus`, or
- a council-member / finder / scout spawn whose `model=` is a placeholder SOURCED FROM
  `role_engine` (it names `role_engine`, one of `model_policy.ENGINE_ROLES`, or the round
  manifest's `dispatch_model`) — the only way a routed role may leave Opus, and
- a span that names no model at all (the harness default, pinned in prose beside the span;
  e.g. the `Agent(...)` meta-mentions and the `tp-worker` dispatch).

A literal model that is not `opus` is refused whatever the span spawns: the allow-list is
the placeholder, never a hand-written downgrade. The fixture tests below pin both halves —
a synth span pinned to `haiku` fails, and the same span on `opus` passes.

`skill_spans` is `dev_only_shared` in the release-tier manifest, so it is
`importorskip`ped inside the helper, never imported at module top: the shipped collect-only
pass (`test_shipped_module_imports.py`) has no such file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import model_policy  # noqa: E402
import skill_text  # noqa: E402

REPO_ROOT = HERE.parents[1]

# The new prose, the topology doc, and every site 4.3 / 6.9 edited with a pointer.
DOC_SITES = (
    "skills/council/strata-members.md",
    "skills/tp-pr-iterate/strata-finders.md",
    "skills/tp-pr-iterate/round-topology.md",
    "skills/council/SKILL.md",
    "skills/tp-plan-audit/SKILL.md",
    "skills/tp-pr-iterate/SKILL.md",
    "skills/tp-run-full-design/SKILL.md",
)

# `model=` / `model:` and its value up to the next top-level comma or close paren. `\b` keeps
# `dispatch_model` from reading as a second kwargs.
_MODEL_KW = re.compile(r"\bmodel\s*[=:]\s*([^,)]*)")
_OPUS = re.compile(r"opus", re.I)
# A bare model word (`opus`, `haiku`, `sonnet`, `local`) — a hand-written model, not a source.
_LITERAL_MODEL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
# The three routable roles, the resolver itself, and the manifest field a routed model arrives in.
_ROLE_SOURCE = re.compile(
    r"role_engine|dispatch_model|" + "|".join(model_policy.ENGINE_ROLES), re.I)
# The spawn shapes those roles take in prose: a council member, a review angle, the scout /
# Opus-check agent, and the round-manifest fan-out that dispatches what `prepare` recorded.
_ENGINE_SPAWN = re.compile(
    r'agent_ref\("council-'
    r'|agent_ref\("<[^">]*>"\)'
    r'|agent_ref\("tp-review-confirmer"\)'
    r"|subagent_type=<the entry's agent_ref>"
    # the engine-sourced ref: the agent `strata_effort.py spawn <base>` prints (the effort variant)
    r"|subagent_type=<the agent_ref printed by strata_effort\.py spawn [^>]*>")


def _model_values(text: str) -> list[str]:
    """Each `model=` value in an `Agent(` span, unquoted."""
    return [m.group(1).strip().strip("\"'") for m in _MODEL_KW.finditer(text)]


def role_engine_model(value: str) -> bool:
    """True iff a `model=` value is a placeholder sourced from `role_engine`, not a literal."""
    return _LITERAL_MODEL.fullmatch(value) is None and _ROLE_SOURCE.search(value) is not None


def span_offender(text: str) -> str | None:
    """Why an `Agent(` span text breaks the rule, or None when the span is allowed."""
    for value in _model_values(text):
        if _OPUS.fullmatch(value):
            return None
        if _LITERAL_MODEL.fullmatch(value):
            return f'pins model="{value}"'
        if role_engine_model(value) and _ENGINE_SPAWN.search(text):
            return None
        return f'model="{value}" is neither opus nor a role_engine-sourced model'
    return None


def _agent_spans(path: Path) -> list[tuple[int, str]]:
    skill_spans = pytest.importorskip("skill_spans")
    if path == REPO_ROOT / "skills/tp-run-full-design/SKILL.md":
        text = skill_text.read_skill_text("tp-run-full-design")
    else:
        text = path.read_text(encoding="utf-8")
    return [(n, t) for n, t in skill_spans.spans(text) if t.startswith("Agent(")]


def _offenders(rel: str) -> list[str]:
    out = []
    for line, text in _agent_spans(REPO_ROOT / rel):
        why = span_offender(text)
        if why:
            out.append(f"{rel}:{line} {why} — {text}")
    return out


def _routed(rel: str) -> int:
    """How many spans in `rel` take a role_engine-sourced model placeholder."""
    return sum(1 for _, t in _agent_spans(REPO_ROOT / rel)
               if any(role_engine_model(v) for v in _model_values(t)))


# --- the prose sites -------------------------------------------------------
@pytest.mark.parametrize("rel", DOC_SITES, ids=lambda s: s.replace("/", "-"))
def test_every_agent_span_in_the_routed_prose_is_allowed(rel):
    assert _offenders(rel) == []


def test_the_scan_is_not_vacuous():
    """The two new docs each carry a routed spawn, so the predicate has real spans to clear."""
    assert _routed("skills/council/strata-members.md") >= 1
    assert _routed("skills/tp-pr-iterate/strata-finders.md") >= 2
    assert _routed("skills/tp-pr-iterate/SKILL.md") >= 1


def test_the_routed_docs_actually_have_agent_spans():
    for rel in ("skills/council/strata-members.md", "skills/tp-pr-iterate/strata-finders.md"):
        assert _agent_spans(REPO_ROOT / rel), rel


# --- the predicate, pinned by fixtures -------------------------------------
_SYNTH_MD = """## Synthesizer

`Agent(subagent_type=agent_ref("tp-readonly-auditor"), model="{model}", prompt=<the synth brief>)`
"""


def _synth_offenders(tmp_path, model: str) -> list[str]:
    md = tmp_path / "synth.md"
    md.write_text(_SYNTH_MD.format(model=model), encoding="utf-8")
    return [f"{n} {t}" for n, t in _agent_spans(md) if span_offender(t)]


def test_a_synth_span_pinned_to_haiku_fails(tmp_path):
    """The RED evidence: a judgment span that hands the synthesizer to the local model."""
    offenders = _synth_offenders(tmp_path, "haiku")
    assert len(offenders) == 1 and 'model="haiku"' in offenders[0], offenders


def test_the_same_span_on_opus_passes(tmp_path):
    """Non-vacuity: the fixture's shape is legal, only its pinned model is not."""
    assert _synth_offenders(tmp_path, "opus") == []


@pytest.mark.parametrize("model", ["haiku", "sonnet", "local", "strata"])
def test_a_literal_model_on_an_engine_role_span_is_still_refused(model):
    """The allow-list is the placeholder, never a hand-written model on a member or finder."""
    span = ('Agent(subagent_type=agent_ref("council-<n>"), '
            f'model="{model}", prompt=<the member prompt>)')
    assert span_offender(span) is not None


def test_a_member_spawn_on_a_role_engine_placeholder_is_allowed():
    span = ('Agent(subagent_type=agent_ref("council-<n>"), '
            'model="<model from role_engine resolve>", prompt=<the member prompt>)')
    assert span_offender(span) is None


def test_a_role_engine_placeholder_on_a_judgment_span_is_refused():
    """The narrow half of the allow-list: the spawn must be a member, finder or scout."""
    span = ('Agent(subagent_type=agent_ref("tp-impl-auditor"), '
            'model="<model from role_engine resolve>", prompt=<the audit brief>)')
    assert span_offender(span) is not None


def test_a_span_that_names_no_model_is_allowed():
    """The pre-existing default-model dispatches and the `Agent(...)` meta-mentions."""
    for span in ('Agent(subagent_type=agent_ref("tp-worker"), isolation="worktree")',
                 "Agent(...)", "Agent()"):
        assert span_offender(span) is None, span


def test_a_strata_effort_spawn_ref_with_a_role_engine_model_is_allowed():
    span = ("Agent(subagent_type=<the agent_ref printed by strata_effort.py spawn council-<n>>, "
            'model="<model from role_engine resolve>", prompt=<the member prompt>)')
    assert span_offender(span) is None


def test_a_role_engine_model_without_an_engine_sourced_agent_is_refused():
    """The model placeholder alone never clears a span: the agent must be engine-sourced too."""
    for agent in ("<the agent_ref printed by the planner>", "<any agent>",
                  'agent_ref("tp-impl-auditor")'):
        span = (f"Agent(subagent_type={agent}, "
                'model="<model from role_engine resolve>", prompt=<the brief>)')
        assert span_offender(span) is not None, agent
