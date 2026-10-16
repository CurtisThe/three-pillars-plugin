"""Task 1.1 — ready_ping core: ping, ledger, degrade.

Oracle: example (plan pr-ready-ping 1.1). Every assertion is the contract
text in the task block, never the wording of any SKILL.md.
"""

import io
import json
from pathlib import Path

from ready_ping import MARK, ledger_path, message, ping, pr_number


def records(ledger):
    if not Path(ledger).exists():
        return []
    return [json.loads(line) for line in
            Path(ledger).read_text(encoding="utf-8").splitlines() if line.strip()]


# --- message / pr_number ----------------------------------------------------


def test_message_ready_and_stop_formats():
    assert message("ready", "my-slug", 12, "Add the thing") == (
        "ready to merge #12 (my-slug): Add the thing"
    )
    assert message("stop", "my-slug", 12, "halt:timeout escalated to the operator") == (
        "run stopped, needs you: #12 (my-slug): halt:timeout escalated to the operator"
    )


def test_message_omits_pr_when_none():
    assert message("ready", "my-slug", None, "Add the thing") == (
        "ready to merge (my-slug): Add the thing"
    )
    assert message("stop", "my-slug", None, "summary") == (
        "run stopped, needs you: (my-slug): summary"
    )


def test_pr_number_extracts_trailing_int():
    assert pr_number("https://github.com/o/r/pull/12") == 12
    assert pr_number("https://github.com/o/r/pull/12/files") == 12
    assert pr_number("https://github.com/o/r/pull/abc") is None
    assert pr_number("not a url") is None
    assert pr_number(None) is None
    assert pr_number(7) == 7


# --- ledger_path ------------------------------------------------------------


def test_ledger_path_is_absolute_under_git_common_dir():
    path = ledger_path("my-slug")
    assert Path(path).is_absolute()
    assert Path(path).name == "my-slug.ndjson"
    assert Path(path).parent.name == "tp-ready-ping"


# --- ping: one record per head ---------------------------------------------


def test_ping_delivers_once_per_head(tmp_path):
    ledger = tmp_path / "tp-ready-ping" / "slug.ndjson"
    first = ping("ready", slug="slug", pr=12, head="aaa", summary="t",
                 ledger=ledger, out=io.StringIO())
    assert first["status"] == "sent"
    assert first["kind"] == "ready"
    assert first["key"] == "ready:aaa"
    assert first["channel"] == "print"
    assert first["message"] == "ready to merge #12 (slug): t"
    assert first["decisions_line"] == "### [ready-ping] ready ping #12"

    again = ping("ready", slug="slug", pr=12, head="aaa", summary="t",
                 ledger=ledger, out=io.StringIO())
    assert again["status"] == "duplicate"
    assert again["key"] == "ready:aaa"
    assert len(records(ledger)) == 1

    other = ping("ready", slug="slug", pr=12, head="bbb", summary="t",
                 ledger=ledger, out=io.StringIO())
    assert other["status"] == "sent"
    assert other["key"] == "ready:bbb"
    assert [r["key"] for r in records(ledger)] == ["ready:aaa", "ready:bbb"]
    got = records(ledger)[0]
    assert got["pr"] == 12
    assert got["slug"] == "slug"
    assert got["head"] == "aaa"
    assert got["at"]


def test_ping_stop_pings_once(tmp_path):
    ledger = tmp_path / "led.ndjson"
    out = io.StringIO()
    sent = ping("stop", slug="slug", pr=None, head=None,
                summary="halt:timeout escalated to the operator",
                ledger=ledger, out=out)
    assert sent["status"] == "sent"
    assert sent["key"] == "stop:halt:timeout escalated to the operator"
    assert sent["decisions_line"] == "### [ready-ping] stop ping #-"
    dup = ping("stop", slug="slug", pr=None, head=None,
               summary="halt:timeout escalated to the operator",
               ledger=ledger, out=io.StringIO())
    assert dup["status"] == "duplicate"
    assert len(records(ledger)) == 1


def test_ping_explicit_key_wins(tmp_path):
    ledger = tmp_path / "led.ndjson"
    sent = ping("stop", slug="slug", pr=3, head="h", summary="s",
                ledger=ledger, key="stop:src:sig:slug:h", out=io.StringIO())
    assert sent["key"] == "stop:src:sig:slug:h"
    assert records(ledger)[0]["key"] == "stop:src:sig:slug:h"


# --- degrade: no push tool, raising push tool --------------------------------


def test_no_push_fn_prints_marked_line(tmp_path):
    out = io.StringIO()
    sent = ping("ready", slug="slug", pr=9, head="h", summary="s",
                ledger=tmp_path / "led.ndjson", out=out)
    assert sent["channel"] == "print"
    assert out.getvalue() == f"{MARK} ready to merge #9 (slug): s\n"


def test_push_fn_success_uses_push_channel(tmp_path):
    shown = []
    sent = ping("ready", slug="slug", pr=9, head="h", summary="s",
                ledger=tmp_path / "led.ndjson", out=io.StringIO(),
                push_fn=lambda m: shown.append(m))
    assert sent["channel"] == "push"
    assert shown == ["ready to merge #9 (slug): s"]
    assert records(tmp_path / "led.ndjson")[0]["channel"] == "push"


def test_raising_push_fn_degrades_to_print(tmp_path):
    out = io.StringIO()

    def boom(_msg):
        raise RuntimeError("no push tool")

    sent = ping("ready", slug="slug", pr=9, head="h", summary="s",
                ledger=tmp_path / "led.ndjson", out=out, push_fn=boom)
    assert sent["status"] == "sent"
    assert sent["channel"] == "print"
    assert out.getvalue() == f"{MARK} ready to merge #9 (slug): s\n"
    assert len(records(tmp_path / "led.ndjson")) == 1


def test_ledger_parent_dir_created(tmp_path):
    ledger = tmp_path / "deep" / "nested" / "led.ndjson"
    ping("ready", slug="slug", pr=1, head="h", summary="s",
         ledger=ledger, out=io.StringIO())
    assert ledger.exists()


# --- decisions entry --------------------------------------------------------


def test_decisions_entry_written_once(tmp_path):
    decisions = tmp_path / "decisions.md"
    ledger = tmp_path / "led.ndjson"
    for _ in range(2):
        ping("ready", slug="slug", pr=4, head="h", summary="s",
             ledger=ledger, decisions=decisions, out=io.StringIO())
    text = decisions.read_text(encoding="utf-8")
    assert text.count("### [ready-ping] ready ping #4") == 1
    lines = text.splitlines()
    assert lines[0] == "### [ready-ping] ready ping #4"
    assert lines[1] == "ready to merge #4 (slug): s"
    assert lines[2] == "ready:h"
    assert text.endswith("\n")
    assert "[finalizer]" not in text


def test_decisions_file_appends_to_existing(tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text("# prior\n", encoding="utf-8")
    ping("stop", slug="slug", pr=None, head="h", summary="s",
         ledger=tmp_path / "led.ndjson", decisions=decisions, out=io.StringIO())
    text = decisions.read_text(encoding="utf-8")
    assert text.startswith("# prior\n")
    assert "### [ready-ping] stop ping #-" in text


# --- fail-open --------------------------------------------------------------


def test_ping_never_raises_on_bad_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("led").write_text("not a dir", encoding="utf-8")
    sent = ping("ready", slug="slug", pr=1, head="h", summary="s",
                ledger=Path("led") / "led.ndjson", out=io.StringIO())
    assert sent["status"] == "error"
    assert sent["reason"]


def test_mark_and_kinds():
    assert MARK == "[READY-PING]"
