"""Tests for stopped_agents.py — the stopped-agents backstop writer (1.2).

The exact line the router (companion local-llm-skills, detailed-design-router.md
L34) reads:

    {"v": 1, "agent": "<full agent id>", "agent8": "<first 8 chars>",
     "attempt": "<attempt id>", "stopped_at": <epoch float>}

`agent` is the FULL id, `agent8` its first 8 characters — the tests pin both.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import stopped_agents as sa  # noqa: E402
from test_router_stats import _sibling  # noqa: E402

FULL = "a05370bf7ff454806"
NOW = 1_700_000_000.0
KEYS = {"v", "agent", "agent8", "attempt", "stopped_at"}


def _env(p):
    return {"TP_LOCAL_STOPPED": str(p)}


def _last(p):
    return json.loads(p.read_text(encoding="utf-8").splitlines()[-1])


def test_constants_and_rel():
    assert sa.REL == Path("tp-local") / "stopped-agents.jsonl"
    assert sa.TTL_S == 86_400
    assert sa.MAX_BYTES == 65_536


def test_path_resolution():
    assert sa.path({"TP_LOCAL_STOPPED": "/x/s.jsonl"}) == Path("/x/s.jsonl")
    assert sa.path({"XDG_STATE_HOME": "/s", "HOME": "/h"}) == \
        Path("/s/tp-local/stopped-agents.jsonl")
    assert sa.path({"HOME": "/h"}) == \
        Path("/h/.local/state/tp-local/stopped-agents.jsonl")


def test_append_writes_exact_line_and_returns_written(tmp_path):
    p = tmp_path / "stopped-agents.jsonl"
    assert sa.append(FULL, attempt_id="at-1", now=NOW, env=_env(p)) == "written"
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert set(entry) == KEYS
    assert entry["v"] == 1
    assert entry["agent"] == FULL
    assert entry["agent8"] == FULL[:8] == "a05370bf"
    assert entry["attempt"] == "at-1"
    assert entry["stopped_at"] == NOW


def test_append_writes_one_line_per_stop(tmp_path):
    p = tmp_path / "stopped-agents.jsonl"
    for i, agent in enumerate((FULL, "b05370bf7ff454807")):
        assert sa.append(agent, attempt_id=f"at-{i}", now=NOW + i, env=_env(p)) == "written"
    lines = p.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["agent8"] for line in lines] == ["a05370bf", "b05370bf"]


def test_append_no_router_creates_nothing(tmp_path):
    p = tmp_path / "absent" / "tp-local" / "stopped-agents.jsonl"
    assert sa.append(FULL, attempt_id="at-1", now=NOW, env=_env(p)) == "no-router"
    assert not (tmp_path / "absent").exists()


def test_over_max_bytes_is_pruned_to_valid_young_entries(tmp_path):
    p = tmp_path / "stopped-agents.jsonl"
    young_a = {"v": 1, "agent": "b1" * 10, "agent8": "b1" * 4,
               "attempt": "at-a", "stopped_at": NOW - sa.TTL_S / 2}
    young_b = {"v": 1, "agent": FULL, "agent8": FULL[:8],
               "attempt": "at-b", "stopped_at": NOW - 1.0}
    old = {"v": 1, "agent": "c" * 12, "agent8": "cccccccc",
           "attempt": "at-old", "stopped_at": NOW - 2 * sa.TTL_S}
    body = "".join(json.dumps(e) + "\n" for e in (young_a, old, young_b))
    pad = json.dumps({"v": 2, "attempt": "x" * (sa.MAX_BYTES - len(body) + 32)}) + "\n"
    p.write_text(body + pad, encoding="utf-8")
    assert p.stat().st_size > sa.MAX_BYTES

    assert sa.append("d1" * 10, attempt_id="at-new", now=NOW, env=_env(p)) == "written"

    entries = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert [e["attempt"] for e in entries] == ["at-a", "at-b", "at-new"]
    assert old not in entries
    assert p.stat().st_size <= sa.MAX_BYTES
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]


def test_under_max_bytes_append_keeps_old_entries(tmp_path):
    p = tmp_path / "stopped-agents.jsonl"
    old = {"v": 1, "agent": FULL, "agent8": FULL[:8],
           "attempt": "at-old", "stopped_at": NOW - 2 * sa.TTL_S}
    p.write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert sa.append("e" * 17, attempt_id="at-new", now=NOW, env=_env(p)) == "written"
    entries = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert [e["attempt"] for e in entries] == ["at-old", "at-new"]


def test_active_returns_live_agent8_set(tmp_path):
    p = tmp_path / "stopped-agents.jsonl"
    lines = [
        json.dumps({"v": 1, "agent": FULL, "agent8": FULL[:8],
                    "attempt": "a", "stopped_at": NOW - 1.0}),
        json.dumps({"v": 1, "agent": "b" * 15, "agent8": "bbbbbbbb",
                    "attempt": "b", "stopped_at": NOW - sa.TTL_S / 2}),
        # boundary: exactly TTL_S old is not younger than TTL_S
        json.dumps({"v": 1, "agent": "c" * 15, "agent8": "cccccccc",
                    "attempt": "c", "stopped_at": NOW - sa.TTL_S}),
        json.dumps({"v": 1, "agent": "d" * 15, "agent8": "dddddddd",
                    "attempt": "d", "stopped_at": NOW - 2 * sa.TTL_S}),
        json.dumps({"v": 2, "agent": "e" * 15, "agent8": "eeeeeeee",
                    "attempt": "e", "stopped_at": NOW - 1.0}),
        "not json",
        json.dumps(5),
        json.dumps({"v": 1, "agent": "f" * 15,
                    "attempt": "f", "stopped_at": NOW - 1.0}),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert sa.active(p, now=NOW) == {FULL[:8], "bbbbbbbb"}


def test_active_missing_file_is_empty(tmp_path):
    assert sa.active(tmp_path / "nope.jsonl", now=NOW) == set()


def test_contract_drift_against_sibling_router(tmp_path):
    sibling = _sibling()
    if sibling is None:
        pytest.skip("local-llm-skills sibling checkout absent")
    readme = sibling / "README.md"
    writer = sibling / "bin" / "stopped_agents.py"
    has_contract = (readme.is_file() and "STOPPED-AGENT" in readme.read_text(encoding="utf-8")) \
        or writer.is_file()
    if not has_contract:
        pytest.skip("sibling has no STOPPED-AGENT contract yet")

    # Our side: exact line shape and the path rule.
    p = tmp_path / "stopped-agents.jsonl"
    assert sa.append(FULL, attempt_id="at-1", now=NOW, env=_env(p)) == "written"
    ours = _last(p)
    assert set(ours) == KEYS
    assert ours["agent8"] == ours["agent"][:8]

    if writer.is_file():
        import importlib.util
        spec = importlib.util.spec_from_file_location("sib_stopped_agents", writer)
        sib = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sib)
        assert Path(sib.REL) == Path("tp-local") / "stopped-agents.jsonl"
        q = tmp_path / "sib" / "stopped-agents.jsonl"
        q.parent.mkdir(parents=True, exist_ok=True)
        assert sib.append(FULL, attempt_id="at-1", now=NOW,
                          env={"TP_LOCAL_STOPPED": str(q)}) == "written"
        assert set(_last(q)) == KEYS
    else:
        assert "stopped-agents.jsonl" in readme.read_text(encoding="utf-8")


# --- audit M3: the durable per-stop record -------------------------------------

def test_append_extra_fields_keep_the_contract_keys(tmp_path):
    p = tmp_path / "stopped-agents.jsonl"
    extra = {"orphaned_at": NOW - 5, "result": "refused", "agent": "spoof", "v": 9}
    assert sa.append(FULL, attempt_id="at-1", now=NOW, env=_env(p), extra=extra) == "written"
    entry = _last(p)
    assert entry["v"] == 1 and entry["agent"] == FULL and entry["agent8"] == FULL[:8]
    assert entry["attempt"] == "at-1" and entry["stopped_at"] == NOW
    assert entry["orphaned_at"] == NOW - 5 and entry["result"] == "refused"


def test_append_ladder_writes_stops_ndjson_without_a_router(tmp_path):
    lad = tmp_path / "ladder"
    lad.mkdir()
    for i in range(2):  # retries append, never rewrite
        assert sa.append_ladder(lad, FULL, attempt_id="at-1", now=NOW + i,
                                extra={"orphaned_at": None, "result": "refused"}) == "written"
    lines = (lad / sa.LADDER_STOPS).read_text(encoding="utf-8").splitlines()
    assert sa.LADDER_STOPS == "stops.ndjson" and len(lines) == 2
    assert json.loads(lines[0])["orphaned_at"] is None
    assert sa.append_ladder(tmp_path / "missing", FULL, attempt_id="x").startswith("error: ")


def test_records_reads_valid_lines_without_ttl(tmp_path):
    p = tmp_path / "stops.ndjson"
    p.write_text("\n".join([json.dumps({"v": 1, "agent": FULL, "attempt": "a", "stopped_at": 1.0}),
                            "{not json", json.dumps({"v": 2, "stopped_at": 1.0}),
                            json.dumps({"v": 1, "agent": FULL, "stopped_at": "x"})]) + "\n",
                 encoding="utf-8")
    assert [e["attempt"] for e in sa.records(p)] == ["a"]
    assert sa.records(tmp_path / "missing") == []
