"""Tests that the core explainer package never reaches into html_briefing.

Covers explainer-agent plan Task 1.2 and guards every later phase: explainer/
ships in core, html_briefing/ ships only in pro, so a production module here
must not import an html_briefing module or name the html_briefing dir. The scan
is over this directory's production modules (files not named ``test_*.py``);
the html_briefing module names are derived from that directory, minus its
``explainer_path`` shim (which points the other way, html_briefing -> core).
"""
import ast
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

_HTML_BRIEFING_DIR = Path(__file__).resolve().parent.parent / "html_briefing"


def _production_modules() -> list:
    mods = sorted(p for p in _HERE.glob("*.py") if not p.name.startswith("test_"))
    assert mods, f"no production modules found under {_HERE}"
    return mods


def _html_briefing_stems() -> set:
    return {p.stem for p in _HTML_BRIEFING_DIR.glob("*.py")} - {"explainer_path"}


def _imported_names(source: str) -> set:
    """Every dotted component of every ``import X`` / ``from X import`` module."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
    return names


def test_no_production_module_imports_an_html_briefing_module():
    if not _HTML_BRIEFING_DIR.is_dir():
        pytest.skip("html_briefing is not shipped here (core tier)")
    stems = _html_briefing_stems()
    offenders = {
        p.name: sorted(_imported_names(p.read_text(encoding="utf-8")) & stems)
        for p in _production_modules()
    }
    assert {k: v for k, v in offenders.items() if v} == {}


def test_no_production_module_names_html_briefing():
    offenders = [p.name for p in _production_modules()
                 if "html_briefing" in p.read_text(encoding="utf-8")]
    assert offenders == []
