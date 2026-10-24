"""test_living_doc_fragments_md.py — Task 1.11: the protocol doc's examples and the learn skills' wiring.

design: living-doc-fragments, Task 1.11. Oracle: example. Structure only (skills/_shared/test-fragility.md):
the protocol's fenced examples are labelled ``fragment <name>`` and parsed by the real grammar; each learn
SKILL.md is read through ``skill_invocations`` (its code spans, never its prose), checked by
``skill_refs.check`` and, for the command it holds, run on a fixture. No test pins wording.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

pytest.importorskip("skill_spans")  # dev-only modules: a plugin copy skips this file
skill_refs = pytest.importorskip("skill_refs")
import changes_fragment as cf  # noqa: E402
from skill_invocations import invocations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "skills" / "_shared" / "living-doc-fragments.md"
LEARN_SKILLS = ("tp-design-learn", "tp-spike-learn")
FILL = {"design-name": "demo", "spike-name": "demo"}
_EXAMPLE = re.compile(r"^```fragment[ \t]+(\S+)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
LEARNED_FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\nlearned: 2026-10-22\n---\n"
BARE_FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n"


def _examples() -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _EXAMPLE.finditer(PROTOCOL.read_text(encoding="utf-8"))}


def _validate_calls(skill: str) -> list[list[str]]:
    calls = invocations(ROOT / "skills" / skill / "SKILL.md", "changes_fragment.py", fill=FILL, root=ROOT)
    return [c for c in calls if c[2:3] == ["validate"]]


def test_protocol_examples_validate():
    examples = _examples()
    assert {"full", "frontmatter-only", "registration"} <= set(examples), sorted(examples)
    for label, text in examples.items():
        fragment = cf.parse(text)
        assert cf.validate(fragment) == [], (label, [cf.format_problem(p) for p in cf.validate(fragment)])
    full, bare, registration = (cf.parse(examples[k]) for k in ("full", "frontmatter-only", "registration"))
    assert set(full.sections) == set(cf.SECTIONS)
    assert bare.sections == {} and bare.slug
    assert set(registration.sections) == {"Roadmap"}
    # `learned:` is the learn skills' stamp: both learn examples carry it, a registration fragment never does
    assert cf.validate(full, require_learned=True) == []
    assert cf.validate(bare, require_learned=True) == []
    assert [p.section for p in cf.validate(registration, require_learned=True)] == ["learned"]


def test_learn_skills_invoke_validate_and_refs_resolve(tmp_path):
    for skill in LEARN_SKILLS:
        calls = _validate_calls(skill)
        assert calls, f"{skill} holds no `changes_fragment.py validate` invocation"
        assert any("three-pillars-docs/changes/demo.md" in c for c in calls), (skill, calls)
        report = skill_refs.check(ROOT, [ROOT / "skills" / skill / "SKILL.md"], cache_dir=tmp_path)
        assert report.issues == [], (skill, report.issues)


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *argv[1:]], cwd=cwd, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("skill", LEARN_SKILLS)
def test_learn_validate_invocation_runs_on_a_fixture(skill, tmp_path):
    """The command the skill holds passes a frontmatter-only fragment the learn skill stamped, and
    refuses one it did not (a registration fragment must never read as 'learn ran')."""
    call = _validate_calls(skill)[0]
    changes = tmp_path / "three-pillars-docs" / "changes"
    changes.mkdir(parents=True)
    fragment = changes / "demo.md"
    fragment.write_text(LEARNED_FM, encoding="utf-8")
    ok = _run(call, tmp_path)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    fragment.write_text(BARE_FM, encoding="utf-8")
    refused = _run(call, tmp_path)
    assert refused.returncode == 1 and "changes_fragment: learned:" in refused.stdout, refused.stdout + refused.stderr
