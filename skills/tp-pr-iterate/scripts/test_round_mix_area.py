"""Tests for round_mix's area side — a fragile class concentrated in one area.

design: review-convergence (Task 2.2, detailed-design-pr-loop §B)

The second signal a round can carry is "one fragile class in one area": more than
half the round's blockers share a `finding_fields.FRAGILE_CLASSES` value AND
`area_of` finds a strict-majority file or parent dir among their files. Two such
rounds give the round-cap stop a `mix` naming that area; blockers split across
dirs give none, because there is no area to rewrite. `area_of` is the shared
majority rule, so it is pinned directly here.
Oracle: example — exact values over a fixture rounds dir (test-fragility).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import round_mix  # noqa: E402

STOP = {"source": "pr-iterate", "signal": "round-cap",
        "target": "https://github.com/o/r/pull/1", "head": "abc", "detail": {}}


def _cd(file="pkg/x/a.py", **over) -> dict:
    """A blocking `change-detector` finding in `file`."""
    f = {"source": "code-review", "file": file, "line_range": [1, 1],
         "summary": "d", "verdict": "structural", "blocking": True,
         "fragility_class": "change-detector"}
    f.update(over)
    return f


def _round(rounds_dir, name: str, findings) -> Path:
    d = Path(rounds_dir) / name / "tail"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    return Path(rounds_dir) / name


def _rounds(tmp_path, r1, r2):
    root = tmp_path / "rounds"
    _round(root, "r1", r1)
    _round(root, "r2", r2)
    return root


# --- area_of: strict-majority file, else strict-majority parent dir ---------

@pytest.mark.parametrize("paths,expected", [
    (["pkg/x/a.py", "pkg/x/a.py", "pkg/x/b.py"], "pkg/x/a.py"),
    (["pkg/x/a.py", "pkg/x/b.py", "pkg/x/c.py"], "pkg/x"),
    (["pkg/x/a.py", "pkg/x/a.py"], "pkg/x/a.py"),
    (["pkg/x/a.py", "pkg/x/b.py"], "pkg/x"),  # dir majority over a file tie
    (["a.py", "a.py", "b.py"], "a.py"),
    (["a.py", "b.py"], "."),                       # one parent dir, named "."
    ([], None),
    ([None, "", 7], None),                         # non-string paths ignored
    (["pkg/x/a.py", "pkg/x/b.py", "other/c.py"], "pkg/x"),
    (["pkg/x/a.py", "pkg/y/b.py", "pkg/y/c.py"], "pkg/y"),
])
def test_area_of_finds_a_strict_majority(paths, expected):
    assert round_mix.area_of(paths) == expected


def test_area_of_parent_of_a_bare_name_is_dot():
    assert round_mix.area_of(["a.py", "a.py", "b.py"]) == "a.py"
    assert round_mix.area_of(["a.py", "b.py", "c.py"]) == "."
    assert round_mix.area_of(["a.py", "b.py"]) == "."


# --- class-in-area majority in both rounds → mix with that area -------------

def test_class_majority_in_one_dir_both_rounds_gives_that_area(tmp_path):
    root = _rounds(tmp_path,
                   [_cd("pkg/x/a.py"), _cd("pkg/x/b.py"), _cd("pkg/x/b.py")],
                   [_cd("pkg/x/c.py"), _cd("pkg/x/a.py")])
    mix = round_mix.mix(root)
    assert mix == {"signal": "structural-rewrite", "area": "pkg/x",
                   "reason": "r1: class:change-detector@pkg/x/b.py; "
                             "r2: class:change-detector@pkg/x"}
    out = round_mix.attach(STOP, root)
    assert out["mix"] == mix


def test_round_signal_reports_the_class_and_area(tmp_path):
    signal = round_mix.round_signal([_cd("pkg/x/a.py"), _cd("pkg/x/a.py"),
                                     _cd("pkg/x/b.py")])
    assert signal == {"kind": "class:change-detector@pkg/x/a.py"}


def test_class_majority_but_files_split_across_dirs_gives_no_mix(tmp_path):
    root = _rounds(tmp_path,
                   [_cd("pkg/x/a.py"), _cd("pkg/y/b.py"), _cd("pkg/z/c.py")],
                   [_cd("pkg/x/d.py"), _cd("pkg/y/e.py")])
    assert round_mix.round_signal([_cd("pkg/x/a.py"), _cd("pkg/y/b.py"),
                                   _cd("pkg/z/c.py")]) is None
    assert round_mix.mix(root) is None
    assert "mix" not in round_mix.attach(STOP, root)


def test_class_majority_without_a_shared_area_gives_no_signal(tmp_path):
    # 3 of 4 blockers share the class, but no file/dir holds a strict majority.
    findings = [_cd("pkg/x/a.py"), _cd("pkg/y/b.py"), _cd("pkg/z/c.py"),
                _cd("pkg/w/d.py")]
    assert round_mix.round_signal(findings) is None


def test_class_below_majority_in_a_round_gives_no_signal(tmp_path):
    findings = [_cd("pkg/x/a.py"), _cd("pkg/x/b.py"),
                {"source": "code-review", "file": "pkg/x/c.py", "line_range": [1, 1],
                 "summary": "d", "verdict": "structural", "blocking": True,
                 "fragility_class": "none"},
                {"source": "code-review", "file": "pkg/x/d.py", "line_range": [1, 1],
                 "summary": "d", "verdict": "structural", "blocking": True}]
    assert round_mix.round_signal(findings) is None


def test_non_fragile_class_never_signals(tmp_path):
    for cls in ("none", "unclassified"):
        findings = [_cd("pkg/x/a.py", fragility_class=cls),
                    _cd("pkg/x/b.py", fragility_class=cls)]
        assert round_mix.round_signal(findings) is None


def test_each_fragile_class_can_signal(tmp_path):
    for cls in ("open-ended", "change-detector", "blocklist"):
        findings = [_cd("pkg/x/a.py", fragility_class=cls),
                    _cd("pkg/x/b.py", fragility_class=cls)]
        assert round_mix.round_signal(findings) == {
            "kind": f"class:{cls}@pkg/x"}


def test_regression_majority_wins_over_a_class_majority(tmp_path):
    findings = [_cd("pkg/x/a.py", origin="regression"),
                _cd("pkg/x/b.py", origin="regression"),
                _cd("pkg/x/c.py", origin="original")]
    assert round_mix.round_signal(findings) == {"kind": "regression"}


def test_area_of_all_blockers_names_a_majority_file_across_rounds(tmp_path):
    root = _rounds(tmp_path,
                   [_cd("pkg/x/a.py"), _cd("pkg/x/a.py"), _cd("pkg/x/b.py")],
                   [_cd("pkg/x/a.py"), _cd("pkg/x/b.py")])
    mix = round_mix.mix(root)
    assert mix["area"] == "pkg/x/a.py"
    assert mix["reason"] == ("r1: class:change-detector@pkg/x/a.py; "
                             "r2: class:change-detector@pkg/x")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
