"""Task 1.6 — the CLI stop dedupe key and the decisions-entry spacing.

Oracle: example (plan pr-ready-ping 1.6). The ledger is isolated the way
``test_ready_ping_helpers.py`` does it: ``ledger_path`` is monkeypatched to a
``tmp_path`` file, so no test touches the real git common dir.
"""

import json

import pytest

import ready_ping


@pytest.fixture
def cli_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ready_ping, "ledger_path",
                        lambda slug: tmp_path / f"{slug}.ndjson")
    return tmp_path


def run_stop(capsys, summary):
    code = ready_ping.main(["stop", "--slug", "demo", "--summary", summary])
    assert code == 0
    return json.loads(capsys.readouterr().out.strip())


def test_cli_stop_different_summary_pings_again(capsys, cli_ledger):
    first = run_stop(capsys, "classifier block")
    second = run_stop(capsys, "different later stop")
    third = run_stop(capsys, "classifier block")
    assert first["status"] == "sent"
    assert second["status"] == "sent"
    assert first["key"] != second["key"]
    assert third["status"] == "duplicate"


def test_append_decisions_blank_line_before_entry(tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text("earlier text\n", encoding="utf-8")
    ready_ping._append_decisions(decisions, "### [ready-ping] stop ping #-",
                                 "msg", "key")
    text = decisions.read_text(encoding="utf-8")
    assert "earlier text\n\n### [ready-ping] stop ping #-\n" in text


def test_append_decisions_new_file_has_no_leading_blank(tmp_path):
    decisions = tmp_path / "decisions.md"
    ready_ping._append_decisions(decisions, "### [ready-ping] stop ping #-",
                                 "msg", "key")
    assert decisions.read_text(encoding="utf-8").startswith("### [ready-ping]")
