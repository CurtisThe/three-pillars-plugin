"""Tests for ruling_file: id shape/determinism, O_EXCL write with clash
re-hash, render -> parse round trip, seat+run refused (4.1); find, dated
feedback, explain link (4.2).

design: fable-escalation 4.1-4.2
"""

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_ruling as fr  # noqa: E402
import ruling_file as rf  # noqa: E402

AT = "2026-10-11T19:00:00Z"
QSTOP = {"source": "question", "signal": "decision", "target": "my-design",
         "detail": {"question": "Which option?"}}
QKEY = "question:decision:my-design:abc12345"
HSTOP = {"source": "halt", "signal": "env-error", "target": "my-design",
         "detail": "pytest crashed"}
HKEY = "halt:env-error:my-design:deadbeef"
RESULT = {"outcome": "resolved", "problems": [], "diagnosis": "d",
          "reasoning": "r (vision.md)", "demoted": [],
          "actions": ["answer-question"], "ruling": dict(fr.EMPTY_RULING)}


def _candidate_ids(scope, question, at):
    """The ids write() tries in order: base, then hash inputs with #1..#3."""
    date = at[:10].replace("-", "")
    ids = []
    for n in ("", "#1", "#2", "#3"):
        h = hashlib.sha256((question + "\n" + at + n).encode("utf-8")).hexdigest()[:6]
        ids.append(f"{scope}-{date}-{h}")
    return ids


def test_ruling_id_shape():
    rid = rf.ruling_id("my-design", "Which?", AT)
    assert re.match(rf.ID_RE, rid)
    assert rid.startswith("my-design-20261011-")


def test_ruling_id_deterministic():
    a = rf.ruling_id("my-design", "Which?", AT)
    assert rf.ruling_id("my-design", "Which?", AT) == a
    assert rf.ruling_id("my-design", "What?", AT) != a
    assert rf.ruling_id("my-design", "Which?", "2026-10-12T19:00:00Z") != a


def test_write_parse_round_trip(tmp_path):
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    parsed = rf.parse(p)
    assert list(parsed["front"]) == ["id", "slug", "entry", "source", "kind",
                                     "outcome", "model", "at", "stop_key",
                                     "explain"]
    assert parsed["front"]["explain"] == "-"
    assert parsed["front"]["id"] == p.stem
    assert parsed["front"]["slug"] == "my-design"
    assert parsed["front"]["entry"] == "run"
    assert parsed["front"]["source"] == "question"
    assert parsed["front"]["kind"] == "decision"
    assert parsed["front"]["outcome"] == "resolved"
    assert parsed["front"]["model"] == "fable"
    assert parsed["front"]["at"] == AT
    assert parsed["front"]["stop_key"] == QKEY
    assert parsed["question"] == "Which option?"
    assert "problems" in parsed["ruling"]
    assert parsed["ruling"] == RESULT
    assert parsed["feedback"] == []


def test_write_creates_rulings_dir(tmp_path):
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    assert p.is_file()
    assert p.parent == tmp_path / rf.RULINGS_REL
    assert (tmp_path / "three-pillars-docs" / "escalations").is_dir()


def test_write_clash_rehashes(tmp_path):
    rid = rf.ruling_id("my-design", "Which option?", AT)
    first = tmp_path / rf.RULINGS_REL / (rid + ".md")
    first.parent.mkdir(parents=True)
    first.write_text("pre-created\n", encoding="utf-8")
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    assert p != first
    assert re.match(rf.ID_RE, p.stem)
    assert "#" not in p.name


def test_write_clash_exhausted_raises(tmp_path):
    d = tmp_path / rf.RULINGS_REL
    d.mkdir(parents=True)
    for rid in _candidate_ids("my-design", "Which option?", AT):
        (d / (rid + ".md")).write_text("x\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)


def test_seat_scope_with_run_entry_refused(tmp_path):
    with pytest.raises(ValueError):
        rf.write(tmp_path, scope="seat", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)


# the third value is a "/tmp"-shaped path built at runtime, never spelled (inv 3)
@pytest.mark.parametrize("bad", ["../x", "Bad_Scope", "/".join(("", "tmp", "x"))])
def test_write_refuses_bad_scope_before_any_write(tmp_path, bad):
    # 8.3: the scope reaches the file name, so it is grammar-checked before the
    # rulings dir is created (ruling_file.write raises ValueError; `_finish` in
    # finalizer_cli turns that into one fail-open line, never a ruling file).
    with pytest.raises(ValueError):
        rf.write(tmp_path, scope=bad, entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    assert not (tmp_path / rf.RULINGS_REL).exists()
    assert list(tmp_path.iterdir()) == []


def test_halt_question_is_stop_key(tmp_path):
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=HSTOP,
                 key=HKEY, result=RESULT, model="fable", at=AT)
    parsed = rf.parse(p)
    assert parsed["question"] == HKEY
    assert parsed["front"]["kind"] == "-"
    assert parsed["front"]["source"] == "halt"


def test_find_by_id(tmp_path):
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    assert rf.find(tmp_path, p.stem) == p
    assert re.match(rf.ID_RE, p.stem)
    assert rf.find(tmp_path, "my-design-20261011-abcdef") is None
    for bad in ("../x", "seat", "MY-DESIGN-20261011-abc123", ""):
        assert rf.find(tmp_path, bad) is None


def test_append_feedback_dated(tmp_path):
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    rf.append_feedback(p, "agree — fits the vision")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parsed = rf.parse(p)
    assert parsed["feedback"] == [f"- {day}: agree — fits the vision"]
    assert parsed["ruling"] == RESULT
    assert parsed["front"]["id"] == p.stem


def test_set_explain(tmp_path):
    p = rf.write(tmp_path, scope="my-design", entry="run", stop=QSTOP,
                 key=QKEY, result=RESULT, model="fable", at=AT)
    rf.set_explain(p, "explain/x.json")
    parsed = rf.parse(p)
    assert parsed["front"]["explain"] == "explain/x.json"
    assert list(parsed["front"]) == ["id", "slug", "entry", "source", "kind",
                                     "outcome", "model", "at", "stop_key",
                                     "explain"]
    assert parsed["ruling"] == RESULT
    assert parsed["question"] == "Which option?"
