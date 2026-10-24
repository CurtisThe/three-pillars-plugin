"""test_safety_gate_coverage.py - GATE_PATHS covers the gate's real members.

design: light-run-ceremony-diet (PR #365 review r1). The list is derived-checked,
not hand-trusted: every `_shared` module gate_roster.py imports and every hook
script hooks/claude-code-hooks.json registers must satisfy touches_gate, so a new
predicate module or a new registered hook cannot silently skip the certifier and
the `security` review angle.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent
ROOT = SHARED.parents[1]
sys.path.insert(0, str(SHARED))

import safety_gate  # noqa: E402

ROSTER = SHARED / "gate_roster.py"
HOOKS_JSON = SHARED / "hooks" / "claude-code-hooks.json"

_in_framework = pytest.mark.skipif(
    not (ROSTER.is_file() and HOOKS_JSON.is_file()),
    reason="outside the framework repo: no gate_roster.py or hook registration")


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _roster_shared_imports() -> list[str]:
    names = set()
    for node in ast.walk(ast.parse(ROSTER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return sorted(_rel(SHARED / f"{n}.py") for n in names
                  if (SHARED / f"{n}.py").is_file())


def _registered_hook_scripts() -> list[str]:
    doc = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    out = set()
    for groups in doc.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                for m in re.finditer(r"(skills/\S+?\.(?:py|sh))", hook.get("command", "")):
                    out.add(m.group(1))
    return sorted(out)


@_in_framework
def test_roster_imports_found():
    assert "skills/_shared/deterministic_gate.py" in _roster_shared_imports()


@_in_framework
def test_every_roster_import_is_a_gate_path():
    missing = [p for p in _roster_shared_imports() if not safety_gate.touches_gate([p])]
    assert missing == [], missing


@_in_framework
def test_registered_hooks_found():
    assert "skills/_shared/reviewer_delete_hook.py" in _registered_hook_scripts()


@_in_framework
def test_every_registered_hook_is_a_gate_path():
    hooks = _registered_hook_scripts()
    missing = [p for p in hooks if not safety_gate.touches_gate([p])]
    assert missing == [], missing
    assert safety_gate.touches_gate([_rel(HOOKS_JSON)])


@pytest.mark.parametrize("path", [
    "skills/_shared/reviewer_delete_hook.py",
    "skills/_shared/wt_layout_hook.py",
    "skills/_shared/diff_balloon_guard.py",
    "skills/_shared/fragility_predicate.py",
    "skills/_shared/ci_local_stamp.py",
    "skills/_shared/round_log_carry.py",
    "skills/_shared/living_doc_carry.py",
    "skills/_shared/numbering_carry.py",
    "skills/_shared/hooks/claude-code-hooks.json",
    "skills/_shared/hooks/tp-commit-guard.sh",
    "skills/_shared/reviewer_delete_shell.py",
    "skills/_shared/worker_root.py",
    "skills/_shared/placeholder_gate.py",
    "skills/_shared/fragility_ast.py",
    "skills/_shared/index_guard.py",
    "skills/_shared/reviewer_delete_shell.py",
    "skills/_shared/reviewer_delete_lex.py",
    "skills/_shared/name_kill_scan.py",
    "skills/_shared/name_kill_py.py",
    "skills/_shared/automation_identity.py",
    "skills/_shared/thread_resolver.py",
    "skills/_shared/per_developer_author.py",
    "skills/tp-pr-iterate/scripts/review_proof.py",
    "skills/_shared/brand_new_widget_guard.py",
    "skills/_shared/brand_new_proof_thing.py",
    "skills/_shared/create_fence_hook.py",
    "skills/_shared/create_fence_targets.py",
    "skills/_shared/create_fence_py.py",
    "skills/_shared/run_scratch.py",
    "skills/_shared/scratch_leftovers.py",
])
def test_reviewed_gate_members_touch(path):
    assert safety_gate.touches_gate([path]) is True
