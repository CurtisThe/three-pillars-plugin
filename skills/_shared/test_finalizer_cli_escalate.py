"""Tests for finalizer_cli escalate / clear — diagnosis before label, no-dispatch paths.

design: fable-first-stops (Task 2.1). Every seam is injected: no live `gh`, no git,
no agent spawn. The resolve side lives in test_finalizer_cli_apply.py.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_escalate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_cli as cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
LABEL = "tp:needs-human-attention"
STOP = {"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": "a1" * 20,
        "detail": {"iteration": 8, "measured": 8, "limit": 6, "signal": "round-cap"}}
HALT = {"source": "halt", "signal": "env-error", "target": "widgets", "detail": "pytest missing"}


class Rec:
    def __init__(self):
        self.calls, self.resolved = [], []

    def kwargs(self, now=T):
        def resolve(agent):
            self.resolved.append(agent)
            return f"three-pillars:{agent}"

        return {"comment_fn": lambda u, b: self.calls.append(("comment", u, b)) or True,
                "label_fn": lambda u, lb: self.calls.append(("label", u, lb)) or True,
                "resolve_fn": resolve, "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": "b2" * 20},
                "is_ancestor_fn": lambda a, b: True, "now": now}


def run(capsys, rec, *argv, now=T):
    rc = cli.main([str(a) for a in argv], **rec.kwargs(now))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, (json.loads(lines[-1]) if lines else None)


def prepare(capsys, rec, tmp, stop=STOP, now=T):
    return run(capsys, rec, "prepare", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json",
               "--decisions", tmp / "decisions.md", now=now)


def reply(tmp, outcome, **extra):
    body = {"outcome": outcome, "actions": [], "diagnosis": "the loop cannot converge: needle churn",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING, **extra}
    path = tmp / "reply.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def cap6(tmp):
    """keep-the-pin: the asserted 8→10 grant numbers predate the review-weight cap of 3."""
    path = tmp / "cap6.json"
    path.write_text(json.dumps({"pdw": {"guards": {"round_cap": 6}}}), encoding="utf-8")
    return path


def apply(capsys, rec, tmp, outcome, *more, stop=STOP, **extra):
    return run(capsys, rec, "apply", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json",
               "--reply", reply(tmp, outcome, **extra), "--decisions", tmp / "decisions.md",
               "--config", cap6(tmp), *more)


def text(tmp):
    return (tmp / "decisions.md").read_text(encoding="utf-8")


def test_escalate_reply_posts_diagnosis_strictly_before_the_label(capsys, tmp_path):
    rec = Rec()
    prepare(capsys, rec, tmp_path)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"phase": "budget-exhausted", "termination_reason": "round-cap",
                                 "iteration": 8, "reproduced_blockers": 1}), encoding="utf-8")
    before = state.read_bytes()
    _, out = apply(capsys, rec, tmp_path, "escalate", "--state", state, "--pr-url", URL)
    assert out["outcome"] == "escalate"
    assert [c[0] for c in rec.calls] == ["comment", "label"]
    assert "needle churn" in rec.calls[0][2] and rec.calls[1][1:] == (URL, LABEL)
    assert state.read_bytes() == before  # the terminal state stays terminal
    assert "needle churn" in text(tmp_path)


def test_escalate_reply_without_a_pr_posts_nothing(capsys, tmp_path):
    rec = Rec()
    prepare(capsys, rec, tmp_path, stop=HALT)
    _, out = apply(capsys, rec, tmp_path, "escalate", stop=HALT)
    assert out["outcome"] == "escalate" and rec.calls == []
    assert "needle churn" in text(tmp_path)
    assert json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))["in_flight"] is None


def test_blocked_reply_escalates_even_when_it_says_resolved(capsys, tmp_path):
    rec = Rec()
    prepare(capsys, rec, tmp_path)
    _, out = apply(capsys, rec, tmp_path, "resolved", "--pr-url", URL, blocked=["merge denied"])
    assert out["outcome"] == "escalate" and out["problems"] == ["blocked: ['merge denied']"]
    assert [c[0] for c in rec.calls] == ["comment", "label"]


@pytest.mark.parametrize("reason", ["already-finalized", "nested"])
def test_escalate_subcommand_needs_no_reply_and_no_dispatch(capsys, tmp_path, reason):
    rec = Rec()
    ledger = tmp_path / "ledger.json"
    rc, out = run(capsys, rec, "escalate", "--stop", json.dumps(STOP), "--reason", reason,
                  "--decisions", tmp_path / "decisions.md", "--pr-url", URL)
    assert (rc, out["outcome"], out["problems"]) == (0, "escalate", [reason])
    assert rec.resolved == [] and not ledger.exists()
    assert [c[0] for c in rec.calls] == ["comment", "label"] and rec.calls[1][2] == LABEL
    assert reason in text(tmp_path) and "no finalizer dispatched" in text(tmp_path)


def test_escalate_subcommand_without_a_pr_only_logs(capsys, tmp_path):
    rec = Rec()
    run(capsys, rec, "escalate", "--stop", json.dumps(HALT), "--reason", "nested",
        "--decisions", tmp_path / "decisions.md")
    assert rec.calls == [] and "nested" in text(tmp_path)


def test_pr_iterate_escalate_reply_without_pr_url_posts_to_the_target(capsys, tmp_path):
    rec = Rec()
    prepare(capsys, rec, tmp_path)
    _, out = apply(capsys, rec, tmp_path, "escalate")
    assert out["outcome"] == "escalate"
    assert [(c[0], c[1]) for c in rec.calls] == [("comment", URL), ("label", URL)]
    assert "needle churn" in rec.calls[0][2] and rec.calls[1][2] == LABEL


def test_pr_iterate_escalate_subcommand_without_pr_url_labels_the_target(capsys, tmp_path):
    rec = Rec()
    run(capsys, rec, "escalate", "--stop", json.dumps(STOP), "--reason", "already-finalized",
        "--decisions", tmp_path / "decisions.md")
    assert [(c[0], c[1]) for c in rec.calls] == [("comment", URL), ("label", URL)]


def test_second_fire_of_an_extended_signal_is_already_finalized(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = Rec()
    prepare(capsys, rec, tmp_path)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"phase": "budget-exhausted", "termination_reason": "round-cap",
                                 "iteration": 8, "reproduced_blockers": 1}), encoding="utf-8")
    _, out = apply(capsys, rec, tmp_path, "resolved", "--state", state)
    assert out["extension"] == {"signal": "round-cap", "from": 8, "to": 10}
    rec.calls.clear()  # the resolution note landed on the target; watch only the escalate
    rc, refused = prepare(capsys, rec, tmp_path)  # the loop hit the extended cap: same key
    assert (rc, refused["reason"]) == (3, "already-finalized")
    _, out = run(capsys, rec, "escalate", "--stop", json.dumps(STOP), "--reason", refused["reason"],
                 "--decisions", tmp_path / "decisions.md", "--pr-url", URL)
    assert out["outcome"] == "escalate" and [c[0] for c in rec.calls] == ["comment", "label"]
    assert rec.resolved == ["tp-finalizer"]  # one dispatch in total


def test_clear_clears_the_marker_and_logs_it(capsys, tmp_path):
    rec = Rec()
    key = prepare(capsys, rec, tmp_path)[1]["key"]
    rc, out = run(capsys, rec, "clear", "--ledger", tmp_path / "ledger.json",
                  "--decisions", tmp_path / "decisions.md")
    assert (rc, out) == (0, {"status": "cleared", "key": key})
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["in_flight"] is None and ledger["stale_cleared"] == [key]
    assert "stale-in-flight-cleared" in text(tmp_path) and key in text(tmp_path)
    assert run(capsys, rec, "clear", "--ledger", tmp_path / "ledger.json",
               "--decisions", tmp_path / "decisions.md")[1] == {"status": "none"}
    assert prepare(capsys, rec, tmp_path)[1]["status"] == "dispatch"  # the stop was never finalized


def test_prepare_that_cleared_a_stale_marker_logs_it(capsys, tmp_path):
    rec = Rec()
    key = prepare(capsys, rec, tmp_path)[1]["key"]
    other = dict(STOP, target="https://github.com/acme/widgets/pull/43")
    rc, out = prepare(capsys, rec, tmp_path, other, now=T + 7201)
    assert (rc, out["status"], out["stale_cleared"]) == (0, "dispatch", [key])
    assert "stale-in-flight-cleared" in text(tmp_path) and key in text(tmp_path)


def test_unreadable_ledger_at_apply_escalates(capsys, tmp_path):
    rec = Rec()
    (tmp_path / "ledger.json").write_text("{not json", encoding="utf-8")
    _, out = apply(capsys, rec, tmp_path, "resolved", "--pr-url", URL)
    assert out["outcome"] == "escalate" and out["problems"] == ["ledger-unreadable"]
    assert [c[0] for c in rec.calls] == ["comment", "label"]


def test_unknown_escalate_reason_is_a_usage_error(capsys, tmp_path):
    rc, _ = run(capsys, Rec(), "escalate", "--stop", json.dumps(STOP), "--reason", "because",
                "--decisions", tmp_path / "decisions.md")
    assert rc == 2 and not (tmp_path / "decisions.md").exists()


# --- PR #188 round 1: the default label seam must work where `gh pr edit` is broken ---

_CLASSIC_PROJECTS_GH = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
labels = os.environ["FAKE_GH_LABELS"]
if a[:2] == ["pr", "edit"]:  # classic-Projects repo: gh pr edit dies before the label lands
    sys.stderr.write("GraphQL: Projects (classic) is being deprecated\\n")
    sys.exit(1)
if a[:1] == ["api"] and a[-2:] == ["--input", "-"] and a[-3].endswith("/labels"):
    with open(labels, "a") as fh:
        fh.write("\\n".join(json.load(sys.stdin)["labels"]) + "\\n")
    sys.exit(0)
if a[:2] == ["pr", "view"]:
    print(json.dumps({"labels": [], "state": "OPEN", "headRefOid": "b" * 40}))
    sys.exit(0)
sys.exit(0)  # pr comment, label create
'''


def test_escalation_labels_the_pr_where_gh_pr_edit_is_broken(tmp_path, monkeypatch):
    import os
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "gh").write_text(_CLASSIC_PROJECTS_GH, encoding="utf-8")
    (shim / "gh").chmod(0o755)
    labels = tmp_path / "labels.txt"
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LABELS", str(labels))
    stop = {"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": "a" * 40}
    rc = cli.main(["escalate", "--stop", json.dumps(stop), "--reason", "already-finalized",
                   "--decisions", str(tmp_path / "decisions.md")])
    assert rc == 0
    got = labels.read_text(encoding="utf-8") if labels.exists() else ""
    assert LABEL in got
