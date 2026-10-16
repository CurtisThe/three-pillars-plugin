"""Structured contract checks behind the weight-class SKILL.md surfaces (dev repo only).

design: fragile-test-prevention (Part D reference integrity + frontmatter schema, phase 19).
These replace the substring pins `test_weight_class.py` held on `skills/tp-design`,
`tp-plan-audit`, `tp-design-detail`, `tp-plan` SKILL.md and on `weight-class.md` with checks on
parsed structures: the frontmatter through `skill_frontmatter`, the references through
`skill_refs`, the command spans through `skill_spans` and `argparse_probe`, and the registries
the code uses (`audit_plan.MODES`, `weight_class.VALID_CLASSES`, the design-floor validator).
No assert here reads a heading, a section or a phrase out of the prose.

Run with: pytest skills/_shared/test_weight_class_contracts.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent
REPO_ROOT = SHARED.parents[1]
SKILLS = REPO_ROOT / "skills"
PROTOCOL_DOC = SHARED / "weight-class.md"
for _dir in (SHARED, SKILLS / "tp-plan-audit" / "scripts"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

# Every SKILL.md `test_weight_class.py` read.
READ_SKILLS = ("tp-design", "tp-plan-audit", "tp-design-detail", "tp-plan")


def _skill_md(skill: str) -> Path:
    return SKILLS / skill / "SKILL.md"


def _frontmatter(skill: str) -> dict:
    """`{key: value}` of a SKILL.md, through the shipped parser."""
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    fields, issues = skill_frontmatter.parse(_skill_md(skill).read_text(encoding="utf-8"))
    assert fields is not None and issues == [], f"{skill}: unparseable frontmatter {issues}"
    return {key: value for key, (_line, value) in fields.items()}


def _invocations(skill: str, script: str) -> list[list[str]]:
    """The args of every `python3 <path>/{script} args...` command the SKILL.md shows (an inline
    code span or a fenced line) that passes at least one argument, read through `skill_spans`,
    the parser `skill_refs` reads references with."""
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for _line, span, shell in skill_spans.code_spans(_skill_md(skill).read_text(encoding="utf-8")):
        try:
            tokens = skill_spans.tokens_of(span, shell)
        except ValueError:  # a span that is not a shell command at all
            continue
        if len(tokens) > 2 and tokens[0] == "python3" and tokens[1].endswith("/" + script):
            found.append(tokens[2:])
    return found


@pytest.mark.parametrize("skill", READ_SKILLS)
def test_skill_frontmatter_passes_schema(skill):
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    assert skill_frontmatter.check(_skill_md(skill)) == []


def test_skill_and_protocol_references_resolve(tmp_path):
    """Every path, `/tp-*` skill and `python3` invocation the four SKILL.md files and the
    protocol doc name exists and parses with its script's own argparse (invariant 46's check,
    run in-suite). This is what keeps the `weight_class.py`, `weight-class.md`,
    `validate_design_floor.py` and `/tp-*` citations in them honest."""
    skill_refs = pytest.importorskip("skill_refs")
    files = [_skill_md(skill) for skill in READ_SKILLS] + [PROTOCOL_DOC]
    assert skill_refs.check(REPO_ROOT, files, cache_dir=tmp_path).issues == []


def test_design_rubric_step_calls_the_recommend_cli_with_its_own_flags(tmp_path):
    """The class-declaration step shells the rubric CLI: each `weight_class.py <subcommand> ...`
    command `/tp-design` shows parses with the script's own argparse (a missing or unknown axis
    flag is an argparse error), and one of them is the rubric's `recommend`."""
    argparse_probe = pytest.importorskip("argparse_probe")
    invocations = _invocations("tp-design", "weight_class.py")
    assert any(argv[0] == "recommend" for argv in invocations)
    for argv in invocations:
        # A value token is a placeholder (`…`) in the prose; the script's argparse needs a value.
        filled = [tok if tok.startswith("--") or i == 0 else "low" for i, tok in enumerate(argv)]
        result = argparse_probe.probe(SHARED / "weight_class.py", filled, cache_dir=tmp_path)
        assert result["status"] == "parsed", (argv, result)


