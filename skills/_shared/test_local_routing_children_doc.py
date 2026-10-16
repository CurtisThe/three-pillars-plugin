"""Task 2.4 (launch-role-precedence): `local-routing.md` names the children's-route rule.

The prose must say that in a **direct run** — the launcher's effective backend
`CLAUDE_LAUNCHER_BACKEND` is `direct` and the session carries no router base URL (a seat or
run session) — every check here probes the **children's route** (the launcher's plan for the
folder) rather than the session's own env, and it must name `children_route.py`.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DOC = ROOT / "skills" / "_shared" / "local-routing.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_names_children_route_module():
    assert "children_route.py" in _text()


def test_doc_names_the_direct_run_signal():
    assert "CLAUDE_LAUNCHER_BACKEND" in _text()


def test_doc_names_the_no_base_url_condition_and_the_children_route():
    missing = [n for n in ("direct", "ANTHROPIC_BASE_URL", "children's route") if n not in _text()]
    assert not missing, missing
