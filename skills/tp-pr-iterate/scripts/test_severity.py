"""Tests for severity — the one severity authority (design review-convergence, D1).

A finding blocks only when it is a real (non-sentinel) finding whose `blocking`
is True, that Opus did not downgrade, and whose reproducer was not refuted.
`finalize` is the single place that writes the final `blocking`/`verdict`, and
it records *why* it flipped a finding with `severity_note`.

Sentinels are built through `review_merge._is_sentinel`'s own shape so the
predicate under test and the sentinel authority cannot drift apart.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import review_merge  # noqa: E402
import severity  # noqa: E402

from severity import finalize, is_blocking, opus_downgraded  # noqa: E402

REPRO = {"kind": "test", "source": "def test_bug():\n    assert False\n"}


def finding(**over):
    """A real blocking structural finding; `over` patches the normalized shape."""
    f = {
        "file": "skills/tp-pr-iterate/scripts/review_merge.py",
        "line_range": [10, 12],
        "summary": "parse drops a key",
        "class": "P",
        "blocking": True,
        "verdict": "structural",
        "reproducer": dict(REPRO),
    }
    f.update(over)
    return f


def no_angles_sentinel():
    return {"source": "no-angles", "summary": "no angles configured",
            "blocking": True, "verdict": "structural"}


def unparseable_sentinel():
    return {"file": "<review-output:angle-security>",
            "summary": "unparseable reviewer output",
            "blocking": True, "verdict": "structural"}


# ---------- opus_downgraded ----------


def test_opus_downgraded_only_for_downgraded_disposition():
    assert opus_downgraded(finding(escape={"disposition": "downgraded"})) is True
    assert opus_downgraded(finding(escape={"disposition": "kept"})) is False
    assert opus_downgraded(finding(escape={"disposition": "opus-added"})) is False


def test_opus_downgraded_tolerates_missing_or_non_dict_escape():
    assert opus_downgraded(finding()) is False
    for junk in ("downgraded", ["downgraded"], 7, None, {}):
        assert opus_downgraded(finding(escape=junk)) is False


# ---------- is_blocking ----------


def test_blocking_finding_with_reproducer_blocks():
    assert is_blocking(finding()) is True


def test_sentinel_never_blocks():
    for sentinel in (no_angles_sentinel(), unparseable_sentinel()):
        assert review_merge._is_sentinel(sentinel) is True
        assert is_blocking(sentinel) is False


def test_opus_downgraded_finding_is_non_blocking():
    downgraded = finding(escape={"disposition": "downgraded", "reason": "style"})
    assert is_blocking(downgraded) is False


def test_refuted_reproduction_is_non_blocking():
    assert is_blocking(finding(reproduction="refuted")) is False


def test_inconclusive_keeps_opus_blocking_call():
    for repro in ("reproduced", "inconclusive"):
        assert is_blocking(finding(reproduction=repro)) is True


def test_downgraded_stays_non_blocking_even_when_reproduced():
    f = finding(escape={"disposition": "downgraded"}, reproduction="reproduced")
    assert is_blocking(f) is False


def test_reviewer_not_blocking_stays_non_blocking():
    assert is_blocking(finding(blocking=False, verdict="minor")) is False


# ---------- finalize ----------


def test_finalize_sets_blocking_and_verdict_from_is_blocking():
    out = finalize([finding(reproduction="refuted"),
                    finding(escape={"disposition": "downgraded"}),
                    finding(reproduction="reproduced")])
    assert [f["blocking"] for f in out] == [False, False, True]
    assert [f["verdict"] for f in out] == ["minor", "minor", "structural"]


def test_finalize_leaves_sentinels_untouched():
    sentinels = [no_angles_sentinel(), unparseable_sentinel()]
    out = finalize(sentinels)
    for got in out:
        assert review_merge._is_sentinel(got) is True
        assert got["blocking"] is True
        assert got["verdict"] == "structural"
        assert "severity_note" not in got
    assert out == sentinels


def test_finalize_notes_opus_downgraded_only_when_it_flips():
    flipped = finalize([finding(escape={"disposition": "downgraded"})])[0]
    assert flipped["severity_note"] == "opus-downgraded"

    already_minor = finalize([finding(blocking=False, verdict="minor",
                                      escape={"disposition": "downgraded"})])[0]
    assert "severity_note" not in already_minor


def test_finalize_notes_refuted_only_when_it_flips():
    flipped = finalize([finding(reproduction="refuted")])[0]
    assert flipped["severity_note"] == "refuted"

    already_minor = finalize([finding(blocking=False, verdict="minor",
                                      reproduction="refuted")])[0]
    assert "severity_note" not in already_minor


def test_finalize_adds_no_note_when_nothing_flips():
    out = finalize([finding(reproduction="inconclusive"),
                    finding(blocking=False, verdict="minor")])
    assert all("severity_note" not in f for f in out)
    assert [f["verdict"] for f in out] == ["structural", "minor"]


def test_finalize_does_not_mutate_input():
    findings = [finding(reproduction="refuted"),
                finding(escape={"disposition": "downgraded"}),
                no_angles_sentinel(),
                finding(reproduction="reproduced")]
    snapshot = copy.deepcopy(findings)
    out = finalize(findings)
    assert findings == snapshot
    assert out is not findings
    for got, src in zip(out, findings):
        assert got is not src
    out[0]["blocking"] = "tampered"
    assert findings[0]["blocking"] is True
