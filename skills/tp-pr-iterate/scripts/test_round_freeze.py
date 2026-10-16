"""round_freeze — the clean-round freeze, its partition, its follow-up store.

design: review-convergence (Task 5.4, detailed-design-pr-loop §D2)

A review round with **0 blocking findings and no degraded sentinel** freezes the loop's
bar: `mark_if_clean` records `frozen_at` = that round's head into the iterate-state file,
and from then on `partition` keeps only the structural (blocking) fixes and defers every
other item as a `frozen-follow-up`. Deferred items accumulate in
`<proof_root>/rounds/<pr>/follow-up.json` (`add_follow_ups`, idempotent per item) —
`test_round_freeze_post.py` covers the post/degrade half.

The filesystem half mirrors `budget_clock.stamp_round_start`: a missing, non-regular or
unreadable `state_path` answers False, changes nothing and raises nothing, because
`run_round` owns the bootstrap and this module must never become a second writer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import iterate_state  # noqa: E402
import round_freeze as rf  # noqa: E402

HEAD = "abc1234def5678abc1234def5678abc1234def"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "iterate-state.v1.json"


def _minor(**kw):
    f = {"file": "a.py", "summary": "tighten the test", "line_range": [3, 4],
         "verdict": "minor", "blocking": False, "class": "T"}
    f.update(kw)
    return f


def _structural(**kw):
    f = {"file": "b.py", "summary": "crash on an empty list", "line_range": [9, 9],
         "verdict": "structural", "blocking": True, "class": "P",
         "reproducer": {"kind": "command", "argv": ["true"], "expect": {"exit": 0}}}
    f.update(kw)
    return f


def _sentinels():
    """Both degraded-review sentinel shapes."""
    return [{"source": "no-angles", "summary": "no angle replied"},
            {"file": "<review-output:unparseable>", "summary": "junk reply"}]


def _state_file(root, **kw):
    """A schema-shaped iterate-state for PR 42, written as `run_round` would."""
    path = root / "iterate-state.42.v1.json"
    state = iterate_state.fresh_state(now="2026-10-01T10:00:00+00:00")
    state.update(kw)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- mark_if_clean: the verdict half ----------


def test_marks_when_nothing_blocks(tmp_path):
    """0 blocking findings (real minors present) → the freeze lands on the head."""
    path = _state_file(tmp_path, iteration=2, last_verdict="minor-only")
    before = _load(path)
    assert rf.mark_if_clean(path, HEAD, [_minor()]) is True
    after = _load(path)
    assert after["frozen_at"] == HEAD
    before.pop("frozen_at", None)
    after.pop("frozen_at")
    assert after == before  # every other field unchanged


def test_marks_on_an_empty_finding_list(tmp_path):
    path = _state_file(tmp_path)
    assert rf.mark_if_clean(path, HEAD, []) is True
    assert _load(path)["frozen_at"] == HEAD


def test_does_not_mark_when_a_finding_blocks(tmp_path):
    path = _state_file(tmp_path)
    original = path.read_bytes()
    assert rf.mark_if_clean(path, HEAD, [_minor(), _structural()]) is False
    assert path.read_bytes() == original


def test_does_not_mark_on_a_degraded_sentinel(tmp_path):
    """A degraded review is not a clean review — a 0-blocker round with a sentinel
    must not freeze, or an unavailable reviewer would silence every later note."""
    for sentinel in _sentinels():
        path = _state_file(tmp_path)
        original = path.read_bytes()
        assert rf.mark_if_clean(path, HEAD, [sentinel]) is False, sentinel
        assert path.read_bytes() == original, sentinel


def test_a_downgraded_or_refuted_blocker_does_not_prevent_the_mark(tmp_path):
    """`severity.is_blocking` is the only bar: Opus downgraded it or a reproducer
    refuted it, so the round is clean and freezes."""
    downgraded = _structural(escape={"disposition": "downgraded"})
    refuted = _structural(reproduction="refuted")
    path = _state_file(tmp_path)
    assert rf.mark_if_clean(path, HEAD, [downgraded, refuted]) is True
    assert _load(path)["frozen_at"] == HEAD


def test_marked_state_still_validates_against_the_schema(tmp_path):
    """The schema gains `frozen_at` (string or null) — the mark this writes must be
    schema-valid, since converge's `_seed_state` carries it across rounds (Task 5.5)."""
    path = _state_file(tmp_path)
    assert rf.mark_if_clean(path, HEAD, []) is True
    Draft202012Validator(_load(SCHEMA_PATH)).validate(_load(path))
    Draft202012Validator(_load(SCHEMA_PATH)).validate(_load(_state_file(tmp_path)))


