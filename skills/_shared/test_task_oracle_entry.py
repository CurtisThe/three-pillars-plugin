"""test_task_oracle_entry.py — the plan **Entry point** grammar and its pairing rule.

design: fragile-test-prevention (detailed-design-stages Part A)

Behaviour only: a backticked item is a repo-relative path over any extension,
optionally with ``::qualname`` (dotted identifiers) → ``{path, symbol}``; the
errors name the offending item (unbackticked, leading ``/``, ``.`` / ``..``
segment, non-identifier qualname part, duplicate); ``none`` is ok with no items
but pairs only with Targets ``none``; a canonical render round-trips. Pure: no
git, no filesystem.
"""
from __future__ import annotations

import itertools

import pytest

import task_oracle
import task_targets

A = "pkg/test_a.py"


def _parse(field):
    return task_oracle.parse_entry_point(field)


def test_function_item_gives_path_and_symbol():
    got = _parse("`skills/_shared/x.py::check`")
    assert (got["kind"], got["errors"]) == ("ok", [])
    assert got["items"] == [{"path": "skills/_shared/x.py", "symbol": "check"}]


def test_prose_item_over_any_extension_has_no_symbol():
    got = _parse("`skills/tp-plan/SKILL.md`")
    assert (got["kind"], got["errors"]) == ("ok", [])
    assert got["items"] == [{"path": "skills/tp-plan/SKILL.md", "symbol": None}]


def test_dotted_qualname_is_one_symbol():
    got = _parse("`a/b.py::Cls.meth`")
    assert (got["kind"], got["errors"]) == ("ok", [])
    assert got["items"] == [{"path": "a/b.py", "symbol": "Cls.meth"}]


def test_several_items_keep_their_order_and_free_comma_spacing():
    got = _parse("`skills/_shared/x.py::check` ,`skills/tp-plan/SKILL.md`,  `a/b.py::Cls.meth`")
    assert got["kind"] == "ok"
    assert [(i["path"], i["symbol"]) for i in got["items"]] == [
        ("skills/_shared/x.py", "check"), ("skills/tp-plan/SKILL.md", None),
        ("a/b.py", "Cls.meth")]


def test_none_is_ok_with_no_items():
    got = _parse("none")
    assert (got["kind"], got["items"], got["errors"]) == ("ok", [], [])


def test_absent_field_is_missing():
    got = _parse(None)
    assert (got["kind"], got["items"], got["errors"]) == ("missing", [], [])


@pytest.mark.parametrize("field,wanted", [
    ("skills/_shared/x.py::check", "x.py::check"),           # unbackticked
    ("`a/b.py`, skills/tp-plan/SKILL.md", "SKILL.md"),       # one unbackticked
    ("`/abs/x.py::f`", "/abs/x.py"),                         # leading /
    ("`./x.py::f`", "./x.py"),                               # . segment
    ("`a/../x.py::f`", "a/../x.py"),                         # .. segment
    ("`a/b.py::9lives`", "9lives"),                          # non-identifier qualname
    ("`a/b.py::Cls.9meth`", "9meth"),                        # bad dotted part
    ("`a/b.py::Cls..meth`", "''"),                           # empty dotted part
    ("`a/b.py::`", "''"),                                    # empty qualname
    ("`a/b.py::x`, `a/b.py::x`", "a/b.py::x"),               # duplicate
    ("`a/b.py`, , `c/d.py`", "''"),                          # empty item
    ("", "''"),                                              # present but empty
    ("``", "''"),                                            # empty path
])
def test_malformed_fields_are_malformed_and_name_the_item(field, wanted):
    got = _parse(field)
    assert got["kind"] == "malformed"
    assert any(wanted in e for e in got["errors"]), got["errors"]


def test_path_rule_is_task_targets_public_helper_not_a_copy():
    # one shared segment rule: any extension only when asked, .py otherwise
    assert task_targets.path_errors("skills/tp-plan/SKILL.md", any_ext=True) == []
    assert task_targets.path_errors("skills/tp-plan/SKILL.md")
    assert task_targets.path_errors("a/x.py") == []
    assert task_targets.path_errors("/a/x.py", any_ext=True)
    assert task_targets.path_errors("a/../x.py", any_ext=True)


def test_pair_refuses_entry_none_with_real_targets():
    ok = task_oracle.parse_oracle("example")
    none = _parse("none")
    assert task_oracle.validate_pair(ok, f"`{A}::test_x`", entry_point=none)
    assert task_oracle.validate_pair(ok, None, entry_point=none)


def test_pair_allows_entry_none_with_targets_none():
    none_oracle = task_oracle.parse_oracle("none")
    assert task_oracle.validate_pair(
        none_oracle, "none", entry_point=_parse("none")) == []


def test_pair_accepts_the_raw_field_and_passes_a_real_entry_point():
    ok = task_oracle.parse_oracle("example")
    assert task_oracle.validate_pair(ok, f"`{A}::t`", entry_point="none")
    assert task_oracle.validate_pair(
        ok, f"`{A}::t`", entry_point=_parse("`skills/_shared/x.py::check`")) == []


def test_pair_without_entry_point_is_unchanged():
    ok = task_oracle.parse_oracle("example")
    assert task_oracle.validate_pair(ok, f"`{A}::t`") == []


_ITEMS = ["skills/_shared/x.py::check", "skills/tp-plan/SKILL.md", "a/b.py::Cls.meth",
          "docs/README", "pkg/mod.py::f"]


def test_render_is_canonical_text():
    assert task_oracle.render_entry_point(_parse("none")) == "none"
    assert task_oracle.render_entry_point(
        _parse("`a/b.py::Cls.meth`  ,`skills/tp-plan/SKILL.md`")
    ) == "`a/b.py::Cls.meth`, `skills/tp-plan/SKILL.md`"


def test_render_round_trips_over_all_item_orders():
    for r in range(1, len(_ITEMS) + 1):
        for combo in itertools.permutations(_ITEMS, r):
            parsed = _parse(", ".join(f"`{i}`" for i in combo))
            assert parsed["kind"] == "ok", combo
            assert _parse(task_oracle.render_entry_point(parsed)) == parsed, combo
    assert _parse(task_oracle.render_entry_point(_parse("none"))) == _parse("none")
