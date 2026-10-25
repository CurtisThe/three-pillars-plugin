"""escalate --reason no-reply clears its own in-flight marker when given --ledger.

design: followups-1024 (Task 9.1, Slot 8 finding F1). Without --ledger the command is
unchanged. Run with: python3 -m pytest skills/_shared/test_finalizer_cli_escalate_ledger.py
"""
from __future__ import annotations

import json

import finalizer_cli as cli  # noqa: E402
from test_finalizer_cli_apply import Rec, URL, apply_args, ledger, prep, run, stop_of  # noqa: E402


def _escalate(capsys, rec, tmp, stop, *more):
    return run(capsys, rec, "escalate", "--stop", json.dumps(stop), "--reason", "no-reply",
               "--decisions", tmp / "decisions.md", "--pr-url", URL, *more)


def test_escalate_no_reply_with_a_ledger_clears_the_marker(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    out = prep(capsys, rec, tmp_path, stop)
    key = out["key"]
    rc = cli.main([str(a) for a in apply_args(tmp_path, stop, reply=tmp_path / "absent.txt")],
                  **rec.kwargs())
    capsys.readouterr()
    assert rc == 2, f"apply with an absent reply should exit 2, got {rc}"
    assert ledger(tmp_path)["in_flight"] is not None, f"refused apply cleared {key}"
    rc, out = _escalate(capsys, rec, tmp_path, stop, "--ledger", tmp_path / "ledger.json")
    assert rc == 0, f"escalate --ledger exited {rc}: {out}"
    led = ledger(tmp_path)
    assert led["in_flight"] is None, f"escalate --ledger left the marker set for {key}"
    assert led["seen"].get(key) == "escalate", f"seen[{key}] = {led['seen'].get(key)!r}, want 'escalate'"


def test_escalate_no_reply_without_a_ledger_keeps_the_marker(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    key = prep(capsys, rec, tmp_path, stop)["key"]
    rc, out = _escalate(capsys, rec, tmp_path, stop)
    assert rc == 0, f"escalate without --ledger exited {rc}: {out}"
    led = ledger(tmp_path)
    assert led["in_flight"] is not None, f"escalate without --ledger cleared the marker for {key}"
    assert key not in led["seen"], f"escalate without --ledger recorded seen[{key}] = {led['seen'][key]!r}"
