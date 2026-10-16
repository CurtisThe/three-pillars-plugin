"""C1 guard: the pr-iterate model-adjacent helpers never call a model themselves.

The Sonnet judge call and the /code-review dispatch happen in SKILL.md prose via
`Agent()`. The helpers own prompt construction, response parsing and plumbing only:
no `import anthropic` / `from anthropic import ...` and no `claude` subprocess.
Both checks parse the helper's Python source with `ast`, so a docstring that merely
names the forbidden pattern is not a hit.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
C1_HELPERS = [
    _SCRIPTS / "classifier_judge.py",
    _SCRIPTS / "review_merge.py",
    _SCRIPTS / "review_merge_dedupe.py",
    _SCRIPTS.parent.parent / "_shared" / "thread_resolver.py",
    _SCRIPTS / "run_round.py",
    _SCRIPTS / "iterate_state.py",
]


def _tree(py: Path) -> ast.AST:
    return ast.parse(py.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    return mods


def _claude_spawns(tree: ast.AST) -> list[int]:
    """Line numbers of calls whose argv list/tuple literal starts with "claude"."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
                first = arg.elts[0]
                if isinstance(first, ast.Constant) and first.value == "claude":
                    lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("py", C1_HELPERS, ids=lambda p: p.name)
def test_c1_helper_has_no_anthropic_import(py: Path):
    bad = [m for m in _imported_modules(_tree(py)) if "anthropic" in m.lower()]
    assert not bad, f"{py.name} imports {bad} (C1: the model is called from SKILL prose)"


@pytest.mark.parametrize("py", C1_HELPERS, ids=lambda p: p.name)
def test_c1_helper_spawns_no_claude_subprocess(py: Path):
    assert not _claude_spawns(_tree(py)), f"{py.name} spawns a `claude` subprocess (C1)"


def test_c1_detectors_catch_the_forbidden_shapes():
    tree = ast.parse("import anthropic\nfrom anthropic.types import X\nrun(['claude', '-p'])\n")
    assert [m for m in _imported_modules(tree) if "anthropic" in m] == ["anthropic", "anthropic.types"]
    assert _claude_spawns(tree) == [3]
    clean = ast.parse('"""import anthropic; run([\'claude\'])"""\nimport json\n')
    assert not [m for m in _imported_modules(clean) if "anthropic" in m]
    assert not _claude_spawns(clean)
