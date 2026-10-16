"""Token pins: a seat shell with TP_ROOT unset fails with one line (design-run-launch-fixes 1.6).

Pins only the tokens the docs must carry (see test-fragility.md): the
``${TP_ROOT:-`` fallback, the ``resolve_root.sh`` resolver, and the single-line
failure message. No structure or count pins.
"""
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DOCS = [HERE / "first-run.md", HERE / "design-run-launch.md"]
MESSAGE = "TP_ROOT unresolved: run resolve_root.sh"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_names_tp_root_fallback(doc):
    text = doc.read_text(encoding="utf-8")
    assert "${TP_ROOT:-" in text, f"{doc.name} lacks the TP_ROOT:- fallback"
    assert "resolve_root.sh" in text, f"{doc.name} does not name resolve_root.sh"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_names_one_line_failure_message(doc):
    text = doc.read_text(encoding="utf-8")
    assert MESSAGE in text, f"{doc.name} lacks the one-line message {MESSAGE!r}"
