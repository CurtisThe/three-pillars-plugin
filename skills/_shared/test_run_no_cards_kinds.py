"""Untagged deny names the operator-only kinds (design: followups-1024 2.2, Behavior 9)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finalizer_ruling as fr  # noqa: E402
import run_no_cards_hook as h  # noqa: E402

RID = "demo-20261024-abc123"
RUN = {"TP_DESIGN_RUN": "1"}


def _card(tmp_path):
    return {"tool_name": "AskUserQuestion", "cwd": str(tmp_path),
            "tool_input": {"questions": [{"question": "Which rung?", "options": []}]}}


def _reason(payload):
    out, rc = h.run(payload, env=RUN)
    assert rc == 0
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    return spec["permissionDecisionReason"]


def test_untagged_reason_names_operator_only_kinds(tmp_path):
    r = _reason(_card(tmp_path))
    assert ", ".join(fr.OPERATOR_ONLY) in r
    assert "--kind" in r


def test_wait_reason_names_no_kind():
    assert "--kind" not in h.wait_reason(RID)
