"""Task 1.2 — ready_ping helpers: pr_info, ping_ready, ping_stop, the CLI.

Oracle: example (plan pr-ready-ping 1.2). Every assertion is the contract
text in the task block, never the wording of any SKILL.md. No test calls the
real ``gh``: every helper gets an injected ``info_fn`` and a ``tmp_path``
ledger.
"""

import hashlib
import io
import json
from pathlib import Path

import pytest

import ready_ping
from ready_ping import MARK, ping_ready, ping_stop, pr_number


def records(ledger):
    if not Path(ledger).exists():
        return []
    return [json.loads(line) for line in
            Path(ledger).read_text(encoding="utf-8").splitlines() if line.strip()]


URL = "https://github.com/o/r/pull/12"


# --- ping_ready -------------------------------------------------------------


def test_ping_ready_mergeable_sends_title(tmp_path):
    ledger = tmp_path / "led.ndjson"
    seen = []

    def info_fn(pr_url):
        seen.append(pr_url)
        return {"mergeable": "MERGEABLE", "title": "Add the thing",
                "headRefName": "tp/my-slug"}

    sent = ping_ready(URL, "abc123", info_fn=info_fn, ledger=ledger,
                      out=io.StringIO())
    assert seen == [URL]
    assert sent["status"] == "sent"
    assert sent["kind"] == "ready"
    assert sent["key"] == "ready:abc123"
    assert sent["channel"] == "print"
    assert sent["message"] == "ready to merge #12 (my-slug): Add the thing"
    got = records(ledger)[0]
    assert got["slug"] == "my-slug"
    assert got["pr"] == 12
    assert got["head"] == "abc123"
    assert len(records(ledger)) == 1


def test_ping_ready_conflicting_skips(tmp_path):
    ledger = tmp_path / "led.ndjson"
    out = io.StringIO()
    sent = ping_ready(URL, "abc123",
                      info_fn=lambda u: {"mergeable": "CONFLICTING",
                                         "title": "Add the thing",
                                         "headRefName": "tp/my-slug"},
                      ledger=ledger, out=out)
    assert sent["status"] == "skipped"
    assert sent["reason"] == "conflicting"
    assert out.getvalue() == ""
    held = records(ledger)
    assert len(held) == 1, f"a conflicting skip records one owed entry, got {held!r}"
    assert held[0]["kind"] == "owed", f"the entry must be owed, got {held[0]!r}"


def test_ping_ready_empty_info_pings_unchecked(tmp_path):
    """No gh / a Gitea forge: ``{}`` info still pings, flagged unchecked."""
    ledger = tmp_path / "led.ndjson"
    out = io.StringIO()
    sent = ping_ready("https://gitea.example/o/r/pulls/7", "h1",
                      info_fn=lambda u: {}, ledger=ledger, out=out)
    assert sent["status"] == "sent"
    assert "mergeability unchecked" in sent["message"]
    assert "(unknown)" in sent["message"]
    assert out.getvalue().startswith(f"{MARK} ")
    assert records(ledger)[0]["slug"] == "unknown"


def test_ping_ready_title_plus_unchecked_when_not_mergeable(tmp_path):
    sent = ping_ready(URL, "h1",
                      info_fn=lambda u: {"mergeable": "UNKNOWN",
                                         "title": "Add the thing",
                                         "headRefName": "tp/my-slug"},
                      ledger=tmp_path / "led.ndjson", out=io.StringIO())
    assert sent["message"] == (
        "ready to merge #12 (my-slug): Add the thing (mergeability unchecked)"
    )


def test_ping_ready_duplicate_on_same_head(tmp_path):
    ledger = tmp_path / "led.ndjson"

    def info(_u):
        return {"mergeable": "MERGEABLE", "title": "T",
                "headRefName": "tp/my-slug"}

    first = ping_ready(URL, "h1", info_fn=info, ledger=ledger, out=io.StringIO())
    again = ping_ready(URL, "h1", info_fn=info, ledger=ledger, out=io.StringIO())
    assert first["status"] == "sent"
    assert again["status"] == "duplicate"
    assert len(records(ledger)) == 1


def test_ping_ready_never_raises_when_info_fn_raises(tmp_path):
    def boom(_url):
        raise RuntimeError("gh missing")

    sent = ping_ready(URL, "h1", info_fn=boom,
                      ledger=tmp_path / "led.ndjson", out=io.StringIO())
    assert sent["status"] == "sent"
    assert "mergeability unchecked" in sent["message"]


# --- ping_stop --------------------------------------------------------------


def test_ping_stop_url_target(tmp_path):
    ledger = tmp_path / "led.ndjson"
    stop = {"source": "halt", "signal": "timeout", "target": URL, "head": "h1"}
    seen = []

    def info_fn(pr_url):
        seen.append(pr_url)
        return {"mergeable": "MERGEABLE", "title": "T",
                "headRefName": "tp/my-slug"}

    sent = ping_stop(stop, info_fn=info_fn, ledger=ledger, out=io.StringIO())
    assert seen == [URL]
    assert sent["status"] == "sent"
    assert sent["kind"] == "stop"
    assert sent["key"].startswith("stop:halt:timeout:")
    assert sent["key"].endswith(":h1")
    assert sent["message"] == (
        "run stopped, needs you: #12 (my-slug): halt/timeout escalated to the operator"
    )
    got = records(ledger)[0]
    assert got["slug"] == "my-slug"
    assert got["pr"] == 12


