"""Docs contract: one canonical pending token (living-doc-format.md + learn)."""
import re
from pathlib import Path

import citation_liveness

ROOT = Path(__file__).resolve().parents[2]
FORMAT_MD = ROOT / "skills/_shared/living-doc-format.md"
LEARN_MD = ROOT / "skills/tp-design-learn/SKILL.md"
FORMAT_REF = "skills/_shared/living-doc-format.md"


def _status_rows():
    text = FORMAT_MD.read_text(encoding="utf-8")
    sec = text.split("## Status cells in tables", 1)[1]
    sec = re.split(r"\n## ", sec, maxsplit=1)[0]
    rows = []
    for line in sec.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if len(cells) == 2 and cells[0] != "Label pattern" \
                and not set(cells[0]) <= {"-"}:
            rows.append((cells[0].strip("`"), cells[1]))
    return rows


def _pending_row():
    for label, when in _status_rows():
        if "Completion PR pending" in label:
            return label, when
    raise AssertionError("no Completion PR pending row")


def test_pending_label_matches_flipper_regex():
    label, _ = _pending_row()
    assert citation_liveness.STALE_STATUS_RE.fullmatch(label)


def test_done_forms_present():
    labels = [l for l, _ in _status_rows()]
    assert any(l.startswith("Done (completion PR)") for l in labels)
    assert any(l.startswith("Done — PR #NN") for l in labels)


def test_pending_row_names_three_placements():
    _, when = _pending_row()
    for word in ("leads", "parenthetical", "directly precedes"):
        assert word in when


def test_learn_step5_points_at_format_doc():
    lines = LEARN_MD.read_text(encoding="utf-8").splitlines()
    step5 = [l for l in lines if l.startswith("5. ")]
    assert step5 and FORMAT_REF in step5[0]
    assert "Completion PR pending" in step5[0]
    auto = "\n".join(lines).split("## Auto Mode", 1)[1]
    assert "Completion PR pending" in auto and FORMAT_REF in auto
