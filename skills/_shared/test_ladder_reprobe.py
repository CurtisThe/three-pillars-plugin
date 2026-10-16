"""test_ladder_reprobe.py — re-probe a skipped local rung before every later spawn.

design: one-cheap-engine (task 3.7). The probe is injected; no live router or lease.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import ladder_busy  # noqa: E402
import local_implement_config  # noqa: E402
import tier_ladder  # noqa: E402

CFG = {**local_implement_config.DEFAULTS, "escalate": True, "max_retries": 2}


def _skipped(effort="medium", route="routed/ok"):
    """local-<effort> skipped busy (never failed), now on sonnet-<effort>."""
    rec = tier_ladder.start("3.7", f"local-{effort}")
    rec["route"] = route
    _a, rung, rec = tier_ladder.next_step(rec, "unavailable", CFG, reason="local-busy")
    assert rung == f"sonnet-{effort}"
    return rec


def _probe(state, calls=None):
    def probe():
        if calls is not None:
            calls.append(1)
        return state
    return probe


def test_retry_reprobes_and_returns_to_local():
    rec = _skipped()
    _a, rung, rec = tier_ladder.next_step(rec, "FAIL", CFG, reason="boom")
    assert rung == "sonnet-medium"
    out, rec2 = ladder_busy.reprobe(rec, rung, probe=_probe("free"))
    assert out == "local-medium"
    assert rec2["tier_path"][-1] == "local-medium"
    assert rec2["verdicts"][-1]["why"] == "reprobe"


def test_escalation_reprobes_to_local_xhigh():
    rec = _skipped("xhigh")
    out, rec2 = ladder_busy.reprobe(rec, "sonnet-xhigh", probe=_probe("free"))
    assert out == "local-xhigh"
    assert rec2["tier_path"][-1] == "local-xhigh"


def test_still_busy_stays_on_sonnet_no_attempt():
    rec = _skipped()
    calls = []
    out, rec2 = ladder_busy.reprobe(rec, "sonnet-medium", probe=_probe("busy", calls))
    assert out == "sonnet-medium" and calls == [1]
    assert rec2["tier_path"] == rec["tier_path"]
    assert rec2["attempts"].get("local-medium", 0) == 0


def test_failed_local_rung_never_reprobed():
    rec = tier_ladder.start("3.7", "local-medium")
    rec["route"] = "routed/ok"
    for _ in range(3):
        _a, rung, rec = tier_ladder.next_step(rec, "FAIL", CFG, reason="boom")
    assert rec["attempts"]["local-medium"] > 0
    calls = []
    out, _ = ladder_busy.reprobe(rec, "sonnet-medium", probe=_probe("free", calls))
    assert out == "sonnet-medium" and calls == []


def test_unvisited_local_rung_never_reprobed():
    rec = tier_ladder.start("3.7", "sonnet-medium")
    rec["route"] = "routed/ok"
    calls = []
    out, _ = ladder_busy.reprobe(rec, "sonnet-medium", probe=_probe("free", calls))
    assert out == "sonnet-medium" and calls == []


def test_floored_route_never_reprobed():
    for route in ("unrouted/not-configured", None):
        rec = _skipped()
        if route is None:
            rec.pop("route")
        else:
            rec["route"] = route
        calls = []
        out, _ = ladder_busy.reprobe(rec, "sonnet-medium", probe=_probe("free", calls))
        assert out == "sonnet-medium" and calls == []


def test_opus_never_reprobed():
    rec = _skipped()
    rec["tier_path"].append("opus-xhigh")
    calls = []
    out, _ = ladder_busy.reprobe(rec, "opus-xhigh", probe=_probe("free", calls))
    assert out == "opus-xhigh" and calls == []


def test_cli_rewrites_record_and_prints_rung(tmp_path, capsys):
    rec = _skipped()
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    rc = ladder_busy.main(["reprobe", "--record", str(path), "--design", "d",
                           "--root", str(tmp_path)], probe=_probe("free"))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rung"] == "local-medium" and out["tier"] == "local"
    assert set(out) == {"rung", "tier", "agent", "agent_ref", "model"}
    assert json.loads(path.read_text(encoding="utf-8"))["tier_path"][-1] == "local-medium"


def test_no_reprobe_after_an_orphan_skip():
    """Only the most recent local-E verdict counts: a later orphan-holds-gpu skip of the
    re-probed rung keeps Sonnet, else the ladder cycles sonnet -> local with 0 attempts."""
    rec = _skipped("xhigh")
    rung, rec = ladder_busy.reprobe(rec, "sonnet-xhigh", probe=_probe("free"))
    assert rung == "local-xhigh"
    _a, rung, rec = tier_ladder.next_step(rec, "unavailable", CFG, reason="orphan-holds-gpu")
    assert rung == "sonnet-xhigh"
    calls = []
    out, _ = ladder_busy.reprobe(rec, rung, probe=_probe("free", calls))
    assert out == "sonnet-xhigh" and calls == []
