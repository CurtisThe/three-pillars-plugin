"""Pins: the launch doc names the run's scratch area and the durable-state list."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scratch_leftovers  # noqa: E402

DOC = (HERE / "design-run-launch.md").read_text(encoding="utf-8")
CAP = 25000


def _scratch_paragraph():
    for para in DOC.split("\n\n"):
        if ".tp-scratch/run" in para:
            return para
    return ""


def test_scratch_paragraph_names_area_vars_and_check():
    para = _scratch_paragraph()
    assert para, "no paragraph names .tp-scratch/run"
    for token in ("TMPDIR", "TMP", "TEMP", ".tp-scratch/run", "scratch_leftovers.py"):
        assert token in para, token
    assert "must not override" in para
    assert "fails the run" in para


def test_durable_state_bullets_match_tuple():
    m = re.search(r"^## Durable state\n(.*?)(?=^## |\Z)", DOC, re.M | re.S)
    assert m, "no ## Durable state section"
    bullets = re.findall(r"^- `([^`]+)`\s*$", m.group(1), re.M)
    assert bullets == list(scratch_leftovers.DURABLE_STATE)
    assert len(bullets) == 7


def test_doc_under_char_cap():
    assert len(DOC) < CAP
