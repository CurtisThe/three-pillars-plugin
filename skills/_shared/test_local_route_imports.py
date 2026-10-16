"""test_local_route_imports.py — pins the L3 one-way import direction between
`local_route_check` and `local_route_log` (Task 2.6).

design: hybrid-routing-hardening (detailed-design.md, L3)

`local_route_log` imports `local_route_check` at module level; `local_route_check`
must NOT import `local_route_log` at module level — its CLI does so lazily inside
the handler, only as `__main__`. These tests pin that: an AST walk over each
module's top-level body, and fresh `-I` subprocesses that import both modules in
both orders (so the order never matters). No module is imported here at
module level, so the test itself can't change the very thing it pins.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent

CHECK_PY = _SHARED / "local_route_check.py"
LOG_PY = _SHARED / "local_route_log.py"


def _child_env() -> dict:
    """An explicit env copy that never inherits the real router URL."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    return env


def _top_level_imports(source: Path) -> list[tuple[str, object]]:
    """`(module, node)` for every top-level `import X` / `from X import …`."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    result = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for name in node.names:
                result.append((name.name, node))
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append((node.module, node))
    return result


def _bound_names(node: object) -> list[str]:
    """Names a top-level import statement binds (for the assert message)."""
    return [alias.name for alias in node.names]  # Import and ImportFrom alike


def test_local_route_check_has_no_module_level_import_of_local_route_log():
    offenders = [(name, _bound_names(node))
                 for name, node in _top_level_imports(CHECK_PY)
                 if name == "local_route_log"]
    assert not offenders, (
        "local_route_check must not import local_route_log at module level "
        f"(lazy CLI import only): {offenders}")


def test_local_route_log_imports_local_route_check_at_module_level():
    modules = [name for name, _ in _top_level_imports(LOG_PY)]
    assert "local_route_check" in modules, (
        "local_route_log must import local_route_check at module level "
        f"(the one way); top-level modules were: {modules}")


def _fresh_import_order(order: list[str]) -> None:
    # A fresh, isolated interpreter: import both modules in `order`, from the
    # `_shared` dir on `sys.path`. Neither module may import the other at
    # import time, so BOTH orders must succeed.
    expr = "import sys; sys.path.insert(0, %r)" % str(_SHARED)
    expr += "; " + "; ".join(f"import {m}" for m in order)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", expr],
        capture_output=True, text=True, timeout=30,
        env=_child_env(),
    )
    assert proc.returncode == 0, (
        f"import order {order} failed; stderr={proc.stderr!r}")


def test_both_import_orders_succeed_in_a_fresh_isolated_interpreter():
    _fresh_import_order(["local_route_check", "local_route_log"])
    _fresh_import_order(["local_route_log", "local_route_check"])


def test_end_subcommand_is_reachable_as_main_under_isolation(tmp_path):
    # The lazy CLI path only runs as `__main__`; prove it resolves under `-I`.
    proc = subprocess.run(
        [sys.executable, "-I", str(CHECK_PY), "end",
         "--decisions", str(tmp_path / "decisions.md")],
        capture_output=True, text=True, timeout=30,
        env=_child_env(),
    )
    # a missing file reads as empty -> `{"line": null, "entry": null}`
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    assert len(lines) == 1, f"expected one JSON line, got {proc.stdout!r}"