# ---------- mark_if_clean: the filesystem half (mirrors stamp_round_start) ----------


def test_missing_state_path_marks_nothing_and_creates_no_file(tmp_path):
    path = tmp_path / "iterate-state.42.v1.json"
    assert rf.mark_if_clean(path, HEAD, []) is False
    assert not path.exists()  # run_round owns the bootstrap


def test_non_regular_state_path_is_refused_without_raising(tmp_path):
    path = tmp_path / "iterate-state.42.v1.json"
    os.mkfifo(path)
    assert rf.mark_if_clean(path, HEAD, []) is False  # a FIFO read would hang the round
    assert path.is_fifo()


def test_unreadable_state_path_is_left_byte_identical(tmp_path):
    for junk in (b"{not json", b'["a", "b"]', b""):
        path = tmp_path / "iterate-state.42.v1.json"
        path.write_bytes(junk)
        assert rf.mark_if_clean(path, HEAD, []) is False, junk
        assert path.read_bytes() == junk, junk


# ---------- is_frozen ----------


@pytest.mark.parametrize("state,frozen", [
    ({}, False),
    ({"frozen_at": None}, False),
    ({"frozen_at": ""}, False),
    ({"frozen_at": "   "}, False),
    ({"frozen_at": HEAD}, True),
    (None, False),
])
def test_is_frozen_reads_the_mark(state, frozen):
    assert rf.is_frozen(state) is frozen


# ---------- partition ----------


def test_partition_not_frozen_keeps_everything():
    items = [_structural(), _minor()]
    keep, defer = rf.partition(items, False)
    assert keep == items
    assert defer == []


def test_partition_frozen_keeps_only_structural():
    blocker, minor = _structural(), _minor()
    keep, defer = rf.partition([blocker, minor, _minor(summary="rename")], True)
    assert keep == [blocker]
    assert len(defer) == 2
    assert {d["summary"] for d in defer} == {"tighten the test", "rename"}


def test_partition_deferred_items_carry_the_frozen_reason():
    """The deferred shape is `fix_round`'s `fixes_deferred` entry: item + reason."""
    _keep, defer = rf.partition([_minor(comment_id=7)], True)
    assert defer[0]["reason"] == "frozen-follow-up"
    assert defer[0]["comment_id"] == 7
    assert defer[0]["file"] == "a.py"


def test_partition_never_mutates_its_input():
    items = [_minor(), _structural()]
    before = [dict(f) for f in items]
    rf.partition(items, True)
    assert items == before


def test_partition_of_nothing():
    assert rf.partition([], True) == ([], [])


# ---------- add_follow_ups ----------


def _pr_dir(tmp_path):
    d = tmp_path / "proof" / "rounds" / "42"
    d.mkdir(parents=True)
    return d


def test_add_follow_ups_creates_the_store_and_counts(tmp_path):
    d = _pr_dir(tmp_path)
    assert rf.add_follow_ups(d, [_minor(reason="frozen-follow-up")]) == 1
    assert rf.FOLLOW_UP == "follow-up.json"
    assert (d / rf.FOLLOW_UP).is_file()
    assert rf.add_follow_ups(d, [_minor(summary="second", reason="frozen-follow-up")]) == 1
    stored = _load(d / rf.FOLLOW_UP)
    assert len(stored) == 2
    assert {s["summary"] for s in stored} == {"tighten the test", "second"}


def test_add_follow_ups_is_idempotent_per_comment_id(tmp_path):
    """A re-partitioned round must not post the same deferred item twice."""
    d = _pr_dir(tmp_path)
    item = _minor(comment_id=11, reason="frozen-follow-up")
    assert rf.add_follow_ups(d, [item]) == 1
    assert rf.add_follow_ups(d, [dict(item)]) == 0
    assert rf.add_follow_ups(d, [dict(item, comment_id=12)]) == 1
    assert len(_load(d / rf.FOLLOW_UP)) == 2


def test_add_follow_ups_recovers_from_a_corrupt_store(tmp_path):
    d = _pr_dir(tmp_path)
    (d / rf.FOLLOW_UP).write_text("{broken", encoding="utf-8")
    assert rf.add_follow_ups(d, [_minor(reason="frozen-follow-up")]) == 1
    assert len(_load(d / rf.FOLLOW_UP)) == 1


def test_add_follow_ups_with_nothing_writes_nothing(tmp_path):
    d = _pr_dir(tmp_path)
    assert rf.add_follow_ups(d, []) == 0
    assert not (d / rf.FOLLOW_UP).exists()
