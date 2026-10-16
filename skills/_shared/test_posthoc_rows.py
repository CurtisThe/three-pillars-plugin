"""Tests for posthoc_rows.load: discovery, merge, the null-time rule, bounds, the measure tag.

design: cheap-tier-local-routing 7.1 (detailed-design-posthoc.md, posthoc_rows; plan Task 7.1).
Reads the committed fixture excerpt (fixtures/posthoc/repo) and tmp copies of it, always with
explicit `roots` and an explicit `env` (XDG_STATE_HOME = the fixture dir, which holds the
expired measurement window), so no test reads the operator's state, router log or worktrees.
The tier-reason and FAIL-cause helpers are in test_posthoc_rows_reasons.py.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FIX = HERE / "fixtures" / "posthoc"
pytestmark = pytest.mark.skipif(not (FIX / "repo").is_dir(), reason="no posthoc fixture in this tree")

import cheap_ab_state  # noqa: E402
import posthoc_rows  # noqa: E402

ENV = {"XDG_STATE_HOME": str(FIX)}
DOCS = Path("three-pillars-docs")
TELEMETRY = "dispatch-telemetry.ndjson"
SONNET_START = "2026-10-01T18:37:35.771000Z"  # fixture row 9, the next 2.1 row after the null-time row 8
LOCAL_FAIL_START = "2026-10-01T18:32:22.316000Z"  # fixture row 7, the row that precedes row 8


def _load(root, **kw):
    kw.setdefault("roots", [root])
    kw.setdefault("env", ENV)
    return posthoc_rows.load(root, **kw)


def _copy(tmp_path, name="repo") -> Path:
    dest = tmp_path / name
    shutil.copytree(FIX / "repo", dest)
    return dest


def _design_dir(root, design="fixture-design", sub="tp-designs") -> Path:
    return Path(root) / DOCS / sub / design


def _lines(root, design="fixture-design") -> list[str]:
    return (_design_dir(root, design) / TELEMETRY).read_text(encoding="utf-8").splitlines()


def _write(root, lines, design="fixture-design", sub="tp-designs") -> None:
    path = _design_dir(root, design, sub)
    path.mkdir(parents=True, exist_ok=True)
    (path / TELEMETRY).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(task_id, started_at=None, **extra) -> str:
    row = {"role": "task", "rung": "local-medium", "outcome": "PASS", "task_id": task_id,
           "started_at": started_at, "attempt_key": f"k{task_id}-{started_at}"}
    row.update(extra)
    return json.dumps(row, sort_keys=True)


def _by_key(rows) -> dict:
    return {r.get("attempt_key"): r for r in rows}


def test_fixture_rows_are_all_loaded_and_tagged_with_their_design():
    rows = _load(FIX / "repo")
    assert len(rows) == 11
    assert {r["design"] for r in rows} == {"fixture-design"}
    assert [r["task_id"] for r in rows if r.get("task_id")][:2] == ["1.2", "1.4"]


def test_a_nested_worktree_copy_and_a_completed_pair_do_not_double_rows(tmp_path):
    root = _copy(tmp_path)
    nested = tmp_path / "repo" / ".claude" / "worktrees" / "agent-a1"
    shutil.copytree(FIX / "repo", nested)
    shutil.copytree(_design_dir(root), _design_dir(root, sub="completed-tp-designs"))
    assert len(_load(root, roots=[root, nested])) == 11
    assert len(_load(root, roots=[root])) == 11


def test_merge_keeps_each_line_at_its_largest_count_and_the_union_of_lines(tmp_path):
    base = _lines(FIX / "repo")
    extra = _row("9.1", "2026-10-02T01:00:00Z", attempt_key="late")
    stale = tmp_path / "stale"
    fresh = tmp_path / "fresh"
    _write(stale, base[:6] + [base[5]])  # a stale checkout with row 6 twice, rows 7-11 absent
    _write(fresh, base + [extra])        # a fresher one with every row once, plus a late row
    rows = _load(stale, roots=[stale, fresh])
    keys = [r.get("attempt_key") for r in rows]
    assert len(rows) == 13 and keys.count("4d1bcfefbc362a03") == 2 and keys.count("late") == 1
    assert keys.index("4d1bcfefbc362a03") < keys.index("c2fd0b125d673f4f") < keys.index("late")


def test_rows_of_two_designs_stay_apart_even_with_the_same_line_text(tmp_path):
    root = tmp_path / "repo"
    same = [_row("1.1", "2026-10-01T10:00:00Z")]
    _write(root, same, design="alpha")
    _write(root, same, design="beta")
    assert sorted(r["design"] for r in _load(root)) == ["alpha", "beta"]


def test_malformed_lines_and_a_missing_root_are_skipped_never_raised(tmp_path):
    root = tmp_path / "repo"
    _write(root, ["not json", "[1, 2]", "", _row("1.1", "2026-10-01T10:00:00Z")])
    assert [r["task_id"] for r in _load(root)] == ["1.1"]
    assert _load(tmp_path / "absent") == []


def test_a_null_time_row_takes_the_next_timed_row_of_its_own_task():
    rows = _by_key(_load(FIX / "repo"))
    null_xhigh = rows["c2fd0b125d673f4f"]
    assert null_xhigh["started_at"] is None
    assert null_xhigh["time"] == SONNET_START and null_xhigh["time_src"] == "task"
    assert rows["d6132897c787165f"]["time_src"] == "own"


def test_without_a_same_task_row_a_null_time_row_takes_the_preceding_then_the_next(tmp_path):
    root = tmp_path / "repo"
    _write(root, [_row("1.1", "2026-10-01T10:00:00Z"), _row("1.2", None, attempt_key="mid"),
                  _row("1.3", "2026-10-01T11:00:00Z")])
    mid = _by_key(_load(root))["mid"]
    assert (mid["time"], mid["time_src"]) == ("2026-10-01T10:00:00Z", "before")
    _write(root, [_row("2.1", None, attempt_key="first"), _row("2.2", "2026-10-01T12:00:00Z")])
    first = _by_key(_load(root))["first"]
    assert (first["time"], first["time_src"]) == ("2026-10-01T12:00:00Z", "after")
    # the generator and reader rows (no task_id) never pair with each other: they take the preceding row
    gen = [r for r in _load(FIX / "repo") if r["role"] in ("generator", "reader")]
    assert {r["time"] for r in gen} == {SONNET_START} and {r["time_src"] for r in gen} == {"before"}


def test_a_row_with_no_timed_row_anywhere_is_kept_unbounded_and_dropped_when_bounded(tmp_path):
    root = tmp_path / "repo"
    _write(root, [_row("1.1", None, attempt_key="lonely")])
    (only,) = _load(root)
    assert only["time"] is None and only["time_src"] is None and only["measure"] == "off"
    assert _load(root, until="2026-12-31T00:00:00Z") == []
    assert _load(root, since="2000-01-01T00:00:00Z") == []


def test_until_prefers_the_same_task_row_only_while_it_is_at_or_before_until(tmp_path):
    root = _copy(tmp_path)
    until = "2026-10-01T18:36:00Z"  # row 9 (18:37:35) is past it
    first = _by_key(_load(root, until=until))
    assert first["c2fd0b125d673f4f"]["time"] == LOCAL_FAIL_START  # falls to the preceding timed row
    assert first["c2fd0b125d673f4f"]["time_src"] == "before"
    with (_design_dir(root) / TELEMETRY).open("a", encoding="utf-8") as fh:  # a later 2.1 retry, past until
        fh.write(_row("2.1", "2026-10-01T19:00:00Z", attempt_key="retry-late") + "\n")
    second = _by_key(_load(root, until=until))
    assert set(second) == set(first)  # the bounded set is unchanged by that retry
    assert second["c2fd0b125d673f4f"]["time"] == LOCAL_FAIL_START
    unbounded = _by_key(_load(root))
    assert unbounded["c2fd0b125d673f4f"]["time"] == SONNET_START


def test_a_same_task_row_at_exactly_until_still_counts(tmp_path):
    root = _copy(tmp_path)
    row = _by_key(_load(root, until=SONNET_START))["c2fd0b125d673f4f"]
    assert (row["time"], row["time_src"]) == (SONNET_START, "task")


def test_since_and_until_filter_on_the_time_inclusively():
    keys = lambda **kw: {r.get("attempt_key") for r in _load(FIX / "repo", **kw)}  # noqa: E731
    both = keys(since="2026-10-01T18:00:37.277000Z", until="2026-10-01T18:32:22.316000Z")
    # rows 6 and 7 at the two bounds, plus null-time row 8, which falls back to row 7's time
    assert both == {"4d1bcfefbc362a03", "1d644010b9d47cf0", "c2fd0b125d673f4f"}
    assert len(keys(until="2026-09-30T03:00:08.678696Z")) == 2  # rows 1 and 2, bound inclusive
    assert "1e48234767b4a6c1" not in keys(since="2026-10-01T00:00:00Z")
    assert keys(since="2027-01-01T00:00:00Z") == set()


def test_since_and_until_accept_datetimes_and_a_naive_stamp_is_utc():
    import datetime as dt
    aware = dt.datetime(2026, 10, 1, 18, 33, tzinfo=dt.timezone.utc)
    naive = dt.datetime(2026, 10, 1, 18, 33)
    assert len(_load(FIX / "repo", since=aware)) == len(_load(FIX / "repo", since=naive))
    with pytest.raises(ValueError):
        _load(FIX / "repo", since="yesterday")


def test_measure_comes_from_the_expired_window_by_row_time():
    rows = _by_key(_load(FIX / "repo"))
    assert rows["4d1bcfefbc362a03"]["measure"] == "owner"  # 18:00:37Z inside 17:55-18:35Z
    assert rows["1d644010b9d47cf0"]["measure"] == "owner"
    assert rows["d6132897c787165f"]["measure"] == "off"    # 09-30
    assert rows["51a34fccdfe13e5a"]["measure"] == "off"    # 18:37:35Z, past the window's end
    assert rows["c2fd0b125d673f4f"]["measure"] == "off"    # null time, borrowed 18:37:35Z


def test_another_design_inside_the_window_is_other_and_a_rows_own_measure_wins(tmp_path):
    root = tmp_path / "repo"
    _write(root, [_row("1.1", "2026-10-01T18:00:00Z"), _row("1.2", "2026-10-01T18:01:00Z", measure="other")],
           design="not-the-owner")
    _write(root, [_row("1.1", "2026-10-01T18:02:00Z", measure="off")])
    got = {(r["design"], r["task_id"]): r["measure"] for r in _load(root)}
    assert got == {("not-the-owner", "1.1"): "other", ("not-the-owner", "1.2"): "other",
                   ("fixture-design", "1.1"): "off"}


def test_measure_follows_env_so_a_missing_state_dir_means_no_window(tmp_path):
    rows = _load(FIX / "repo", env={"XDG_STATE_HOME": str(tmp_path / "nowhere")})
    assert {r["measure"] for r in rows} == {"off"}


def test_roots_default_to_the_repo_worktrees(monkeypatch):
    seen = []
    monkeypatch.setattr(cheap_ab_state, "worktree_roots", lambda root: seen.append(root) or [FIX / "repo"])
    rows = posthoc_rows.load(FIX / "repo", env=ENV)
    assert seen == [FIX / "repo"] and len(rows) == 11
