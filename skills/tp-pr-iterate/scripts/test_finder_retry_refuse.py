"""Task 1.10: what `finder_retry.retry` refuses or answers instead of two halves.

design: finder-cap-coverage (Behavior 2) — an unsplittable segment takes `settle`'s
Sonnet transition; a retry past the per-angle budget answers `uncovered` and marks
the entry; a retry of anything but an unmarked first attempt on Strata exits 2;
and the whole chain (split, a half capped on Strata, capped again on Sonnet) lands
the half's files uncovered with no hand-set field. The CLI reads the diff from the
repo. The fixtures are `test_finder_retry_retry`'s, built the way
`round_scratch.prepare` builds an entry.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import finder_coverage  # noqa: E402
import finder_round  # noqa: E402
import finder_retry  # noqa: E402
from test_finder_retry_retry import (DIFF, HALF_A, ONE_HUNK_DIFF, PARENT,  # noqa: E402
                                     _entry, _manifest, _parent_entry, _read, _retry, _seg)

# --- unsplittable: the Sonnet transition, shared with settle ----------------

def test_unsplittable_segment_takes_the_sonnet_transition(tmp_path, capsys):
    seg = _seg(files=["one.py"], sid="s1")
    _manifest(tmp_path, [_parent_entry(tmp_path, seg=seg)])
    assert _retry(tmp_path, diff=ONE_HUNK_DIFF)["next"] == "sonnet"
    after = _entry(tmp_path, PARENT)
    assert after["rung"] == "sonnet-xhigh" and after["attempt"] == 2
    assert "skipped" not in after
    assert len(_read(tmp_path)["angles"]) == 1  # nothing was split
    capsys.readouterr()
    assert finder_retry.main(["retry", "--round-dir", str(tmp_path), "--angle", PARENT,
                              "--repo", str(tmp_path)]) == 2  # no third attempt


def test_retry_of_a_sonnet_rung_or_marked_entry_exits_2(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path, rung="sonnet-xhigh")])
    assert _retry(tmp_path)["exit"] == 2
    _manifest(tmp_path, [_parent_entry(tmp_path, unparseable=finder_retry.UNCOVERED_MARK)])
    assert _retry(tmp_path)["exit"] == 2
    _manifest(tmp_path, [_parent_entry(tmp_path, attempt=2)])
    assert _retry(tmp_path)["exit"] == 2


def test_second_retry_of_the_parent_exits_2(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    assert _retry(tmp_path)["next"] == "retry"
    assert _retry(tmp_path)["exit"] == 2


def test_retry_refuses_the_opus_check_and_an_unknown_angle(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path, name="x")])
    assert finder_retry.retry(tmp_path, "opus-check", diff_text=DIFF)["exit"] == 2
    assert finder_retry.retry(tmp_path, "nope-s9", diff_text=DIFF)["exit"] == 2


# --- the budget is checked first --------------------------------------------

def test_budget_exhausted_answers_uncovered_and_marks(tmp_path):
    spent = _parent_entry(tmp_path, name="correctness-s1", attempt=3,
                          seg=_seg(sid="s1", max_segments=2))
    parent = _parent_entry(tmp_path)
    parent["segment"]["max_segments"] = 2
    _manifest(tmp_path, [spent, parent])
    assert finder_retry.retry_used(_read(tmp_path), "correctness") == 2
    out = _retry(tmp_path)
    assert out["next"] == "uncovered"
    after = _entry(tmp_path, PARENT)
    assert after["unparseable"] == finder_retry.UNCOVERED_MARK
    assert after["telemetry"]["outcome"] == "capped"
    assert "skipped" not in after
    assert len(_read(tmp_path)["angles"]) == 2  # no halves were written
    assert finder_round.parse_required(_read(tmp_path)) == [spent]


def test_budget_allows_one_sonnet_rerun_when_two_halves_would_not_fit(tmp_path):
    spent = _parent_entry(tmp_path, name="correctness-s1", attempt=3,
                          seg=_seg(sid="s1", max_segments=3))
    parent = _parent_entry(tmp_path, seg=_seg(sid="s2", files=["one.py"]))
    parent["segment"]["max_segments"] = 3
    _manifest(tmp_path, [spent, parent])
    assert finder_retry.retry_used(_read(tmp_path), "correctness") == 2
    assert _retry(tmp_path, diff=ONE_HUNK_DIFF)["next"] == "sonnet"
    assert _entry(tmp_path, PARENT)["rung"] == "sonnet-xhigh"


# --- the whole chain, with no hand-set field --------------------------------

def test_full_chain_half_caps_twice_and_lands_uncovered(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    assert _retry(tmp_path)["next"] == "retry"
    half = PARENT + "a"
    (tmp_path / half).mkdir(exist_ok=True)
    out = finder_retry.settle(tmp_path, half, capped=True)
    assert out["outcome"] == "capped" and out["next"] == "sonnet"
    after = _entry(tmp_path, half)
    assert after["rung"] == "sonnet-xhigh" and after["attempt"] == 3
    out = finder_retry.settle(tmp_path, half, capped=True)
    assert out["outcome"] == "capped" and out["next"] == "uncovered"
    after = _entry(tmp_path, half)
    assert after["unparseable"] == finder_retry.UNCOVERED_MARK
    man = _read(tmp_path)
    outcomes = {e["name"]: finder_coverage.entry_outcome(e) for e in man["angles"]}
    unc = set(finder_coverage.uncovered(man, outcomes))
    assert set(HALF_A) <= unc  # half a capped twice: its files are uncovered
    assert not (set(HALF_A) & {p for e in man["angles"]
                               if finder_coverage.entry_outcome(e) == "delivered"
                               for p in e["segment"]["files"]})
    assert finder_retry.retry_used(man, "correctness") == 3
    assert finder_round.parse_required(man) == [_entry(tmp_path, PARENT + "b")]


# --- the CLI reads the diff from the repo -----------------------------------

def test_cli_retry_splits_from_the_repo_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for i, name in enumerate(("one.py", "two.py", "three.py")):
        (repo / name).write_text("x = 1\n", encoding="utf-8")

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True).stdout.strip()
    for name in ("one.py", "two.py", "three.py"):
        (repo / name).write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "head")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True).stdout.strip()
    seg = _seg(files=["one.py", "two.py", "three.py"])
    entry = _parent_entry(tmp_path, seg=seg)
    _manifest(tmp_path, [entry], base=base, head=head)
    assert finder_retry.main(["retry", "--round-dir", str(tmp_path), "--angle", PARENT,
                              "--repo", str(repo)]) == 0
    man = _read(tmp_path)
    assert [e["name"] for e in man["angles"]] == [PARENT, PARENT + "a", PARENT + "b"]


# --- only a capped entry is retried ------------------------------------------

def _write_reply(round_dir, text):
    (round_dir / PARENT / "reply.md").write_text(text, encoding="utf-8")


def test_retry_of_a_delivered_entry_exits_2_and_changes_nothing(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    _write_reply(tmp_path, json.dumps(
        {"findings": [{"file": "a.py", "line": 3, "summary": "real finding"}]}))
    before = _read(tmp_path)
    assert _retry(tmp_path)["exit"] == 2
    assert _read(tmp_path) == before


def test_retry_of_a_settled_delivered_or_partial_entry_exits_2(tmp_path):
    for outcome in ("delivered", "partial", "unparseable"):
        _manifest(tmp_path, [_parent_entry(tmp_path, telemetry={"outcome": outcome})])
        assert _retry(tmp_path)["exit"] == 2, outcome


def test_retry_takes_a_settled_capped_or_placeholder_only_entry(tmp_path):
    _manifest(tmp_path, [_parent_entry(tmp_path, telemetry={"outcome": "capped"})])
    assert _retry(tmp_path)["next"] == "retry"
    _manifest(tmp_path, [_parent_entry(tmp_path)])
    _write_reply(tmp_path, json.dumps({"findings": [{"capped": True, "text": ""}]}))
    assert _retry(tmp_path)["next"] == "retry"
