"""test_slow_first.py — junit durations, the slow-first order, the newest other head dir.

design: ci-local-speed-part2 Task 1.5 (Scope 1, Behavior 1)

A 12-minute test that starts last holds the stage's tail. The junit report a previous
head left behind gives the durations; the order is what this module has to get right.
Every cross-check against pytest's own junit naming rule goes through
``mangle_test_address`` itself, so the key rule cannot drift from pytest's.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import slow_first  # noqa: E402
from _pytest.junitxml import mangle_test_address  # noqa: E402  (cross-check only)

NODEIDS = (
    "skills/_shared/test_a.py::test_b",
    "skills/x/test_c.py::TestK::test_d",
    "skills/x/test_c.py::TestK::test_e[a/b-1]",
    "skills/x/test_c.py::test_f[x::y]",
)


def _write_junit(dir_path: Path, body: str, name: str = slow_first.JUNIT_NAME) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{body}</testsuite>'
                    '</testsuites>', encoding="utf-8")
    return path


# ---------------------------------------------------------------- junit_key (a)

@pytest.mark.parametrize("nodeid", NODEIDS)
def test_junit_key_is_pytest_s_own_mangle_rule(nodeid):
    m = mangle_test_address(nodeid)
    assert slow_first.junit_key(nodeid) == (".".join(m[:-1]), m[-1])


def test_junit_key_pinned_by_hand():
    assert slow_first.junit_key("skills/x/test_c.py::TestK::test_d") == (
        "skills.x.test_c.TestK", "test_d")
    assert slow_first.junit_key("skills/x/test_c.py::test_f[x::y]") == (
        "skills.x.test_c", "test_f[x::y]")


# ---------------------------------------------------------------- load (b)

def test_load_takes_the_max_time_per_key_and_skips_the_bad_row(tmp_path):
    _write_junit(
        tmp_path,
        '<testcase classname="skills.x.test_c" name="test_d" time="3.5"/>'
        '<testcase classname="skills.x.test_c" name="test_d" time="9.25"/>'
        '<testcase classname="skills.x.test_c" name="test_e" time="x"/>'
        '<testcase classname="skills._shared.test_a" name="test_b" time="1"/>')
    assert slow_first.load(tmp_path) == {
        ("skills.x.test_c", "test_d"): 9.25,
        ("skills._shared.test_a", "test_b"): 1.0,
    }


def test_load_missing_file_returns_no_data(tmp_path):
    assert slow_first.load(tmp_path) == {}


def test_load_empty_file_returns_no_data(tmp_path):
    (tmp_path / slow_first.JUNIT_NAME).write_text("", encoding="utf-8")
    assert slow_first.load(tmp_path) == {}


def test_load_unparseable_xml_returns_no_data(tmp_path):
    (tmp_path / slow_first.JUNIT_NAME).write_text("<testsuites><oops", encoding="utf-8")
    assert slow_first.load(tmp_path) == {}


def test_load_refuses_a_dtd(tmp_path):
    (tmp_path / slow_first.JUNIT_NAME).write_text(
        '<!DOCTYPE testsuites><testsuites><testsuite>'
        '<testcase classname="a" name="b" time="1"/></testsuite></testsuites>',
        encoding="utf-8")
    assert slow_first.load(tmp_path) == {}


# ---------------------------------------------------------------- order (c)

def test_order_descending_then_unknown_in_input_order():
    # `key=str` maps an item to its junit address, so a bare name keys as ("", name).
    items = ["slow", "mid", "fast", "unknown1", "quick", "unknown2"]
    durs = {("", "slow"): 9.0, ("", "mid"): 5.0, ("", "fast"): 5.0, ("", "quick"): 1.0}
    assert slow_first.order(items, durs, key=str, workers=1) == [
        "slow", "mid", "fast", "quick", "unknown1", "unknown2"]


def test_order_with_no_durations_is_the_input_order():
    items = ["b", "a", "c"]
    assert slow_first.order(items, {}, key=str, workers=1) == ["b", "a", "c"]


# ---------------------------------------------------------------- order under xdist (d)

def test_order_deals_the_slowest_over_xdist_first_chunks():
    items = list("abcdefghij")
    durs = {("", c): float(10 - i) for i, c in enumerate(items)}
    assert slow_first.order(items, durs, key=str, workers=2) == [
        "a", "c", "b", "d", "e", "f", "g", "h", "i", "j"]


def test_order_below_two_per_worker_is_plain_descending():
    items = list("abcdef")
    durs = {("", c): float(6 - i) for i, c in enumerate(items)}
    assert slow_first.order(items, durs, key=str, workers=4) == list("abcdef")


def test_order_with_few_known_items_among_many_new_ones_does_not_raise():
    items = [f"m.py::t{i}" for i in range(3)] + [f"new.py::u{i}" for i in range(37)]
    durs = {("m", f"t{i}"): 100.0 - i for i in range(3)}
    result = slow_first.order(items, durs, key=str, workers=4)
    assert sorted(result) == sorted(items), "a short known list must still deal as a permutation"
    assert set(items[:3]) <= set(result[:8]), "the known tests must start in the workers' first chunks"


@pytest.mark.parametrize("workers", [2, 3, 4, 8])
@pytest.mark.parametrize("unknown", [0, 1, 5, 20, 41])
@pytest.mark.parametrize("known", [0, 1, 2, 3, 5, 9, 17])
def test_order_is_a_permutation_of_its_input_for_every_size(known, unknown, workers):
    items = [f"m.py::t{i}" for i in range(known)] + [f"n.py::u{i}" for i in range(unknown)]
    durs = {("m", f"t{i}"): float(1000 - i) for i in range(known)}
    result = slow_first.order(items, durs, key=str, workers=workers)
    assert len(result) == len(items), f"lost or gained items: {len(result)} != {len(items)}"
    assert sorted(result) == sorted(items), "an item was lost or duplicated"


# ------------------------------------------------------------- newest_other (e)

def test_newest_other_picks_the_other_head_with_the_newest_junit(tmp_path):
    head = tmp_path / "head-a"
    older = tmp_path / "head-b"
    newer = tmp_path / "head-c"
    _write_junit(head, '<testcase classname="a" name="b" time="1"/>')
    p_old = _write_junit(older, '<testcase classname="a" name="b" time="1"/>')
    p_new = _write_junit(newer, '<testcase classname="a" name="b" time="1"/>')
    os.utime(p_old, (1_600_000_000, 1_600_000_000))
    os.utime(p_new, (1_700_000_000, 1_700_000_000))
    assert slow_first.newest_other(tmp_path, head) == newer


def test_newest_other_ignores_dirs_without_the_main_report(tmp_path):
    head = tmp_path / "head-a"
    other = tmp_path / "head-b"
    _write_junit(head, '<testcase classname="a" name="b" time="1"/>')
    _write_junit(other, '<testcase classname="a" name="b" time="1"/>', name="f8.xml")
    assert slow_first.newest_other(tmp_path, head) is None


def test_newest_other_with_a_missing_parent_is_none(tmp_path):
    assert slow_first.newest_other(tmp_path / "nope", tmp_path / "head-a") is None