def test_ping_stop_slug_target(tmp_path):
    ledger = tmp_path / "led.ndjson"
    out = io.StringIO()
    stop = {"source": "pr-iterate", "signal": "budget-exhausted",
            "target": "my-slug"}
    sent = ping_stop(stop, info_fn=lambda u: pytest.fail("no gh for a slug"),
                     ledger=ledger, out=out)
    assert sent["status"] == "sent"
    assert sent["key"] == "stop:pr-iterate:budget-exhausted:my-slug:"
    assert sent["message"] == (
        "run stopped, needs you: (my-slug): pr-iterate/budget-exhausted "
        "escalated to the operator"
    )
    assert out.getvalue().startswith(f"{MARK} run stopped, needs you: ")
    assert records(ledger)[0]["pr"] is None


def test_ping_stop_two_headless_stops_both_ping(tmp_path):
    ledger = tmp_path / "led.ndjson"
    base = {"source": "halt", "signal": "timeout", "target": "my-slug"}
    one = ping_stop(dict(base, detail="first"), ledger=ledger, out=io.StringIO())
    two = ping_stop(dict(base, detail="second"), ledger=ledger, out=io.StringIO())
    assert one["status"] == "sent"
    assert two["status"] == "sent"
    assert one["key"] != two["key"]
    assert len(records(ledger)) == 2


def test_ping_stop_malformed_stop_is_error_not_raise(tmp_path):
    for bad in (None, {}, {"source": "nope", "signal": "x", "target": "s"}):
        sent = ping_stop(bad, ledger=tmp_path / "led.ndjson", out=io.StringIO())
        assert sent["status"] == "error"
        assert sent["reason"]
    assert records(tmp_path / "led.ndjson") == []


def test_ping_stop_never_raises_when_info_fn_raises(tmp_path):
    def boom(_url):
        raise RuntimeError("gh missing")

    stop = {"source": "halt", "signal": "timeout", "target": URL, "head": "h1"}
    sent = ping_stop(stop, info_fn=boom, ledger=tmp_path / "led.ndjson",
                     out=io.StringIO())
    assert sent["status"] == "sent"
    assert "(unknown)" in sent["message"]


# --- pr_info ----------------------------------------------------------------


def test_pr_info_failure_returns_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no gh")

    monkeypatch.setattr(ready_ping.subprocess, "run", boom)
    assert ready_ping.pr_info(URL) == {}


# --- CLI --------------------------------------------------------------------


@pytest.fixture
def cli_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ready_ping, "ledger_path",
                        lambda slug: tmp_path / f"{slug}.ndjson")
    monkeypatch.setattr(ready_ping, "pr_info",
                        lambda url: {"mergeable": "MERGEABLE",
                                     "title": "Add the thing",
                                     "headRefName": "tp/my-slug"})
    return tmp_path


def test_cli_ready_prints_one_json_line(capsys, cli_ledger):
    code = ready_ping.main(["ready", "--pr-url", URL, "--head", "h1"])
    captured = capsys.readouterr()
    assert code == 0
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["status"] == "sent"
    assert payload["message"] == "ready to merge #12 (my-slug): Add the thing"
    assert captured.err.startswith(f"{MARK} ")
    assert len(records(cli_ledger / "my-slug.ndjson")) == 1


def test_cli_ready_repeat_says_duplicate(capsys, cli_ledger):
    ready_ping.main(["ready", "--pr-url", URL, "--head", "h1"])
    capsys.readouterr()
    code = ready_ping.main(["ready", "--pr-url", URL, "--head", "h1"])
    captured = capsys.readouterr()
    assert code == 0
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "duplicate"
    assert captured.err == ""


def test_cli_stop_slug_and_pr_url(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(ready_ping, "ledger_path",
                        lambda slug: tmp_path / f"{slug}.ndjson")
    code = ready_ping.main(["stop", "--slug", "my-slug", "--summary",
                            "halt/timeout escalated to the operator",
                            "--pr-url", URL, "--head", "h1"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out.strip())
    assert payload["status"] == "sent"
    digest = hashlib.sha1(b"halt/timeout escalated to the operator",
                          usedforsecurity=False).hexdigest()[:12]
    assert payload["key"] == f"stop:my-slug:{digest}:h1"
    assert payload["message"] == (
        "run stopped, needs you: #12 (my-slug): halt/timeout escalated to the operator"
    )
    assert pr_number(URL) == 12


def test_cli_stop_slug_only(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(ready_ping, "ledger_path",
                        lambda slug: tmp_path / f"{slug}.ndjson")
    code = ready_ping.main(["stop", "--slug", "my-slug", "--summary", "s"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out.strip())
    assert payload["status"] == "sent"
    digest = hashlib.sha1(b"s", usedforsecurity=False).hexdigest()[:12]
    assert payload["key"] == f"stop:my-slug:{digest}:"
    assert payload["message"] == "run stopped, needs you: (my-slug): s"


def test_cli_usage_error_exits_two(capsys):
    assert ready_ping.main([]) == 2
    assert ready_ping.main(["nope"]) == 2
    assert ready_ping.main(["ready", "--head", "h"]) == 2
    assert ready_ping.main(["stop", "--slug", "s"]) == 2
    capsys.readouterr()


def test_cli_decisions_file_written(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(ready_ping, "ledger_path",
                        lambda slug: tmp_path / f"{slug}.ndjson")
    monkeypatch.setattr(ready_ping, "pr_info",
                        lambda url: {"mergeable": "MERGEABLE", "title": "T",
                                     "headRefName": "tp/my-slug"})
    decisions = tmp_path / "decisions.md"
    code = ready_ping.main(["ready", "--pr-url", URL, "--head", "h1",
                            "--decisions", str(decisions)])
    capsys.readouterr()
    assert code == 0
    text = decisions.read_text(encoding="utf-8")
    assert text.startswith("### [ready-ping] ready ping #12")
    assert "[finalizer]" not in text
