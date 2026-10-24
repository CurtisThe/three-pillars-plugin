"""test_registration_fragment.py — Task 1.13: registration and design-complete Current Focus go to the fragment.

design: living-doc-fragments, Task 1.13 (behavior B8). Oracle: example. Structure only
(skills/_shared/test-fragility.md): the fixture branch is built from the protocol's own registration example
and checked by the real guard and grammar; each SKILL.md is read through ``skill_invocations`` (its code
spans, never its prose), checked by ``skill_refs.check`` and, for the command it holds, run on a fixture.
No test pins wording.
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
import certify_issues  # noqa: E402
import changes_fragment as cf  # noqa: E402
import living_doc_guard  # noqa: E402
from skill_invocations import invocations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "skills" / "_shared" / "living-doc-fragments.md"
SKILLS = ("tp-design", "tp-spike", "tp-design" + "-complete", "tp-spike-auto")
VALIDATING = SKILLS[:3]  # the three that write the fragment (tp-spike-auto only words its closeout)
FILL = {"design-name": "demo", "spike-name": "demo"}
FRAGMENT_REL = "three-pillars-docs/changes/demo.md"
ROADMAP_REL = "three-pillars-docs/product_roadmap.md"
ISSUES_REL = "three-pillars-docs/known_issues.md"
_EXAMPLE = re.compile(r"^```fragment[ \t]+registration[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)

BLOCKED_ROW = "| 1 | `other` | wait for `demo` | `demo` |"
FREED_ROW = "| 1 | `other` | `/tp-plan other` | none |"
ROADMAP = (
    "# Roadmap\n\n## Current Focus\n\n| Priority | Design | Next Action | Blocked By |\n|---|---|---|---|\n"
    f"{BLOCKED_ROW}\n\n## Design Inventory\n\n| Name | What | Status |\n|---|---|---|\n"
)
KNOWN = "# Known Issues\n\n## Medium\n\n### M3: an open one\n\nbody\n\n## Low\n"
RESULT = {"complete": True, "name": "sweep-01", "sha": "a" * 40, "dispos" + "ition": "ledger", "claims": [
    {"id": "s2", "status": "not-binding", "reasons": [], "guard": "g/s2.py::t", "evidence": {"red": [], "green": []}}]}
CURRENT_FOCUS = f"### Current Focus\n- {BLOCKED_ROW}\n+ {FREED_ROW}\n\n"
ADD = "## Known issues — add"


def _registration_example() -> str:
    match = _EXAMPLE.search(PROTOCOL.read_text(encoding="utf-8"))
    assert match, "the protocol doc holds no `fragment registration` example"
    return match.group(1)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)


def _commit(root: Path, rel: str, text: str, msg: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", msg)


def _repo(tmp_path: Path, branch: str = "tp/demo") -> Path:
    """A repo whose ``main`` holds the living docs, and a design branch cut from it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user" + ".email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _commit(root, ROADMAP_REL, ROADMAP, "docs")
    _commit(root, ISSUES_REL, KNOWN, "issues")
    _git(root, "checkout", "-q", "-b", branch)
    return root


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_calls(skill: str, *, learned: bool = False) -> list[list[str]]:
    """The skill's ``changes_fragment.py validate`` commands (those without ``--require-learned`` by default)."""
    calls = invocations(ROOT / "skills" / skill / "SKILL.md", "changes_fragment.py", fill=FILL, root=ROOT)
    return [c for c in calls if c[2:3] == ["validate"] and ("--require-learned" in c) == learned]


def test_registration_fragment_branch_is_clean(tmp_path):
    root = _repo(tmp_path)
    fragment = root / FRAGMENT_REL
    # /tp-design registers: the protocol's example, the inventory row only
    _commit(root, FRAGMENT_REL, _registration_example(), "Design: demo high-level")
    # Tier 5.6 files a cert block into the same fragment (no living doc written)
    applied = certify_issues.apply_to_fragment(certify_issues.render([RESULT], None), fragment, root / ISSUES_REL)
    assert applied == ["M-new-cert-sweep-01-s2"]
    _git(root, "add", FRAGMENT_REL)
    _git(root, "commit", "-q", "-m", "cert issues")
    # /tp-design-complete step 6e frees the row the design blocked: a - / + pair, in place under ## Roadmap
    edited = _text(fragment).replace(ADD, CURRENT_FOCUS + ADD, 1)
    assert edited != _text(fragment)
    _commit(root, FRAGMENT_REL, edited, "Current" + " Focus")
    verdict = living_doc_guard.check(root, base_ref="main")
    assert (verdict.verdict, verdict.paths) == ("clean", [])
    parsed = cf.parse(_text(fragment), stem="demo")
    assert [cf.format_problem(p) for p in cf.validate(parsed, repo_root=root)] == []
    assert set(parsed.sections) == {"Roadmap", "Known issues — add"}
    focus = next(b for b in parsed.sections["Roadmap"] if b.heading == "Current" + " Focus")
    assert [(op.kind, op.text) for op in focus.ops] == [("-", BLOCKED_ROW), ("+", FREED_ROW)]


def test_editing_the_roadmap_directly_is_refused(tmp_path):
    """The contrast: what the skills did before this task (stage the roadmap) is what the guard refuses."""
    root = _repo(tmp_path)
    _commit(root, ROADMAP_REL, ROADMAP + "| `demo` | One-line what | Designed |\n", "Design: demo high-level")
    verdict = living_doc_guard.check(root, base_ref="main")
    assert (verdict.verdict, verdict.paths) == ("refused", [ROADMAP_REL])
    assert FRAGMENT_REL in verdict.fix


def test_registration_skills_invoke_validate_and_refs_resolve(tmp_path):
    for skill in VALIDATING:
        calls = _validate_calls(skill)
        assert calls, f"{skill} holds no `changes_fragment.py validate` invocation"
        assert any(FRAGMENT_REL in c for c in calls), (skill, calls)
    for skill in SKILLS:
        report = skill_refs.check(ROOT, [ROOT / "skills" / skill / "SKILL.md"], cache_dir=tmp_path)
        assert report.issues == [], (skill, report.issues)


@pytest.mark.parametrize("skill", VALIDATING)
def test_validate_invocation_passes_the_registration_fragment(skill, tmp_path):
    """The command the skill holds, run as written, accepts what ``/tp-design`` wrote at registration
    (which never carries ``learned:``) and refuses a fragment whose Current Focus line is not in the docs."""
    root = _repo(tmp_path)
    fragment = root / FRAGMENT_REL
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text(_registration_example(), encoding="utf-8")
    calls = [c for c in _validate_calls(skill) if FRAGMENT_REL in c]
    assert calls, f"{skill} holds no `changes_fragment.py validate` invocation for the fragment"
    call = calls[0]
    argv = [sys.executable, *call[1:]]
    ok = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=120)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    stale = _text(fragment) + "\n### Current Focus\n- | 9 | `gone` | nothing | none |\n"
    fragment.write_text(stale, encoding="utf-8")
    refused = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=120)
    assert refused.returncode == 1 and "changes_fragment: Roadmap:" in refused.stdout, refused.stdout
