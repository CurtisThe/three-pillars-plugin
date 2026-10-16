"""test_fragility_citations.py — every review and audit prompt cites the fragility rule.

design: fragile-test-prevention (Task 9.8, stages §Behavior 10 guard)

The prompt set is derived, never listed: the skills and agents whose name has an
audit or review token, `tp-pr-fix` and the PR-loop round topology, and
`angles.build_prompt`'s output for each default angle. Each must hold a markdown
link target or a code-span path that resolves to `skills/_shared/test-fragility.md`.
Only the reference is checked, never the wording around it, per that rule doc.

Resolution: a link target resolves relative to the file's own directory; a code
span resolves relative to that directory or to the repo root (the framework's
`skills/_shared/...` paths are repo-root-relative). Angle prompts are text with
no file, so their spans resolve against the repo root.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
REPO_ROOT = _SHARED.parents[1]
sys.path.insert(0, str(REPO_ROOT / "skills" / "tp-pr-iterate" / "scripts"))
sys.path.insert(0, str(_SHARED))

import angles  # noqa: E402

RULE_DOC = (_SHARED / "test-fragility.md").resolve()

assert RULE_DOC.is_file(), "the rule doc must exist for this guard to mean anything"

_SKILL_TOKENS = {"audit", "review"}
_AGENT_TOKENS = {"auditor", "review"}
_NAMED_FILES = ("skills/tp-pr-fix/SKILL.md", "skills/tp-pr-iterate/round-topology.md")

_LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _has_token(name: str, tokens: set[str]) -> bool:
    return bool(set(name.split("-")) & tokens)


def _derived_files() -> list[Path]:
    skills = [p for p in sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
              if _has_token(p.parent.name, _SKILL_TOKENS)]
    agents = [p for p in sorted((REPO_ROOT / "agents").glob("*.md"))
              if _has_token(p.stem, _AGENT_TOKENS)]
    named = [REPO_ROOT / rel for rel in _NAMED_FILES]
    return skills + agents + named


def _is_rule_doc(raw: str, bases: list[Path]) -> bool:
    target = raw.split("#", 1)[0]
    if not target:
        return False
    for base in bases:
        try:
            if (base / target).resolve() == RULE_DOC:
                return True
        except (OSError, ValueError):
            continue
    return False


def cites_rule_doc(text: str, file_dir: Path | None) -> bool:
    """True when `text` holds a link target or code span resolving to the rule doc."""
    link_bases = [file_dir if file_dir is not None else REPO_ROOT]
    span_bases = [REPO_ROOT] if file_dir is None else [file_dir, REPO_ROOT]
    return (any(_is_rule_doc(t, link_bases) for t in _LINK_TARGET.findall(text))
            or any(_is_rule_doc(s, span_bases) for s in _CODE_SPAN.findall(text)))


def _angle_prompt(angle: dict) -> str:
    return angles.build_prompt(angle, base="b0", head="h1", effort="high",
                               reply_path="/r/reply.md")


_FILES = _derived_files()


def test_derived_sets_are_non_empty():
    assert any(p.name == "SKILL.md" and p.parent.parent.name == "skills" for p in _FILES)
    assert any(p.parent.name == "agents" for p in _FILES)
    assert angles.DEFAULT_ANGLES


@pytest.mark.parametrize("path", _FILES, ids=[str(p.relative_to(REPO_ROOT)) for p in _FILES])
def test_file_cites_rule_doc(path):
    assert path.is_file()
    assert cites_rule_doc(path.read_text(encoding="utf-8"), path.parent)


@pytest.mark.parametrize("angle", angles.DEFAULT_ANGLES,
                         ids=[a["name"] for a in angles.DEFAULT_ANGLES])
def test_angle_prompt_cites_rule_doc(angle):
    assert cites_rule_doc(_angle_prompt(angle), None)


@pytest.mark.parametrize("text,file_dir,expected", [
    ("See [rule](../skills/_shared/test-fragility.md).", REPO_ROOT / "agents", True),
    ("See [rule](skills/_shared/test-fragility.md).", REPO_ROOT / "agents", False),
    ("See `skills/_shared/test-fragility.md`.", REPO_ROOT / "skills" / "x", True),
    ("See `../_shared/test-fragility.md#fixes`.", REPO_ROOT / "skills" / "x", True),
    ("See `skills/_shared/file-size-caps.md`.", REPO_ROOT / "agents", False),
    ("test-fragility.md in prose, no reference", REPO_ROOT / "agents", False),
    ("See `skills/_shared/test-fragility.md`.", None, True),
])
def test_resolution_examples(text, file_dir, expected):
    assert cites_rule_doc(text, file_dir) is expected
