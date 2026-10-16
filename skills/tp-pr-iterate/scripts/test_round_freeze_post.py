"""round_freeze.post — deferred follow-ups post ONCE, and degrade LOUDLY.

design: review-convergence (Task 5.4, detailed-design-pr-loop §D2)

At a terminal the loop posts the accumulated `follow-up.json` items as one PR
comment through the forge chokepoint. Two behaviours are pinned here:

* **once** — a successful post empties the store, so a re-run (a resumed loop, a
  second terminal) cannot post the same note twice;
* **never silent** — when the forge degrades (no `gh`, no token, an unsupported
  host, a raising poster), the items are appended to the loop log (which
  `round_scratch.py flush` moves into `decisions.md`, where `/tp-design-learn`
  picks them up) and one line is printed:
  `follow-up: forge comment degraded (<kind>); N item(s) logged to decisions.md`.

`post_fn(pr_url, body) -> bool` is the test seam (the same shape
`review_merge.post_codereview_comment` takes); the default `_default_post` goes
through `forge.comment_post`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import round_freeze as rf  # noqa: E402 — first: it puts skills/_shared on sys.path
import forge  # noqa: E402

PR = "https://github.com/o/r/pull/42"
LINE = "follow-up: forge comment degraded ("
LOG_LINES = ["frozen-follow-up: a1.py: note 1", "frozen-follow-up: a2.py: note 2"]


def _item(n):
    return {"file": f"a{n}.py", "summary": f"note {n}", "verdict": "minor",
            "blocking": False, "comment_id": n, "reason": "frozen-follow-up"}


def _store(root, items):
    """`<root>/rounds/42/follow-up.json` with `items`, plus the loop log's location."""
    d = root / "rounds" / "42"
    d.mkdir(parents=True)
    (d / rf.FOLLOW_UP).write_text(json.dumps(items), encoding="utf-8")
    return d, root / "iterate-log.42.md"


def _log_lines(log):
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _poster(calls, ok=True):
    def post(pr_url, body):
        calls.append((pr_url, body))
        return ok
    return post


# ---------- posts once ----------


def test_post_posts_the_items_once_and_empties_the_store(tmp_path, capsys):
    d, log = _store(tmp_path, [_item(1), _item(2)])
    calls = []
    body = rf.post(PR, d, post_fn=_poster(calls))
    assert len(calls) == 1 and calls[0][0] == PR
    assert "note 1" in body and "note 2" in body
    assert "a1.py" in body and "a2.py" in body
    assert not (d / rf.FOLLOW_UP).exists()  # posted → spent
    assert not log.exists()                # nothing degraded → nothing logged
    assert LINE not in capsys.readouterr().out


def test_second_post_of_a_spent_store_posts_nothing(tmp_path):
    """A resumed loop reaching a second terminal must not re-post the same notes."""
    d, _log = _store(tmp_path, [_item(1)])
    calls = []
    rf.post(PR, d, post_fn=_poster(calls))
    assert rf.post(PR, d, post_fn=_poster(calls)) == ""
    assert len(calls) == 1


def test_post_with_an_empty_store_posts_nothing(tmp_path):
    d = tmp_path / "rounds" / "42"
    d.mkdir(parents=True)
    calls = []
    assert rf.post(PR, d, post_fn=_poster(calls)) == ""
    assert calls == []


def test_post_body_carries_the_deferral_reason(tmp_path):
    d, _log = _store(tmp_path, [_item(1)])
    body = rf.post(PR, d, post_fn=_poster([]))
    assert "frozen-follow-up" in body


# ---------- degraded forge: log line, never silent ----------


def test_failing_post_fn_logs_the_items_and_prints_one_line(tmp_path, capsys):
    d, log = _store(tmp_path, [_item(1), _item(2)])
    assert rf.post(PR, d, post_fn=lambda url, body: False) == ""
    assert _log_lines(log) == LOG_LINES
    out = capsys.readouterr().out
    assert out.count(LINE) == 1
    assert f"{LINE}post-failed); 2 item(s) logged to decisions.md)" in out
    assert not (d / rf.FOLLOW_UP).exists()  # the items live in the log, never re-posted


def test_raising_post_fn_degrades_the_same_way(tmp_path, capsys):
    def boom(url, body):
        raise RuntimeError("network down")
    d, log = _store(tmp_path, [_item(1)])
    assert rf.post(PR, d, post_fn=boom) == ""
    assert _log_lines(log) == LOG_LINES[:1]
    out = capsys.readouterr().out
    assert f"{LINE}RuntimeError); 1 item(s) logged to decisions.md)" in out


def test_degraded_forge_result_logs_the_forge_line(tmp_path, capsys, monkeypatch):
    """No `post_fn` → the real forge chokepoint; a degraded `Result` degrades loudly
    with the forge's own actionable line as the kind (Gitea parity: visible, never
    silent)."""
    def degraded(repo, number, body, **kw):
        return forge.Result.degraded("comment-post: gitea token missing — set TEA_TOKEN")
    monkeypatch.setattr(rf.forge, "comment_post", degraded)
    d, log = _store(tmp_path, [_item(1)])
    assert rf.post(PR, d) == ""
    assert _log_lines(log) == LOG_LINES[:1]
    out = capsys.readouterr().out
    assert f"{LINE}comment-post: gitea token missing — set TEA_TOKEN); " \
           "1 item(s) logged to decisions.md)" in out


def test_log_write_failure_still_prints_the_line(tmp_path, capsys):
    """A log path that cannot be written (it is a directory) must not silence the
    degrade — the printed line is the operator's only signal."""
    d, log = _store(tmp_path, [_item(1)])
    log.mkdir()
    assert rf.post(PR, d, post_fn=lambda url, body: False) == ""
    out = capsys.readouterr().out
    assert f"{LINE}post-failed); 1 item(s) logged to decisions.md)" in out


# ---------- CLI ----------


def test_cli_is_frozen_exits_zero_when_frozen(tmp_path):
    path = tmp_path / "iterate-state.42.v1.json"
    path.write_text(json.dumps({"phase": "awaiting-review", "frozen_at": "abc1234"}),
                    encoding="utf-8")
    assert rf.main(["is-frozen", "--state-path", str(path)]) == 0


def test_cli_is_frozen_exits_one_when_not_frozen(tmp_path):
    path = tmp_path / "iterate-state.42.v1.json"
    path.write_text(json.dumps({"phase": "awaiting-review", "frozen_at": None}),
                    encoding="utf-8")
    assert rf.main(["is-frozen", "--state-path", str(path)]) == 1


def test_cli_is_frozen_exits_one_when_the_state_is_absent(tmp_path):
    assert rf.main(["is-frozen", "--state-path", str(tmp_path / "nope.json")]) == 1


def test_cli_post_uses_the_root_and_the_pr_number(tmp_path, monkeypatch):
    d, _log = _store(tmp_path, [_item(1)])
    calls = []

    def stub(pr_url, body, repo="."):
        calls.append((pr_url, body, repo))
        return True

    monkeypatch.setattr(rf, "_default_post", stub)
    assert rf.main(["post", "--pr-url", PR, "--root", str(tmp_path)]) == 0
    assert len(calls) == 1 and calls[0][0] == PR
    assert not (d / rf.FOLLOW_UP).exists()
