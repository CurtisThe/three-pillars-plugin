"""Tests for escape_ledger.from_review over a fixture round dir."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import escape_ledger  # noqa: E402


def _round(tmp_path, reply, sidecar=None, raw=False):
    r = tmp_path / "round-1"
    (r / "opus-check").mkdir(parents=True)
    text = reply if raw else json.dumps(reply)
    (r / "opus-check" / "reply.md").write_text(text, encoding="utf-8")
    if sidecar is not None:
        (r / "opus-check" / "dispositions.json").write_text(
            json.dumps(sidecar), encoding="utf-8")
    return r


KEPT = {"class": "sec", "escape": {"from": "security#0", "disposition": "kept"}}
ADDED = {"escape": {"from": None, "disposition": "opus-added"}}


def test_reply_and_sidecar_yield_three_rows(tmp_path):
    r = _round(tmp_path, {"findings": [KEPT, ADDED, {"title": "no escape"}]},
               {"dropped": [{"from": "perf#1", "class": "perf"}]})
    rows = escape_ledger.from_review(r, "d")
    assert len(rows) == 3
    assert all(x["role"] == "review_finder" and x["engine"] == "local"
               and x["design"] == "d" and x["step"] == "round-1"
               and x["caught_by"] == "opus-check" for x in rows)
    by = {x["disposition"]: x for x in rows}
    assert by["kept"]["finding_id"] == "security#0"
    assert by["kept"]["defect_class"] == "sec"
    assert by["opus-added"]["finding_id"] is None
    assert by["dropped"]["finding_id"] == "perf#1"
    assert by["dropped"]["defect_class"] == "perf"


def test_bare_string_dropped_and_fenced_reply(tmp_path):
    fenced = "text\n```json\n" + json.dumps({"findings": [KEPT]}) + "\n```\n"
    r = _round(tmp_path, fenced, {"dropped": ["a#2"]}, raw=True)
    rows = escape_ledger.from_review(r, "d")
    assert [x["finding_id"] for x in rows] == ["security#0", "a#2"]


def test_missing_sidecar_notes_incomplete(tmp_path, capsys):
    r = _round(tmp_path, {"findings": [KEPT, ADDED]})
    rows = escape_ledger.from_review(r, "d")
    assert len(rows) == 2
    assert "ledger-incomplete" in capsys.readouterr().err


def test_unparseable_reply_returns_empty(tmp_path, capsys):
    r = _round(tmp_path, "not json at all", raw=True)
    assert escape_ledger.from_review(r, "d") == []
    assert "ledger-incomplete" in capsys.readouterr().err


def test_missing_reply_returns_empty(tmp_path, capsys):
    assert escape_ledger.from_review(tmp_path / "nope", "d") == []
    assert "ledger-incomplete" in capsys.readouterr().err


def test_bad_disposition_skipped_not_raised(tmp_path, capsys):
    bad = {"escape": {"from": "x#0", "disposition": "bogus"}}
    r = _round(tmp_path, {"findings": [bad, KEPT]}, {"dropped": []})
    rows = escape_ledger.from_review(r, "d")
    assert len(rows) == 1
    assert "skipped" in capsys.readouterr().err


def test_served_sonnet_busy_propagates(tmp_path):
    f = {"escape": {"from": "a#0", "disposition": "kept",
                    "served": "sonnet-busy"}}
    r = _round(tmp_path, {"findings": [f]}, {"dropped": []})
    rows = escape_ledger.from_review(r, "d")
    assert rows[0]["served"] == "sonnet-busy"
