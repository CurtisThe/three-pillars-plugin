"""Task 1.2 replay — the #316 sequence through the real ping_ready, then rearm.

Oracle: example (plan ready-ping-after-basesync 1.2). The real ``ping_ready``
and ``rearm`` run against one ``tmp_path`` ledger. ``info_fn``, ``label_fn``,
``push_fn`` and ``sleep_fn`` are injected, so no test reaches gh, the label
manager or a real sleep.
"""

import io
import json

import ready_ping
import ready_ping_rearm
from ready_ping_rearm import main, rearm

URL = "https://github.com/o/r/pull/12"
OTHER_URL = "https://github.com/o/r/pull/13"
LABEL = "tp:ready-for-human-merge"


def info(mergeable, ref="tp/s", title="T"):
    return {"mergeable": mergeable, "headRefName": ref, "title": title}


class Recorder:
    """Records each call's arguments."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)


def test_316_converge_conflicting_then_sync_head_mergeable_one_ping_one_label(tmp_path):
    ledger = str(tmp_path / "s.ndjson")
    push, label = Recorder(), Recorder()
    # Converge while CONFLICTING: the h1 ping is skipped and owed.
    first = ready_ping.ping_ready(
        URL, "h1", info_fn=lambda _u: info("CONFLICTING"), ledger=ledger,
        out=io.StringIO(),
    )
    assert first["status"] == "skipped", f"the conflicting h1 ping must skip, got {first!r}"
    # A base-sync pushes head h2; the PR is now MERGEABLE.
    result = rearm(
        URL, "h2", info_fn=lambda _u: info("MERGEABLE"), label_fn=label,
        ledger=ledger, push_fn=push, out=io.StringIO(), err=io.StringIO(),
        sleep_fn=lambda _s: None,
    )
    assert len(push.calls) == 1, f"exactly one ready ping expected, got {len(push.calls)}"
    assert label.calls == [(URL, LABEL)], f"one label put back, got {label.calls!r}"
    assert result["ready_ping"]["status"] == "sent", f"got {result!r}"


def test_never_converged_slug_gets_no_ping_and_no_label(tmp_path):
    ledger = str(tmp_path / "never.ndjson")
    push, label = Recorder(), Recorder()
    result = rearm(
        OTHER_URL, "h9", info_fn=lambda _u: info("MERGEABLE", ref="tp/never"),
        label_fn=label, ledger=ledger, push_fn=push, out=io.StringIO(),
        err=io.StringIO(), sleep_fn=lambda _s: None,
    )
    assert result == {"status": "skipped", "reason": "not-converged"}, f"got {result!r}"
    assert len(push.calls) == 0, f"a never-converged PR gets zero pings, got {push.calls!r}"
    assert len(label.calls) == 0, f"a never-converged PR gets zero labels, got {label.calls!r}"


def test_main_prints_one_json_line_and_returns_zero(monkeypatch, capsys):
    seen = {}

    def fake_rearm(pr_url, head, **kwargs):
        seen["args"] = (pr_url, head)
        return {"status": "skipped", "reason": "not-converged"}

    monkeypatch.setattr(ready_ping_rearm, "rearm", fake_rearm)
    monkeypatch.setattr(ready_ping, "pr_info", lambda _u: {})
    code = main(["--pr-url", URL, "--head", "h2"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 0, f"main must return 0, got {code!r}"
    assert len(lines) == 1, f"main must print one JSON line, got {lines!r}"
    assert json.loads(lines[0]) == {"status": "skipped", "reason": "not-converged"}, (
        f"the printed line must be rearm's result, got {lines[0]!r}")
    assert seen["args"] == (URL, "h2"), f"rearm got the wrong arguments: {seen!r}"


def test_main_returns_zero_when_rearm_raises(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("seam down")

    monkeypatch.setattr(ready_ping_rearm, "rearm", boom)
    monkeypatch.setattr(ready_ping, "pr_info", lambda _u: {})
    code = main(["--pr-url", URL, "--head", "h2"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 0, f"main must still return 0 when rearm raises, got {code!r}"
    assert len(lines) == 1, f"main must print one JSON line, got {lines!r}"
    result = json.loads(lines[0])
    assert result["status"] == "error", f"a raise must print an error status, got {result!r}"
    assert "seam down" in result["reason"], f"the reason must carry the raise, got {result!r}"
