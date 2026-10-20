"""Task 1.1 — a skipped (conflicting) ping is recorded as owed in the ledger.

Oracle: example (plan ready-ping-after-basesync 1.1). Every assertion is the
contract text in the task block, never the wording of any SKILL.md. No test
calls the real ``gh``: every helper gets an injected ``info_fn`` and a
``tmp_path`` ledger.
"""

import io
import json
from pathlib import Path

import ready_ping
from ready_ping import ping_ready
from ready_ping_owed import converged_before, owed_pending, record_owed

URL = "https://github.com/o/r/pull/12"


def records(ledger):
    if not Path(ledger).exists():
        return []
    return [json.loads(line) for line in
            Path(ledger).read_text(encoding="utf-8").splitlines() if line.strip()]


def _info(mergeable, ref="tp/s"):
    def info_fn(_url):
        return {"mergeable": mergeable, "headRefName": ref, "title": "T"}
    return info_fn


def test_conflicting_skip_records_owed_entry(tmp_path):
    ledger = tmp_path / "led.ndjson"
    sent = ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=ledger,
                      out=io.StringIO())
    assert sent == {"status": "skipped", "reason": "conflicting"}, (
        f"the skip result must be unchanged, got {sent!r}")
    got = records(ledger)
    assert len(got) == 1, f"one owed record expected, got {got!r}"
    picked = {k: got[0].get(k) for k in ("key", "kind", "head", "slug", "pr")}
    assert picked == {"key": "owed:h1", "kind": "owed", "head": "h1",
                      "slug": "s", "pr": 12}, f"owed record wrong: {got[0]!r}"


def test_repeat_conflicting_skip_does_not_duplicate(tmp_path):
    ledger = tmp_path / "led.ndjson"
    ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=ledger,
               out=io.StringIO())
    again = ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=ledger,
                       out=io.StringIO())
    assert again == {"status": "skipped", "reason": "conflicting"}, (
        "a repeat skip still reports skipped")
    assert len(records(ledger)) == 1, "the same head must not add a second owed"


def test_owed_cleared_by_later_sent_ready_ping(tmp_path):
    ledger = tmp_path / "led.ndjson"
    ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=ledger,
               out=io.StringIO())
    assert owed_pending("s", ledger=ledger) is True, "a skip leaves owed pending"
    sent = ping_ready(URL, "h2", info_fn=_info("MERGEABLE"), ledger=ledger,
                      out=io.StringIO())
    assert sent["status"] == "sent", f"mergeable ping must send, got {sent!r}"
    assert owed_pending("s", ledger=ledger) is False, (
        "a later sent ready ping clears the owed state")


def test_stop_after_owed_leaves_owed_pending(tmp_path):
    ledger = tmp_path / "led.ndjson"
    ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=ledger,
               out=io.StringIO())
    ready_ping.ping("stop", slug="s", pr=None, head="h3", summary="x",
                    ledger=ledger, out=io.StringIO())
    assert [r["kind"] for r in records(ledger)] == ["owed", "stop"], (
        "the stop record must follow the owed one")
    assert owed_pending("s", ledger=ledger) is True, (
        "a stop record is not a ready ping, so owed stays pending")


def test_converged_before_tracks_owed_and_ready(tmp_path):
    missing = tmp_path / "missing.ndjson"
    assert converged_before(missing) is False, "a missing ledger is not converged"

    stop_only = tmp_path / "stop_only.ndjson"
    ready_ping.ping("stop", slug="s", pr=None, head="h3", summary="x",
                    ledger=stop_only, out=io.StringIO())
    assert converged_before(stop_only) is False, (
        "a ledger holding only a stop record is not converged")

    owed = tmp_path / "owed.ndjson"
    ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=owed,
               out=io.StringIO())
    assert converged_before(owed) is True, "an owed record means converged"

    ready = tmp_path / "ready.ndjson"
    ping_ready(URL, "h2", info_fn=_info("MERGEABLE"), ledger=ready,
               out=io.StringIO())
    assert converged_before(ready) is True, "a ready record means converged"


def test_converged_before_honours_a_later_stop(tmp_path):
    demoted = tmp_path / "demoted.ndjson"
    ping_ready(URL, "h1", info_fn=_info("MERGEABLE"), ledger=demoted,
               out=io.StringIO())
    ready_ping.ping("stop", slug="s", pr=None, head="h2", summary="x",
                    ledger=demoted, out=io.StringIO())
    assert [r["kind"] for r in records(demoted)] == ["ready", "stop"]
    assert converged_before(demoted) is False, (
        "a stop after the ready ping means the PR is no longer converged")

    reconverged = tmp_path / "reconverged.ndjson"
    ready_ping.ping("stop", slug="s", pr=None, head="h1", summary="x",
                    ledger=reconverged, out=io.StringIO())
    ping_ready(URL, "h2", info_fn=_info("CONFLICTING"), ledger=reconverged,
               out=io.StringIO())
    assert [r["kind"] for r in records(reconverged)] == ["stop", "owed"]
    assert converged_before(reconverged) is True, (
        "an owed record after the stop means the PR converged again")


def test_unwritable_ledger_still_skips_without_raising(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    ledger = blocker / "led.ndjson"
    sent = ping_ready(URL, "h1", info_fn=_info("CONFLICTING"), ledger=ledger,
                      out=io.StringIO())
    assert sent == {"status": "skipped", "reason": "conflicting"}, (
        "an unwritable ledger must not change the skip result")
    assert record_owed("s", 12, "h1", ledger) is False, (
        "record_owed reports False when it cannot write, and never raises")
