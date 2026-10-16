import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

STOP = {"source": "pr-iterate", "signal": "round-cap", "target": "pr-1"}


def _reply(**kw):
    base = {"outcome": "resolved", "actions": ["fix", "confirm", "converge"],
            "diagnosis": "d", "reasoning": "r (vision.md)", "demoted": [], "blocked": [],
            **fr.EMPTY_RULING}
    base.update(kw)
    return base


def test_resolved():
    r = fo.validate(_reply())
    assert r["outcome"] == "resolved" and r["problems"] == []
    assert r["diagnosis"] == "d" and r["demoted"] == []


def test_json_string_resolved():
    assert fo.validate(json.dumps(_reply()))["outcome"] == "resolved"


def test_disallowed_action():
    for bad in ("merge", "force-push"):
        r = fo.validate(_reply(actions=["fix", bad]))
        assert r["outcome"] == "escalate"
        assert any(bad in p for p in r["problems"])


def test_blocked():
    r = fo.validate(_reply(blocked="classifier denied"))
    assert r["outcome"] == "escalate"


def test_errored():
    for bad in (None, "", "{not json", json.dumps(_reply(outcome="maybe"))):
        r = fo.validate(bad)
        assert r["outcome"] == "escalate"
        assert any("finalizer-errored" in p for p in r["problems"])


def test_demoted():
    assert fo.validate(_reply(demoted=["a", "b"]))["demoted"] == ["a", "b"]


def test_decision_entry_fable():
    e = fo.decision_entry(STOP, fo.validate(_reply()), model_used="fable")
    assert "### [finalizer] resolved — pr-iterate/round-cap" in e
    for k in ("Decided", "Reasoning", "Confidence", "fable", "d"):
        assert k in e
    assert "finalizer-fallback" not in e


def test_decision_entry_opus():
    e = fo.decision_entry(STOP, fo.validate(_reply()), model_used="opus",
                          fallback_reason="fable unavailable")
    assert "finalizer-fallback" in e and "fable unavailable" in e


def test_resolution_note():
    res = fo.validate(_reply(demoted=["nit one", "nit two"]))
    ext = {"signal": "round-cap", "from": 6, "to": 8}
    n = fo.resolution_note(STOP, res, extension=ext)
    assert "fix" in n and "round-cap 6 → 8" in n
    assert "nit one" in n and "nit two" in n
    assert "no budget was extended" in fo.resolution_note(STOP, res).lower()
