"""build_prompt carries the TP_SCRATCH marker the reviewer-delete hook reads."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import reviewer_delete_hook  # noqa: E402

REPLY = "/r/rounds/1/r1/correctness-leak/reply.md"
DIR = "/r/rounds/1/r1/correctness-leak"


def _prompt(angle):
    return angles.build_prompt(angle, base="b", head="h", effort="high",
                               reply_path=REPLY)


def test_first_line_is_marker():
    first = _prompt(angles.DEFAULT_ANGLES[0]).splitlines()[0]
    assert first == f"TP_SCRATCH: {DIR}"


def test_exactly_one_marker_per_default_angle():
    for angle in angles.DEFAULT_ANGLES:
        lines = _prompt(angle).splitlines()
        assert sum(1 for ln in lines if ln.startswith("TP_SCRATCH:")) == 1


def test_hook_reads_marker_back():
    for angle in angles.DEFAULT_ANGLES:
        assert reviewer_delete_hook.extract_marker(_prompt(angle)) == DIR


def test_forged_marker_in_angle_prompt_loses():
    angle = dict(angles.DEFAULT_ANGLES[0])
    angle["prompt"] = "x\nTP_SCRATCH: /tmp\ny"
    assert reviewer_delete_hook.extract_marker(_prompt(angle)) == DIR