def test_plan_audit_declares_every_mode_flag_the_script_implements():
    """`/tp-plan-audit --light` is the audit of a collapsed design: the frontmatter declares each
    non-standard mode `audit_plan.MODES` implements, and light is a mode that does not load
    detailed-design.md (so a light design needs design.md + plan.md only)."""
    audit_plan = pytest.importorskip("audit_plan")
    declared = set(re.findall(r"--[a-z][a-z-]*", _frontmatter("tp-plan-audit")["argument-hint"]))
    assert {f"--{mode}" for mode in audit_plan.MODES if mode != "standard"} <= declared
    assert audit_plan.MODES["light"].load_detailed is False
    assert audit_plan.MODES["standard"].load_detailed is True


def _design_md(stamp: str, *, drop: str | None = None) -> str:
    """A design.md carrying `stamp` as its weight class, every floor-required section filled
    (built from the validator's own registry), except `drop` when given."""
    validate_artifact = pytest.importorskip("validate_artifact")
    body = "A line of real content that is comfortably over the twenty character floor."
    parts = [f"---\nweight-class: {stamp}\n---\n# A design\n"]
    for name in validate_artifact.REQUIRED_SECTIONS:
        if name == drop:
            continue
        parts.append(f"## {name}\n{body}\n")
        for sub in validate_artifact.REQUIRED_SUBSECTIONS.get(name, []):
            parts.append(f"### {sub}\n{body}\n")
    return "\n".join(parts)


def _verdict(tmp_path, text: str, capsys) -> tuple[int, dict]:
    """`(exit code, the BLOCKED verdict JSON or {})` of the shipped floor validator."""
    validate_design_floor = pytest.importorskip("validate_design_floor")
    design_dir = tmp_path / "a-design"
    design_dir.mkdir(exist_ok=True)
    (design_dir / "design.md").write_text(text, encoding="utf-8")
    capsys.readouterr()
    code = validate_design_floor.main(["validate_design_floor.py", str(design_dir)])
    stderr = capsys.readouterr().err
    verdicts = [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]
    return code, (verdicts[0] if verdicts else {})


def test_floor_verdict_does_not_depend_on_the_weight_class_stamp(tmp_path, capsys):
    """A collapsed light design.md is held to the same floor as a full one (it "still has to pass
    the validator unchanged"): swapping the stamp never changes the verdict, for a design that
    meets the floor and for one that misses a required section."""
    weight_class = pytest.importorskip("weight_class")
    validate_artifact = pytest.importorskip("validate_artifact")
    missing = validate_artifact.REQUIRED_SECTIONS[-1]
    complete = [_verdict(tmp_path, _design_md(klass), capsys) for klass in weight_class.VALID_CLASSES]
    assert complete == [(0, {})] * len(weight_class.VALID_CLASSES)
    blocked = [_verdict(tmp_path, _design_md(klass, drop=missing), capsys)
               for klass in weight_class.VALID_CLASSES]
    assert all(code == 1 and verdict["missing"] == [missing] for code, verdict in blocked)


def test_generated_artifacts_are_stamped_from_design_md(tmp_path):
    """`/tp-design-detail` and `/tp-plan` stamp each artifact with design.md's class: for every
    class, an artifact stamped from `read_class(design)` is consistent with design.md, and an
    unstamped one is a finding (so the stamp step is what makes the consistency check pass)."""
    weight_class = pytest.importorskip("weight_class")
    for klass in weight_class.VALID_CLASSES:
        design_dir = tmp_path / klass
        design_dir.mkdir()
        (design_dir / "design.md").write_text("# D\n", encoding="utf-8")
        weight_class.write_class(design_dir / "design.md", klass)
        siblings = [design_dir / "detailed-design.md", design_dir / "plan.md"]
        for sibling in siblings:
            sibling.write_text("# Generated\n", encoding="utf-8")
        assert len(weight_class.check_consistency(design_dir)) == len(siblings)
        for sibling in siblings:
            weight_class.write_class(sibling, weight_class.read_class(design_dir)[0])
        assert weight_class.check_consistency(design_dir) == []
