"""`round_scratch.prepare` stamps the round start into the iterate-state file.

design: fable-first-stops (Task 1.1). The stamp is `budget_round_started_at`; the
budget tick later folds `now - stamp` into `budget_active_elapsed_sec`. A missing
state file stays absent (`prepare` never bootstraps), and an unreadable one is left
byte-identical for `run_round` to refuse.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402
import iterate_state  # noqa: E402
import round_scratch as rs  # noqa: E402

PR = "https://github.com/o/r/pull/42"
NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _prep(root, state_path, **kw):
    return rs.prepare(root, PR, angles.DEFAULT_ANGLES, base="b0", head="h1", effort="high",
                      state_path=str(state_path), log_path=str(root / "log.md"), **kw)


def _state(root) -> Path:
    path = root / "iterate-state.42.v1.json"
    state = iterate_state.fresh_state(now="2026-09-24T10:00:00+00:00")
    state.update(budget_pr_url=PR, iteration=2, budget_active_elapsed_sec=77.5)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_prepare_stamps_an_aware_round_start_and_nothing_else(tmp_path):
    path = _state(tmp_path)
    before = _load(path)
    _prep(tmp_path, path)
    after = _load(path)
    stamp = after.pop("budget_round_started_at")
    assert datetime.fromisoformat(stamp).tzinfo is not None
    assert after == before  # every other field unchanged
    assert abs(datetime.now(tz=timezone.utc) - datetime.fromisoformat(stamp)) < timedelta(minutes=1)


def test_manifest_records_the_same_started_at(tmp_path):
    path = _state(tmp_path)
    r = _prep(tmp_path, path, now=NOW)
    manifest = _load(r / "angles.json")
    assert manifest["started_at"] == NOW.isoformat()
    assert _load(path)["budget_round_started_at"] == manifest["started_at"]


def test_stamp_goes_through_write_state_atomic(tmp_path, monkeypatch):
    path = _state(tmp_path)
    calls = []
    real = iterate_state.write_state_atomic
    monkeypatch.setattr(iterate_state, "write_state_atomic",
                        lambda p, s: (calls.append((Path(p), dict(s))), real(p, s))[1])
    _prep(tmp_path, path, now=NOW)
    assert [c[0] for c in calls] == [path]
    assert calls[0][1]["budget_round_started_at"] == NOW.isoformat()
    assert not list(tmp_path.glob("iterate-state.42.v1.json.tmp.*"))


def test_missing_state_file_stays_absent(tmp_path):
    path = tmp_path / "iterate-state.42.v1.json"
    r = _prep(tmp_path, path, now=NOW)
    assert not path.exists()
    assert _load(r / "angles.json")["started_at"] == NOW.isoformat()


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", ""])
def test_unreadable_or_non_object_state_is_left_untouched(tmp_path, raw):
    path = tmp_path / "iterate-state.42.v1.json"
    path.write_text(raw, encoding="utf-8")
    _prep(tmp_path, path, now=NOW)
    assert path.read_text(encoding="utf-8") == raw


def test_second_round_restamps_the_start(tmp_path):
    path = _state(tmp_path)
    r1 = _prep(tmp_path, path, now=NOW)
    (r1 / "tail" / "envelope.json").write_text(json.dumps({"action": "fix"}), encoding="utf-8")
    later = NOW + timedelta(hours=3)
    _prep(tmp_path, path, now=later)
    assert _load(path)["budget_round_started_at"] == later.isoformat()


def test_refused_prepare_does_not_stamp(tmp_path):
    path = _state(tmp_path)
    r1 = _prep(tmp_path, path, now=NOW)
    # r1 has no tail envelope: the next prepare refuses (TailFailed) before stamping.
    with pytest.raises(rs.TailFailed):
        _prep(tmp_path, path, now=NOW + timedelta(hours=1))
    assert _load(path)["budget_round_started_at"] == NOW.isoformat()
    assert r1.is_dir()
