"""Tests for finalizer_cli apply refusing a missing, blank or unreadable reply.

design: followups-1024 (Task 1.1). Refusal cases call cli.main directly and read
stdout/stderr from one capsys.readouterr(), since run() drains stderr.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_reply_guard.py
"""
from __future__ import annotations

import json

import pytest

import finalizer_cli as cli
from test_finalizer_cli_apply import (Rec, URL, apply_args, entries, ledger, prep,  # noqa: F401
                                      reply_of, run, state_at, stop_of)


class RecWithPing(Rec):
    """cert c1: the recording seam also injects the ping seam (``main(ping_fn=…)``), so a
    ping on a refused reply lands in the same recorder ``Rec`` already reports. ``Rec``
    alone never supplies one, so the guard could not see a ping that fires before the raise."""

    def kwargs(self):
        return {**super().kwargs(),
                "ping_fn": lambda stop, decisions=None: (
                    self.calls.append(("ping", stop.get("target"), str(decisions))) or True)}


def _blank(t):
    p = t / "blank.txt"
    p.write_text("  \n", encoding="utf-8")
    return p


def _binary(t):
    p = t / "binary.txt"
    p.write_bytes(b"\xff\xfe\x00bad")
    return p


@pytest.mark.parametrize("make", [lambda t: t / "absent.txt", _blank, _binary],
                         ids=["absent", "blank", "undecodable"])
def test_unusable_reply_is_refused_and_writes_nothing(capsys, tmp_path, monkeypatch, make):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), RecWithPing()
    prep(capsys, rec, tmp_path, stop)
    before = (tmp_path / "ledger.json").read_bytes()
    reply = make(tmp_path)
    argv = [str(a) for a in apply_args(tmp_path, stop, reply=reply)]
    rc = cli.main(argv, **rec.kwargs())
    cap = capsys.readouterr()
    assert rc == 2 and cap.out.strip() == ""
    assert str(reply) in cap.err
    assert (tmp_path / "ledger.json").read_bytes() == before
    assert not (tmp_path / "decisions.md").exists()
    # a refused reply spends NO effect seam — comment, label and the stop ping alike
    assert rec.kinds() == [], f"refused reply spent effect seams: {rec.kinds()}"


def test_refused_apply_does_not_spend_the_stop(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    absent = tmp_path / "absent.txt"
    argv = [str(a) for a in apply_args(tmp_path, stop, reply=absent)]
    assert cli.main(argv, **rec.kwargs()) == 2
    capsys.readouterr()
    rc, out = run(capsys, rec, *apply_args(tmp_path, stop, "--state", state_at(tmp_path),
                                           "--pr-url", URL))
    assert (rc, out["outcome"]) == (0, "resolved")
    rc, out = run(capsys, rec, *apply_args(tmp_path, stop, reply=absent))
    assert (rc, out["status"]) == (0, "noop")


def test_nonempty_unparseable_reply_still_escalates(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop, rec = stop_of(), Rec()
    prep(capsys, rec, tmp_path, stop)
    bad = tmp_path / "bad.txt"
    bad.write_text("not json", encoding="utf-8")
    rc, out = run(capsys, rec, *apply_args(tmp_path, stop, reply=bad))
    assert (rc, out["outcome"]) == (0, "escalate")
    assert "finalizer-errored" in out["problems"][0]


def test_escalate_no_reply_records_an_escalate(capsys, tmp_path):
    rc, out = run(capsys, Rec(), "escalate", "--stop", json.dumps(stop_of()),
                  "--reason", "no-reply", "--decisions", tmp_path / "d.md")
    assert (rc, out["outcome"], out["problems"]) == (0, "escalate", ["no-reply"])
