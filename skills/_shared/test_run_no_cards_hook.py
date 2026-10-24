"""Tests for run_no_cards_hook (design: run-no-cards-hook Task 1.1)."""
import copy
import io
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_no_cards_hook as h  # noqa: E402

RID = "demo-20261024-abc123"
RUN = {"TP_DESIGN_RUN": "1"}
ASK = {"tool_name": "AskUserQuestion", "cwd": "/x",
       "tool_input": {"questions": [{"question": "Which rung?", "options": []}]}}


def _with(*texts):
    p = copy.deepcopy(ASK)
    p["tool_input"]["questions"] = [{"question": t, "options": []} for t in texts]
    return p


def _reason(payload):
    out, rc = h.run(payload, env=RUN)
    assert rc == 0
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["permissionDecision"] == "deny"
    assert spec["permissionDecisionReason"].startswith("run-no-cards:")
    return spec["permissionDecisionReason"]


def test_untagged_denied():
    r = _reason(ASK)
    assert "ruling_cli.py ask" in r and "ruling_cli.py wait" in r


def test_tagged_denied_wait_only():
    r = _reason(_with("Which rung?\nruling: " + RID))
    assert "awaiting-operator: ruling " + RID in r
    assert "ruling_cli.py wait --id " + RID in r
    assert "ruling_cli.py ask" not in r
    assert re.search(r"\bask\b", r) is None


def test_second_question_tag():
    r = _reason(_with("One?", "Two?\nruling: " + RID))
    assert "ruling_cli.py wait --id " + RID in r


def test_malformed_tag_and_non_list_untagged():
    assert "ruling_cli.py ask" in _reason(_with("Q?\nruling: ../x"))
    p = copy.deepcopy(ASK)
    p["tool_input"]["questions"] = "nope"
    assert "ruling_cli.py ask" in _reason(p)


@pytest.mark.parametrize("e", [
    {}, {"TP_DESIGN_RUN": "0"},
    {"TP_DESIGN_RUN": "1", "TP_CHILD_SESSION": "1"},
    {"TP_DESIGN_RUN": "1", "TP_CHILD_SESSION": ""}])
def test_other_env_allowed(e):
    assert h.run(ASK, env=e) == ("", 0)


def test_other_tool_allowed():
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert h.run(p, env=RUN) == ("", 0)


def test_non_dict_fail_open(capsys):
    assert h.run(["not", "a", "dict"], env=RUN) == ("", 0)
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("run-no-cards:")


def test_main_bad_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
    assert h.main() == 0
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("run-no-cards:")


def _manifest(tmp_path, pre):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"hooks": {"PreToolUse": pre}}))
    return p


def test_check_manifest(tmp_path, capsys):
    cmd = 'python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/run_no_cards_hook.py"'
    good = _manifest(tmp_path, [{"matcher": "AskUserQuestion", "hooks": [
        {"type": "command", "command": cmd, "timeout": 10}]}])
    assert h.check_manifest(good) == 0
    assert h.check_manifest(_manifest(tmp_path, [])) == 1
    assert len(capsys.readouterr().err.strip().splitlines()) == 1
    assert h.check_manifest(tmp_path / "missing.json") == 1
