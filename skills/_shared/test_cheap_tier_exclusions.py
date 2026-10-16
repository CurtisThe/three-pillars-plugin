"""Guard: the cheap tiers (Haiku / Sonnet) never leak outside `tp-task-worker` spawns.

The only agent files that may pin a cheap frontmatter model are the task-worker variants
and `tp-runbook` / `tp-drafter*` / `tp-explainer` (the other cheap-pinned agents).

design: local-implement-and-review (Task 6.1), beside `test_review_models_opus.py`.

`--local` lets an implement dispatcher run one plan task on a cheaper model, but only
through a `tp-task-worker` spawn. Everything that reviews, audits, designs, orchestrates
or merges stays on Opus:

- council-*, `tp-readonly-auditor`, `tp-impl-auditor` and `tp-generator` declare exactly `model: opus` (read with
  `weight_class.parse_frontmatter`: last duplicate key wins, an absent or unclosed block
  has no model, and any other spelling fails), and the review-only agents carry no
  cheap model pin anywhere in the file;
- no audit / council / design / orchestrator / merge / phase-review SKILL.md pins a
  cheap model at all;
- in the implement-side dispatch docs (`tp-phase-implement/SKILL.md`,
  `_shared/local-dispatch.md`, `agents/tp-worker.md`, `_shared/cheap-dispatch.md`) every
  cheap pin sits inside an `Agent(...)` spawn whose `subagent_type` is `tp-task-worker`.

A "cheap pin" is a model-selection literal (`model="haiku"`, `model: sonnet`,
`"model": "haiku"`, `'model': sonnet`, `claude-sonnet-*`), not the bare word, so prose may still name the
ladder rungs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import skill_text
from weight_class import parse_frontmatter

ROOT = Path(__file__).resolve().parent.parent.parent
CHEAP_PIN_RE = re.compile(
    r"""["']?model["']?\s*[=:]\s*["']?(?:haiku|sonnet)\b["']?|claude-(?:haiku|sonnet)""",
    re.I,
)
OPUS_AGENT_GLOBS = ("council-*.md", "tp-readonly-auditor.md",
                    "tp-impl-auditor.md", "tp-generator.md")
REVIEW_AGENT_GLOBS = ("council-*.md", "tp-readonly-auditor.md", "tp-impl-auditor.md")
CHEAP_AGENT_ALLOW = ("tp-task-worker*.md", "tp-runbook.md", "tp-drafter*.md", "tp-spawn-host.md", "tp-explainer.md",
                     "tp-worker.md")
CHEAP_MODEL_RE = re.compile(r"(?:haiku|sonnet)\b|claude-(?:haiku|sonnet)", re.I)
GUARDED_SKILL_GLOBS = ("*-audit", "council", "tp-design*", "tp-run-full-design", "tp-merge*",
                       "tp-phase-review")
SPAWN_DOCS = ("skills/tp-phase-implement/SKILL.md", "skills/_shared/local-dispatch.md",
              "agents/tp-worker.md", "skills/_shared/cheap-dispatch.md")
# `{agent_ref}` is local-dispatch.md's spawn field: the resolved `<plugin>:tp-task-worker-<rung>`.
TASK_WORKER_RE = re.compile(r"""subagent_type\s*=\s*(["'])(?:\{agent_ref\}|(?:[a-z-]+:)?tp-task-worker(?:-\{rung\}|-(?:local|sonnet)-(?:medium|xhigh))?)\1""")
CANONICAL_MODEL = "opus"


def _frontmatter_model(text: str) -> str | None:
    """The raw frontmatter `model` value; None when the block is absent or unclosed."""
    return parse_frontmatter(text).get("model")


