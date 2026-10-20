"""Task 1.2 — rearm: a converged PR re-arms the ready state after a base-sync.

Oracle: example (plan ready-ping-after-basesync 1.2). Every assertion is the
contract text in the task block, never the wording of any SKILL.md. No test
calls the real ``gh`` or the real label manager: every helper gets an injected
``info_fn``, ``label_fn``, ``push_fn``, ``sleep_fn`` and a ``tmp_path`` ledger.
Scripted info values are full info dicts, never bare status strings.
"""

import io
import json
from pathlib import Path

from ready_ping_owed import record_owed
from ready_ping_rearm import main, rearm

URL = "https://github.com/o/r/pull/12"
LABEL = "tp:ready-for-human-merge"


def info(mergeable, ref="tp/s", title="T"):
    return {"mergeable": mergeable, "headRefName": ref, "title": title}


def script(*states):
    """An info_fn yielding one full info dict per call; the last value repeats."""
    values = [info(state) for state in states]
    calls = []

    def info_fn(_url):
        calls.append(_url)
        return values[min(len(calls), len(values)) - 1]

    info_fn.calls = calls
    return info_fn


class Recorder:
    """Records each call; optionally raises after recording."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, *args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("boom")


def converged_ledger(tmp_path, head="h1"):
    """A ledger holding an owed:<head> record, i.e. the PR once converged."""
    ledger = str(tmp_path / "ledger.ndjson")
    record_owed("s", 12, head, ledger)
    return ledger


def records(ledger):
    path = Path(ledger)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def keys(ledger):
    return [rec.get("key") for rec in records(ledger)]


def test_a_empty_ledger_is_not_converged_and_arms_nothing(tmp_path):
    ledger = str(tmp_path / "ledger.ndjson")
    label, push = Recorder(), Recorder()
    result = rearm(
        URL, "h2", info_fn=script("MERGEABLE"), label_fn=label, ledger=ledger,
        push_fn=push, out=io.StringIO(), err=io.StringIO(), sleep_fn=lambda _s: None,
    )
    assert result == {"status": "skipped", "reason": "not-converged"}, (
        f"an unconverged PR must skip with not-converged, got {result!r}")
    assert label.calls == [], "an unconverged PR must not touch the label"
    assert push.calls == [], "an unconverged PR must not send a ping"


def test_b_converged_and_mergeable_sends_one_ping_and_sets_label(tmp_path):
    ledger = converged_ledger(tmp_path)
    label, push = Recorder(), Recorder()
    result = rearm(
        URL, "h2", info_fn=script("MERGEABLE"), label_fn=label, ledger=ledger,
        push_fn=push, out=io.StringIO(), err=io.StringIO(), sleep_fn=lambda _s: None,
    )
    assert label.calls == [(URL, LABEL)], f"label must be set once, got {label.calls!r}"
    assert len(push.calls) == 1, f"exactly one ping expected, got {len(push.calls)}"
    assert result["label"] == "set", f"label must read set, got {result.get('label')!r}"
    assert result["ready_ping"]["status"] == "sent", (
        f"ready ping must be sent, got {result.get('ready_ping')!r}")


def test_c_second_call_for_same_head_is_a_duplicate(tmp_path):
    ledger = converged_ledger(tmp_path)
    push = Recorder()
    kwargs = dict(
        info_fn=script("MERGEABLE"), label_fn=Recorder(), ledger=ledger,
        push_fn=push, out=io.StringIO(), err=io.StringIO(), sleep_fn=lambda _s: None,
    )
    rearm(URL, "h2", **kwargs)
    again = rearm(URL, "h2", **kwargs)
    assert again["ready_ping"]["status"] == "duplicate", (
        f"the same head must not ping twice, got {again.get('ready_ping')!r}")
    assert len(push.calls) == 1, f"no second push expected, got {len(push.calls)}"


def test_d_conflicting_is_not_mergeable_and_stays_owed(tmp_path):
    ledger = converged_ledger(tmp_path)
    label, push, err = Recorder(), Recorder(), io.StringIO()
    result = rearm(
        URL, "h2", info_fn=script("CONFLICTING"), label_fn=label, ledger=ledger,
        push_fn=push, out=io.StringIO(), err=err, sleep_fn=lambda _s: None,
    )
    assert result.get("reason") == "not-mergeable", f"got {result!r}"
    assert label.calls == [], "a conflicting PR must not get the label"
    assert push.calls == [], "a conflicting PR must not get a ping"
    lines = err.getvalue().splitlines()
    assert len(lines) == 1 and "still owed" in lines[0], (
        f"err must hold exactly one still-owed line, got {lines!r}")
    assert "owed:h2" in keys(ledger), f"owed:h2 must be recorded, keys={keys(ledger)!r}"


def test_e_unknown_then_mergeable_polls_and_sends(tmp_path):
    ledger = converged_ledger(tmp_path)
    sleeps, label, push = [], Recorder(), Recorder()
    result = rearm(
        URL, "h2", info_fn=script("UNKNOWN", "UNKNOWN", "MERGEABLE"), label_fn=label,
        ledger=ledger, push_fn=push, out=io.StringIO(), err=io.StringIO(),
        attempts=4, sleep_fn=sleeps.append,
    )
    assert result["ready_ping"]["status"] == "sent", f"got {result!r}"
    assert len(sleeps) == 2, f"two sleeps between three polls, got {len(sleeps)}"
    assert len(label.calls) == 1, "the settled MERGEABLE state sets the label once"


def test_e_unknown_on_every_attempt_is_not_mergeable_and_owed(tmp_path):
    ledger = converged_ledger(tmp_path)
    sleeps, label, push = [], Recorder(), Recorder()
    result = rearm(
        URL, "h2", info_fn=script("UNKNOWN"), label_fn=label, ledger=ledger,
        push_fn=push, out=io.StringIO(), err=io.StringIO(),
        attempts=4, sleep_fn=sleeps.append,
    )
    assert result.get("reason") == "not-mergeable", f"got {result!r}"
    assert len(sleeps) == 3, f"attempts - 1 sleeps expected, got {len(sleeps)}"
    assert "owed:h2" in keys(ledger), f"owed:h2 must be recorded, keys={keys(ledger)!r}"
    assert label.calls == [] and push.calls == [], "an unsettled PR gets neither"


def test_f_empty_info_is_mergeability_unavailable(tmp_path):
    ledger = converged_ledger(tmp_path)
    label, push, err = Recorder(), Recorder(), io.StringIO()
    result = rearm(
        URL, "h2", info_fn=lambda _u: {}, label_fn=label, ledger=ledger,
        push_fn=push, out=io.StringIO(), err=err, sleep_fn=lambda _s: None,
    )
    assert result.get("reason") == "mergeability-unavailable", f"got {result!r}"
    lines = err.getvalue().splitlines()
    assert len(lines) == 1, f"one line must say mergeability is unavailable, got {lines!r}"
    assert label.calls == [] and push.calls == [], "no label and no ping without info"


def test_g_label_failure_still_sends_the_ping(tmp_path):
    ledger = converged_ledger(tmp_path)
    label, push = Recorder(fail=True), Recorder()
    result = rearm(
        URL, "h2", info_fn=script("MERGEABLE"), label_fn=label, ledger=ledger,
        push_fn=push, out=io.StringIO(), err=io.StringIO(), sleep_fn=lambda _s: None,
    )
    assert result["label"].startswith("failed"), f"label must read failed, got {result!r}"
    assert result["ready_ping"]["status"] == "sent", "the ping goes out regardless"
    assert len(push.calls) == 1, f"exactly one ping expected, got {len(push.calls)}"


def test_h_cli_missing_required_arg_prints_json_error_and_exits_0(capsys):
    rc = main(["--pr-url", "https://github.com/o/r/pull/12"])
    assert rc == 0, "the CLI is fail-open: a usage error still exits 0"
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"exactly one JSON line on stdout, got {lines!r}"
    doc = json.loads(lines[0])
    assert doc["status"] == "error" and doc.get("reason"), (
        f"a usage error reports the error shape, got {doc!r}")
