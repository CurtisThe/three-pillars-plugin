"""PR numbers in a prose_shape facts payload (cheap-tier-offload PR #191 review r2).

Only a PR-named key's ints and number lists count as PRs; strings anywhere count for
`#N`, `PR N` / `PRs 190 and 191` / `PR-191` and `/pull(s)/N`. Draft-side `PR#N` is
checked case-insensitively.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prose_oracle as po  # noqa: E402

DATE = "2026-09-30"


def _line(ref: str, facts: dict, tmp_path) -> dict:
    return po.check("history_line", f"- {DATE} — cheap tier landed in {ref}.",
                    root=tmp_path, facts=facts)


@pytest.mark.parametrize("facts,ref", [
    ({"date": DATE, "prs": [191], "tests": 225, "phase": 7}, "#225"),
    ({"date": DATE, "prs": [191], "tests": 225, "phase": 7}, "#7"),
    ({"date": DATE, "phase": 3, "tests": 150, "prs": [191]}, "PR #3"),
    ({"date": DATE, "phase": 3, "tests": 150, "prs": [191]}, "#150"),
    ({"change": "191", "prs": []}, "#191"),
])
def test_an_int_or_digit_string_that_is_not_under_a_pr_key_is_not_a_pr(tmp_path, facts, ref):
    v = _line(ref, facts, tmp_path)
    assert v["ok"] is False and "not in the facts" in v["reason"], v


@pytest.mark.parametrize("facts", [
    {"prs": [191]}, {"pr": 191}, {"pr_number": 191}, {"pulls": ["191"]},
    {"merged_prs": [190, 191]}, {"base_pr": 191}, {"PRS": "191"},
])
def test_pr_named_keys_count(tmp_path, facts):
    assert _line("PR #191", facts, tmp_path)["ok"] is True, facts


@pytest.mark.parametrize("facts", [
    {"prs": "PRs 190 and 191"}, {"prs": "PR 190/191"}, {"prs": "190, 191"},
    {"change": "PRs 190 and 191"}, {"change": "PR 190/191, #192"},
    {"change": "landed via PR 190 & 191"},
])
def test_a_facts_string_listing_several_prs_yields_every_number(tmp_path, facts):
    for ref in ("#190", "#191"):
        assert _line(f"PR {ref}", facts, tmp_path)["ok"] is True, (ref, facts)


@pytest.mark.parametrize("facts", [
    {"url": "https://api.github.com/repos/o/r/pulls/191"},
    {"url": "https://github.com/o/r/pull/191"},
    {"change": "merged as PR-191"},
    {"change": "PR 191"},
])
def test_pull_urls_and_pr_prefixes_in_facts_count(tmp_path, facts):
    assert _line("PR #191", facts, tmp_path)["ok"] is True, facts


@pytest.mark.parametrize("facts", [{"PR 191": "merged"}, {"#191": "merged"}])
def test_facts_keys_are_scanned(tmp_path, facts):
    assert _line("PR #191", facts, tmp_path)["ok"] is True, facts


@pytest.mark.parametrize("ref", ["pr#999", "Pr#999", "pR#999", "PR#999"])
def test_pr_hash_n_is_checked_in_any_case(tmp_path, ref):
    v = _line(ref, {"date": DATE, "prs": [191]}, tmp_path)
    assert v["ok"] is False and "#999" in v["reason"], v


# --- PR #191 review r1: the History line's date, and `./` path spans ------------------


def test_history_line_date_must_equal_the_facts_date(tmp_path):
    facts = {"date": DATE, "prs": [191]}
    ok = po.check("history_line", f"- {DATE} — cheap tier landed (#191).",
                  root=tmp_path, facts=facts)
    assert ok["ok"] is True, ok
    for line in ("- 2026-09-29 — cheap tier landed (#191).",
                 "- **2026-10-01** — cheap tier landed (#191)."):
        v = po.check("history_line", line, root=tmp_path, facts=facts)
        assert v["ok"] is False and "facts date" in v["reason"], v
    undated = po.check("history_line", "- 2026-09-29 — landed (#191).", root=tmp_path,
                       facts={"prs": [191]})
    assert undated["ok"] is True, undated  # no facts date: nothing to compare


@pytest.mark.parametrize("span", ["./skills/_shared/nope_does_not_exist.py",
                                  "skills/./_shared/nope_does_not_exist.py"])
def test_dot_segment_phantom_path_is_flagged(span):
    root = Path(__file__).resolve().parents[2]
    v = po.check("history_line", f"- {DATE} — added `{span}`.", root=root, facts={})
    assert v["ok"] is False and "phantom path `skills/_shared/nope_does_not_exist.py`" \
        in v["reason"], v
    real = po.check("history_line", f"- {DATE} — see `./skills/_shared/prose_oracle.py`.",
                    root=root, facts={})
    assert real["ok"] is True, real
