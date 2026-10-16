"""Tests for finalizer_cli's stop ping — the operator hears when an escalate lands.

design: pr-ready-ping (Task 1.4). Every seam is injected: no live `gh`, no git,
no push tool. The seam style is test_finalizer_cli_escalate.py's `Rec`.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_ping.py
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_cli as cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import ready_ping  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
STOP = {"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": "a1" * 20,
        "detail": {"iteration": 8, "measured": 8, "limit": 6, "signal": "round-cap"}}
HALT = {"source": "halt", "signal": "env-error", "target": "widgets", "detail": "pytest missing"}


class Rec:
    def __init__(self):
        self.calls, self.resolved, self.pings = [], [], []

    def ping(self, stop, decisions=None):
        self.pings.append((stop, decisions))

    def kwargs(self, now=T):
        def resolve(agent):
            self.resolved.append(agent)
            return f"three-pillars:{agent}"

        return {"comment_fn": lambda u, b: self.calls.append(("comment", u, b)) or True,
                "label_fn": lambda u, lb: self.calls.append(("label", u, lb)) or True,
                "resolve_fn": resolve, "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": "b2" * 20},
                "is_ancestor_fn": lambda a, b: True, "now": now, "ping_fn": self.ping}


def run(capsys, rec, *argv, now=T):
    rc = cli.main([str(a) for a in argv], **rec.kwargs(now))
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    return rc, (json.loads(lines[-1]) if lines else None), captured.out, captured.err


def prepare(capsys, rec, tmp, stop=STOP, now=T):
    return run(capsys, rec, "prepare", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json",
               "--decisions", tmp / "decisions.md", now=now)


def reply(tmp, outcome, **extra):
    body = {"outcome": outcome, "actions": [], "diagnosis": "the loop cannot converge: needle churn",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING, **extra}
    path = tmp / "reply.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def apply(capsys, rec, tmp, outcome, *more, stop=STOP, **extra):
    return run(capsys, rec, "apply", "--stop", json.dumps(stop), "--ledger", tmp / "ledger.json",
               "--reply", reply(tmp, outcome, **extra), "--decisions", tmp / "decisions.md", *more)


def test_escalate_pings_once_with_the_stop_and_the_decisions_path(capsys, tmp_path):
    rec = Rec()
    rc, out, _, _ = run(capsys, rec, "escalate", "--stop", json.dumps(HALT), "--reason", "nested",
                        "--decisions", tmp_path / "decisions.md")
    assert (rc, out["outcome"]) == (0, "escalate")
    assert rec.pings == [(HALT, str(tmp_path / "decisions.md"))]


def test_the_ping_line_goes_to_stderr_so_the_json_stays_last_on_stdout(capsys, tmp_path):
    rec = Rec()

    def real(stop, decisions=None):
        return ready_ping.ping_stop(stop, decisions=decisions, ledger=str(tmp_path / "ping.jsonl"),
                                    info_fn=lambda u: {"headRefName": "tp/widgets",
                                                       "mergeable": "MERGEABLE", "title": "t"})

    rec.ping = real
    rc, out, out_text, err = run(capsys, rec, "escalate", "--stop", json.dumps(HALT),
                                 "--reason", "already-finalized", "--decisions",
                                 tmp_path / "decisions.md")
    assert (rc, out["outcome"]) == (0, "escalate")
    assert json.loads(out_text.strip().splitlines()[-1])["outcome"] == "escalate"
    assert ready_ping.MARK in err
    assert (tmp_path / "ping.jsonl").exists()


def test_resolved_never_pings(capsys, tmp_path):
    rec = Rec()
    prepare(capsys, rec, tmp_path, stop=HALT)
    rc, out, _, _ = apply(capsys, rec, tmp_path, "resolved", stop=HALT)
    assert (rc, out["outcome"]) == (0, "resolved") and rec.pings == []


def test_a_raising_ping_fn_changes_neither_the_exit_code_nor_the_json(capsys, tmp_path):
    rec = Rec()

    def boom(stop, decisions=None):
        raise RuntimeError("push tool down")

    rec.ping = boom
    rc, out, _, _ = run(capsys, rec, "escalate", "--stop", json.dumps(HALT), "--reason", "nested",
                        "--decisions", tmp_path / "decisions.md")
    assert (rc, out["outcome"], out["problems"]) == (0, "escalate", ["nested"])


def test_main_called_without_a_ping_fn_pings_nothing(capsys, tmp_path):
    rec = Rec()
    kwargs = rec.kwargs()
    kwargs.pop("ping_fn")
    rc = cli.main(["escalate", "--stop", json.dumps(HALT), "--reason", "nested",
                   "--decisions", str(tmp_path / "decisions.md")], **kwargs)
    captured = capsys.readouterr()
    assert rc == 0 and rec.pings == []
    assert json.loads(captured.out.strip().splitlines()[-1])["outcome"] == "escalate"


def test_main_exposes_a_ping_fn_seam_defaulting_to_none():
    param = inspect.signature(cli.main).parameters["ping_fn"]
    assert param.default is None


def test_the_module_holds_ready_ping_for_the_main_entry():
    assert getattr(cli, "ready_ping", None) is not None
    assert callable(cli.ready_ping.ping_stop)
