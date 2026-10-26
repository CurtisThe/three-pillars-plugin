"""test_finder_coverage_prompt.py — a segment finder is told to write inline FINDING lines.

design: finder-cap-coverage (Task 1.2)

The shipped transport (`agent_caps.harvest`, the `put-partial` sidecar) was reachable but no
finder prompt named it, so a capped segment finder left nothing to harvest — the design's root
cause. One paragraph, from `finder_coverage.partial_note` and appended by `angles.build_prompt`
only for an angle with a `segment` block, tells the finder to write each confirmed finding as a
`FINDING` line in its own message text (no tool call) and one progress line per finished file.
The lines are a fallback for a stop, never the delivery, which stays the one `put` command; and
the paragraph carries no parseable example, so the prompt in the transcript never harvests as a
finding.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# `agent_caps` lives in skills/_shared: the path insert is what `angles.py` itself does, and
# what every test module here that imports a _shared module repeats.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import agent_caps  # noqa: E402
import angles  # noqa: E402
import finder_coverage  # noqa: E402

BASE, HEAD, EFFORT = "b0", "h1", "high"
REPLY = "/r/rounds/1/r1/edge-cases/reply.md"
ROUND_DIR, PUT_SCRIPT = "/r", "/fw/round_scratch.py"


def _segment_angle(**over):
    """A manifest entry for one segment slot of the `edge-cases` angle."""
    a = dict(angles.DEFAULT_ANGLES[1])
    a["role"], a["model"] = "finder", "local"
    a["segment"] = {"angle": "edge-cases", "id": "s3", "of": 4,
                    "files": ["skills/x.py", "tests/test_x.py"], "fraction": 0.6}
    a.update(over)
    return a


def _prompt(angle):
    return angles.build_prompt(angle, base=BASE, head=HEAD, effort=EFFORT, reply_path=REPLY,
                               round_dir=ROUND_DIR, put_script=PUT_SCRIPT)


_NON_SEGMENT = (*angles.DEFAULT_ANGLES, dict(angles.DEFAULT_ANGLES[1], role="finder"),
                _segment_angle(segment={}), _segment_angle(segment=None))


def test_partial_note_is_empty_without_a_segment():
    for angle in _NON_SEGMENT:
        assert finder_coverage.partial_note(angle) == ""


def test_segment_note_names_the_inline_lines():
    note = finder_coverage.partial_note(_segment_angle())
    assert note
    assert agent_caps.FINDING_MARK.strip() in note
    assert "progress" in note
    assert "put" in note


def test_the_note_is_the_only_change_to_a_segment_prompt(monkeypatch):
    """Metamorphic: the segment prompt minus its note paragraph is exactly the prompt
    `build_prompt` gives with the note switched off, so the `put` delivery rule and
    every other line stand unchanged."""
    note = finder_coverage.partial_note(_segment_angle())
    with_note = _prompt(_segment_angle())
    monkeypatch.setattr(finder_coverage, "partial_note", lambda angle: "")
    assert with_note.replace("\n\n" + note, "", 1) == _prompt(_segment_angle())


def test_segment_prompt_carries_the_note_as_exactly_one_paragraph():
    note = finder_coverage.partial_note(_segment_angle())
    p = _prompt(_segment_angle())
    assert note in p
    assert p.count(note) == 1
    assert sum(1 for para in p.split("\n\n") if note in para) == 1


def test_note_paragraph_sits_before_the_budget_line():
    p = _prompt(_segment_angle())
    note = finder_coverage.partial_note(_segment_angle())
    assert agent_caps.BUDGET_LINE in p
    assert p.index(note) < p.index(agent_caps.BUDGET_LINE)


def test_segment_prompt_never_harvests_as_a_finding():
    """The instruction carries no parseable example, so the prompt sitting in the finder's own
    transcript is inert: harvest finds nothing, and no marker is ever followed by a brace."""
    p = _prompt(_segment_angle())
    assert agent_caps.harvest(p) == []
    assert "FINDING {" not in p
    assert not re.search(re.escape(agent_caps.FINDING_MARK) + r"\s*\{", p)


def test_non_segment_prompt_equals_the_build_without_the_note(monkeypatch):
    """Metamorphic, not a pinned literal: a non-segment prompt is the same string whether
    `partial_note` exists or not, so the change adds nothing to it."""
    real = {i: _prompt(a) for i, a in enumerate(_NON_SEGMENT)}
    monkeypatch.setattr(finder_coverage, "partial_note", lambda angle: "")
    assert real == {i: _prompt(a) for i, a in enumerate(_NON_SEGMENT)}


def test_no_non_segment_prompt_mentions_the_inline_marker():
    for angle in _NON_SEGMENT:
        p = _prompt(angle)
        assert agent_caps.FINDING_MARK.strip() not in p
        assert agent_caps.harvest(p) == []