def _frontmatter_block(text: str) -> str:
    """The closed leading `---` block's body; "" when absent or unclosed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[1:i])
    return ""


def _body(text: str) -> str:
    """`text` without its leading frontmatter block (an agent's own `model:` line is its pin)."""
    block = _frontmatter_block(text)
    return text.split("---", 2)[2] if block and text.startswith("---") else text


def _agent_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of every paren-balanced `Agent(...)` call in `text`."""
    spans = []
    for m in re.finditer(r"\bAgent\(", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        spans.append((m.start(), i + 1))
    return spans


def _outside_task_worker(text: str) -> list[str]:
    """Cheap pins that are not inside an `Agent(...)` spawn of `tp-task-worker`."""
    allowed = [(s, e) for s, e in _agent_spans(text) if TASK_WORKER_RE.search(text[s:e])]
    return [m.group(0) for m in CHEAP_PIN_RE.finditer(text)
            if not any(s <= m.start() < e for s, e in allowed)]


def _globbed(base: Path, patterns: tuple[str, ...]) -> list[Path]:
    return sorted({p for pat in patterns for p in base.glob(pat)})


def find_violations(root: Path) -> list[str]:
    """Every cheap-tier leak under `root`, as `<rel path>: <reason>` strings."""
    out: list[str] = []

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    for path in _globbed(root / "agents", OPUS_AGENT_GLOBS):
        text = path.read_text(encoding="utf-8")
        model = _frontmatter_model(text)
        if model != CANONICAL_MODEL:
            out.append(f"{rel(path)}: frontmatter model is {model!r}, not opus")
        # parse_frontmatter skips quoted keys and reads lines inside multi-line scalars,
        # so a cheap pin anywhere in the block is a violation even when it said "opus".
        out += [f"{rel(path)}: cheap pin {m.group(0)!r} in frontmatter"
                for m in CHEAP_PIN_RE.finditer(_frontmatter_block(text))]
    for path in _globbed(root / "agents", REVIEW_AGENT_GLOBS):
        out += [f"{rel(path)}: cheap pin {m.group(0)!r}"
                for m in CHEAP_PIN_RE.finditer(path.read_text(encoding="utf-8"))]
    allowed = set(_globbed(root / "agents", CHEAP_AGENT_ALLOW))
    for path in sorted((root / "agents").glob("*.md")):
        model = _frontmatter_model(path.read_text(encoding="utf-8")) or ""
        if path not in allowed and CHEAP_MODEL_RE.search(model):
            out.append(f"{rel(path)}: cheap frontmatter model {model!r} not allowed here")
    for skill_dir in _globbed(root / "skills", GUARDED_SKILL_GLOBS):
        path = skill_dir / "SKILL.md"
        if path.is_file():
            body = (skill_text.read_skill_text(skill_dir.name, root)
                    if skill_dir.name == "tp-run-full-design" else path.read_text(encoding="utf-8"))
            out += [f"{rel(path)}: cheap pin {m.group(0)!r}"
                    for m in CHEAP_PIN_RE.finditer(body)]
    for doc in SPAWN_DOCS:
        path = root / doc
        if path.is_file():
            out += [f"{doc}: cheap pin {hit!r} outside a tp-task-worker spawn"
                    for hit in _outside_task_worker(_body(path.read_text(encoding="utf-8")))]
    return out


def _write(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_guard_flags_synthetic_violation(tmp_path):
    _write(tmp_path, "agents/council-x.md", "---\nname: council-x\nmodel: sonnet\n---\nbody\n")
    _write(tmp_path, "agents/tp-generator.md", "---\nname: council-x\nmodel: opus\n---\nbody\n")
    _write(tmp_path, "skills/tp-phase-implement/SKILL.md",
           'Local rung:\n\nAgent(subagent_type="tp-task-worker", model="haiku", prompt=p)\n\n'
           'Leak:\n\nAgent(\n  subagent_type="general-purpose",\n  model="haiku",\n)\n')
    _write(tmp_path, "skills/tp-plan-audit/SKILL.md", 'Spawn `Agent(model="sonnet")` here.\n')
    _write(tmp_path, "skills/tp-guide/SKILL.md", 'Unguarded: model="haiku".\n')
    got = find_violations(tmp_path)
    assert "agents/council-x.md: frontmatter model is 'sonnet', not opus" in got
    assert ("skills/tp-phase-implement/SKILL.md: cheap pin 'model=\"haiku\"' outside a "
            "tp-task-worker spawn") in got
    assert "skills/tp-plan-audit/SKILL.md: cheap pin 'model=\"sonnet\"'" in got
    # The tp-task-worker spawn and the unguarded skill are not violations.
    assert sum("tp-phase-implement" in v for v in got) == 1
    assert not any("tp-guide" in v for v in got)


def test_cheap_agent_allowlist(tmp_path):
    _write(tmp_path, "agents/tp-foo.md", "---\nname: tp-foo\nmodel: haiku\n---\nb\n")
    _write(tmp_path, "agents/tp-runbook.md", "---\nname: tp-runbook\nmodel: haiku\n---\nb\n")
    _write(tmp_path, "agents/tp-task-worker-x.md", "---\nname: x\nmodel: sonnet\n---\nb\n")
    for name in ("tp-drafter", "tp-drafter-xhigh"):  # cheap-tier-offload 3.1
        _write(tmp_path, f"agents/{name}.md", f"---\nname: {name}\nmodel: haiku\n---\nb\n")
    got = find_violations(tmp_path)

    assert got == ["agents/tp-foo.md: cheap frontmatter model 'haiku' not allowed here"]


def _agent_violations(tmp_path, frontmatter: bytes, name: str = "council-x.md") -> list[str]:
    """Write a guarded agent `agents/<name>` byte-exact; return its guard violations."""
    path = tmp_path / "agents" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frontmatter)
    return [v for v in find_violations(tmp_path) if v.startswith(f"agents/{name}")]


def test_duplicate_model_key_uses_the_last_value(tmp_path):
    # YAML and Claude Code take the last duplicate key, so this agent runs on sonnet.
    got = _agent_violations(tmp_path, b"---\nname: council-x\nmodel: opus\nmodel: sonnet\n---\nb\n")
    assert "agents/council-x.md: frontmatter model is 'sonnet', not opus" in got


def test_crlf_frontmatter_is_read(tmp_path):
    crlf = b"---\r\nname: council-x\r\nmodel: opus\r\n---\r\nb\r\n"
    assert _agent_violations(tmp_path, crlf) == []
    # The reader itself, on text that kept its CRs (read_text() would translate them).
    assert _frontmatter_model(crlf.decode()) == "opus"


def test_unclosed_frontmatter_has_no_model(tmp_path):
    got = _agent_violations(tmp_path, b"---\nname: council-x\nmodel: opus\nbody, no closing fence\n")
    assert got == ["agents/council-x.md: frontmatter model is None, not opus"]


@pytest.mark.parametrize("line", [
    'model: "opus"', "model: 'opus'", "model: opus # default", "model: Opus",
    "model: claude-opus-4-1", "model: inherit", "name: council-x",
])
def test_only_the_canonical_model_value_passes(tmp_path, line):
    assert _agent_violations(tmp_path, f"---\n{line}\n---\nb\n".encode()) != []
    assert _agent_violations(tmp_path, b"---\nmodel:   opus  \n---\nb\n") == []


# YAML reads each of these as a cheap model; parse_frontmatter skips the quoted key and
# takes the `model: opus` line inside the multi-line description scalar.
_SCALAR_HIDES_PIN = b'---\nname: council-x\ndescription: "a\nmodel: opus\nb"\n"model": sonnet\n---\nbody\n'


@pytest.mark.parametrize("name,raw", [
    ("council-x.md", _SCALAR_HIDES_PIN),
    ("council-x.md", b"---\nname: council-x\nmodel: opus\n'model': haiku\n---\nbody\n"),
    ("tp-generator.md", _SCALAR_HIDES_PIN.replace(b"council-x", b"tp-generator")),
], ids=["double-quoted-key-after-scalar", "single-quoted-key", "tp-generator"])
def test_quoted_model_key_cheap_pin_is_flagged(tmp_path, name, raw):
    assert _agent_violations(tmp_path, raw, name) != []


@pytest.mark.parametrize("spawn", [
    'Agent(subagent_type="tp-task-worker", model="haiku")',
    "Agent(subagent_type='tp-task-worker', model=\"haiku\")",
    'Agent(subagent_type = "tp-task-worker", model="haiku")',
    'Agent(subagent_type="tp-task-worker-{rung}", model="haiku")',
    'Agent(subagent_type="tp-task-worker-local-medium", model="haiku")',
    "Agent(subagent_type='tp-task-worker-sonnet-xhigh', model=\"haiku\")",
])
def test_task_worker_spawn_accepts_either_quote_style(spawn):
    assert _outside_task_worker(f"Local rung:\n\n{spawn}\n") == []


def test_task_worker_re_rejects_other_variant():
    assert TASK_WORKER_RE.search('subagent_type="tp-task-worker-opus-xhigh"') is None


def test_repo_has_no_cheap_tier_leak():
    agents = _globbed(ROOT / "agents", OPUS_AGENT_GLOBS)
    skills = [d for d in _globbed(ROOT / "skills", GUARDED_SKILL_GLOBS) if (d / "SKILL.md").is_file()]
    assert len(agents) >= 20 and len(skills) >= 10, "guard globs matched too little"
    assert find_violations(ROOT) == []


# --- cheap-tier-offload Task 1.3: the slot table never loosens ------------------------
# ROOT is the plugin tree, so these guard the shipped table and schema; a consumer
# config is refused at runtime (the Tier 1 load_slots preflight, spec exit 2).

import json  # noqa: E402

import cheap_tier  # noqa: E402
import model_policy  # noqa: E402


def test_cheap_slots_never_overlap_excluded_or_roles():
    assert set(cheap_tier.SLOTS) & cheap_tier.EXCLUDED == set()
    assert set(cheap_tier.SLOTS) & set(model_policy.ROLES) == set()


def test_gate_and_pinned_agent_roles_are_excluded():
    pinned = {role for role, source, _eff in model_policy.AGENTS.values()
              if not source.startswith("rung:")}
    # council members (audit-member) are cheap now (one-cheap-engine 1.1); the synth stays.
    # spawn-host: the spawn host is a fixed-Sonnet shell, never cheap-tier routed
    # The explainer drafter (agent tp-explainer, role `explainer`) is cheap too: classed
    # `cheap` in cheap_classes, not EXCLUDED (explainer-agent, one-cheap-engine base-sync).
    need = (set(model_policy.GATE_ROLES) | pinned) - {"task", "audit-member", "spawn-host", "explainer", "review_finder"}
    # Fixed prefix: the certifier's RED marker (a computed message alone prints no stable text).
    assert need <= cheap_tier.EXCLUDED, (
        f"gate or pinned agent roles missing from cheap_tier.EXCLUDED: {sorted(need - cheap_tier.EXCLUDED)}")


def test_effectful_slots_are_code():
    for name, row in cheap_tier.SLOTS.items():
        if row.effect == "effectful":
            assert row.kind == "code", name


def test_repo_config_loads_slots_cleanly():
    path = ROOT / ".three-pillars" / "config.json"
    if not path.is_file():
        pytest.skip("no .three-pillars/config.json in this tree")
    cheap_tier.load_slots(json.loads(path.read_text(encoding="utf-8")))


def test_schema_models_match_the_slot_table():
    schema = json.loads((ROOT / "skills" / "_shared" / "repo-config.schema.json")
                        .read_text(encoding="utf-8"))
    models = schema["properties"]["models"]
    assert models["additionalProperties"] is False
    props = models["properties"]
    assert set(props) - set(model_policy.ROLES) == set(cheap_tier.SLOTS)
    for name, row in cheap_tier.SLOTS.items():
        assert tuple(props[name]["enum"]) == (*row.rungs, "off"), name
        assert props[name].get("description"), name
