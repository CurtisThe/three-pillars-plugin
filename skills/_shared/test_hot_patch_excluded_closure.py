"""test_hot_patch_excluded_closure.py — the lane cannot edit its own guard
(consumer-repo-parity Task 5.7, detailed-design-part-e.md §H3 / Decision 10).

Ships (reads only commit_guard.py's own source and
hot_patch_check.EXCLUDED_FILES; never the dev-only release-tiering manifest).

Two checks:
  - every module commit_guard.py's import graph reaches, transitively,
    within skills/_shared/ (AST: every Import/ImportFrom node, module-level
    AND function-local — ast.walk descends into function bodies exactly
    like module bodies — plus literal-string dynamic loads,
    importlib.import_module("x") / import_module("x") / __import__("x"),
    positional or name= keyword)
    must be in EXCLUDED_FILES;
  - the design's named guard-adjacent modules — commit_guard.py itself,
    commit_guard_settings.py, hot_patch_hook.py, repo_config_load.py,
    ci_gate_run.py, ci_local_stamp.py, default_branch.py and
    bootstrap_immunization.py (some of these the closure walk does not
    reach on its own, e.g. ci_gate_run.py / ci_local_stamp.py) — and every
    on-disk test file for each (test_<name>*.py), plus the sentinel body
    (hooks/tp-commit-guard.sh), must be in EXCLUDED_FILES too.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import hot_patch_check as hpc  # noqa: E402

_ROOT_MODULE = "commit_guard"

_NAMED_MODULES = (
    _ROOT_MODULE,
    "commit_guard_settings",
    "hot_patch_hook",
    "repo_config_load",
    "ci_gate_run",
    "ci_local_stamp",
    "default_branch",
    "bootstrap_immunization",
)

_GUARD_SCRIPT_RELPATH = "skills/_shared/hooks/tp-commit-guard.sh"


def _rel(name: str) -> str:
    return f"skills/_shared/{name}.py"


_DYNAMIC_IMPORTERS = ("import_module", "__import__")


def _module_key(dotted: str) -> str | None:
    """The skills/_shared module name a dotted import target reaches: the
    third part of ``skills._shared.X``, else the first part (bare form)."""
    parts = dotted.split(".")
    if parts[0] == "skills":
        return parts[2] if len(parts) > 2 and parts[1] == "_shared" else None
    return parts[0]


def _dynamic_import_target(node: ast.AST) -> str | None:
    """The literal module string of a dynamic import call —
    ``importlib.import_module("x")``, a bare ``import_module("x")`` (after
    ``from importlib import import_module``) or ``__import__("x")``, the
    module passed positionally or as the ``name=`` keyword — else None. A
    non-literal argument cannot be resolved statically."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else None)
    if name not in _DYNAMIC_IMPORTERS:
        return None
    arg = node.args[0] if node.args else next(
        (kw.value for kw in node.keywords if kw.arg == "name"), None)
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _imported_module_names(tree: ast.AST) -> set[str]:
    """Every module ``tree`` imports, bare or ``skills._shared.X``-form, at
    any nesting depth — ``ast.walk`` visits nodes inside function bodies
    exactly like module-level ones, so a function-local import is found the
    same way as a module-level one. Dynamic loads with a literal module
    string (``importlib.import_module`` / ``__import__``) count too."""
    names: set[str] = set()
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                targets.append(node.module)
        else:
            dynamic = _dynamic_import_target(node)
            if dynamic is not None:
                targets.append(dynamic)
    for dotted in targets:
        key = _module_key(dotted)
        if key:
            names.add(key)
    return names


_PLANTED_FORMS = '''
import importlib
from importlib import import_module
import planted_a
from skills._shared.planted_b import thing
def f():
    importlib.import_module("planted_c")
    import_module("skills._shared.planted_d")
    __import__("planted_e")
    importlib.import_module(name="planted_f")
    __import__(name="planted_g")
    import_module(package=None, name="skills._shared.planted_h")
    importlib.import_module(some_variable)
'''


def _closure(start: str) -> set[str]:
    """Every skills/_shared module reachable from ``start`` (inclusive),
    following import edges transitively, staying within skills/_shared/."""
    seen = {start}
    pending = [start]
    while pending:
        name = pending.pop()
        path = _SHARED_DIR / f"{name}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_module_names(tree):
            if imported in seen:
                continue
            if (_SHARED_DIR / f"{imported}.py").exists():
                seen.add(imported)
                pending.append(imported)
    return seen


def test_import_closure_all_excluded():
    """Every module commit_guard.py's import graph reaches, transitively,
    within skills/_shared/, is in EXCLUDED_FILES — static imports AND
    literal dynamic loads (importlib.import_module / __import__)."""
    # The walk itself must see every import form (a planted-form check, so a
    # walker that drops a form cannot pass vacuously on today's sources).
    planted = _imported_module_names(ast.parse(_PLANTED_FORMS))
    expected = {"importlib", "planted_a", "planted_b", "planted_c",
                "planted_d", "planted_e", "planted_f", "planted_g", "planted_h"}
    assert planted == expected, (
        f"closure walk missed an import form: got {sorted(planted)}, "
        f"want {sorted(expected)}"
    )
    closure = _closure(_ROOT_MODULE)
    missing = sorted(
        _rel(name) for name in closure if _rel(name) not in hpc.EXCLUDED_FILES
    )
    assert not missing, (
        f"commit_guard.py's import closure is missing from EXCLUDED_FILES: {missing}"
    )


def test_named_guard_modules_and_tests_excluded():
    """The design's named guard-adjacent modules, and every on-disk test
    file for each, are in EXCLUDED_FILES."""
    missing: list[str] = []
    for name in _NAMED_MODULES:
        rel = _rel(name)
        if rel not in hpc.EXCLUDED_FILES:
            missing.append(rel)
        for test_file in sorted(_SHARED_DIR.glob(f"test_{name}*.py")):
            test_rel = f"skills/_shared/{test_file.name}"
            if test_rel not in hpc.EXCLUDED_FILES:
                missing.append(test_rel)
    assert not missing, (
        "named guard-adjacent modules/tests missing from EXCLUDED_FILES: "
        f"{sorted(set(missing))}"
    )


def test_guard_sentinel_body_excluded():
    """The sentinel body hooks/tp-commit-guard.sh is in EXCLUDED_FILES."""
    assert _GUARD_SCRIPT_RELPATH in hpc.EXCLUDED_FILES, (
        f"the sentinel body {_GUARD_SCRIPT_RELPATH!r} must be in EXCLUDED_FILES "
        "— the lane cannot edit its own guard"
    )
