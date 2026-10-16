"""Tests for round_mix — the regression/area mix riding the round-cap stop.

design: review-convergence (Task 2.2, detailed-design-pr-loop §B)

Behavior 5: two consecutive rounds whose blockers are a regression majority make
the round-cap budget terminal say *why* the loop is stuck, so the finalizer is
told to rewrite one area instead of taking another patch. `attach` adds `mix`
only to a `pr-iterate` / `round-cap` stop; one round, a below-`MIN_BLOCKERS`
round, or any other stop leaves the stop untouched. The CLI is the topology's
pipe: `attach --stop-file F --rounds-dir D` prints the (possibly extended) stop.
Oracle: example — exact values over a fixture rounds dir (test-fragility).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import round_mix  # noqa: E402

STOP = {"source": "pr-iterate", "signal": "round-cap",
        "target": "https://github.com/o/r/pull/1", "head": "abc", "detail": {}}


def _finding(file="pkg/x/a.py", **over) -> dict:
    """A blocking finding (severity.is_blocking shape) plus any extra keys."""
    f = {"source": "code-review", "file": file, "line_range": [1, 1],
         "summary": "d", "verdict": "structural", "blocking": True}
    f.update(over)
    return f


def _regression(file="pkg/x/a.py") -> dict:
    return _finding(file=file, origin="regression")


def _round(rounds_dir, name: str, findings) -> Path:
    """Write `<rounds_dir>/<name>/tail/findings.json`."""
    d = Path(rounds_dir) / name / "tail"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    return Path(rounds_dir) / name


def _rounds(tmp_path, r1, r2=None):
    root = tmp_path / "rounds"
    _round(root, "r1", r1)
    if r2 is not None:
        _round(root, "r2", r2)
    return root


# --- two regression-majority rounds → the round-cap stop gains mix ------------

def test_two_regression_rounds_add_mix_to_a_round_cap_stop(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression("pkg/x/b.py")],
                   [_regression("pkg/x/c.py"), _regression()])
    out = round_mix.attach(STOP, root)
    assert out["mix"] == {"signal": "structural-rewrite", "area": "pkg/x",
                          "reason": "r1: regression; r2: regression"}


def test_mix_is_the_only_key_added_and_the_input_is_never_mutated(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    before = json.dumps(STOP, sort_keys=True)
    out = round_mix.attach(STOP, root)
    assert json.dumps(STOP, sort_keys=True) == before
    assert set(out) == set(STOP) | {"mix"}
    assert out["target"] == STOP["target"] and out["head"] == "abc"


def test_mix_reason_names_each_round_and_its_signal(tmp_path):
    root = _rounds(tmp_path, [_regression("pkg/x/a.py"), _regression("pkg/x/b.py")],
                   [_regression("pkg/y/a.py"), _regression("pkg/y/b.py")])
    mix = round_mix.mix(root)
    assert mix["reason"] == "r1: regression; r2: regression"
    assert mix["signal"] == "structural-rewrite"
    assert mix["area"] == "."  # no strict-majority file or dir over both rounds


def test_mix_is_none_when_either_round_has_no_signal(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_finding(origin="original"), _finding(origin="original")])
    assert round_mix.mix(root) is None


# --- one round, a thin round, or a missing dir → no mix ----------------------

def test_one_round_gives_no_mix(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()])
    assert round_mix.mix(root) is None
    assert "mix" not in round_mix.attach(STOP, root)


def test_missing_rounds_dir_gives_no_mix(tmp_path):
    assert round_mix.mix(tmp_path / "absent") is None
    assert "mix" not in round_mix.attach(STOP, tmp_path / "absent")


def test_round_below_min_blockers_has_no_signal(tmp_path):
    assert round_mix.MIN_BLOCKERS == 2
    root = _rounds(tmp_path, [_regression()], [_regression(), _regression()])
    assert round_mix.round_signal([_regression()]) is None
    assert round_mix.mix(root) is None
    assert "mix" not in round_mix.attach(STOP, root)


def test_non_blocking_findings_are_not_blockers(tmp_path):
    thin = [{"source": "code-review", "file": "pkg/x/a.py", "line_range": [1, 1],
             "summary": "d", "verdict": "minor", "blocking": False,
             "origin": "regression"}] * 3
    root = _rounds(tmp_path, thin + [_regression()], thin + [_regression()])
    assert round_mix.mix(root) is None


def test_unreadable_round_is_skipped(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    (root / "r2" / "tail" / "findings.json").write_text("{not json", encoding="utf-8")
    assert round_mix.mix(root) is None


def test_last_two_rounds_are_the_ones_that_signal(tmp_path):
    root = _rounds(tmp_path, [_finding(origin="original")],
                   [_regression(), _regression()])
    _round(root, "r3", [_regression("pkg/x/z.py"), _regression("pkg/x/z.py")])
    mix = round_mix.mix(root)
    assert mix["reason"] == "r2: regression; r3: regression"
    assert mix["area"] == "pkg/x"


def test_rerun_dir_supersedes_its_parent_round(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_finding(origin="original"), _finding(origin="original")])
    _round(root, "r2.1", [_regression(), _regression()])
    mix = round_mix.mix(root)
    assert mix["reason"] == "r1: regression; r2.1: regression"


# --- only a pr-iterate round-cap stop is ever extended ----------------------

@pytest.mark.parametrize("over", [
    {"signal": "wall-clock"},
    {"signal": "growth-lines"},
    {"source": "halt"},
    {"source": "finalizer", "signal": "round-cap"},
])
def test_other_stops_are_returned_unchanged(tmp_path, over):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    stop = {**STOP, **over}
    assert round_mix.attach(stop, root) == stop


def test_attach_tolerates_a_stop_without_source_or_signal(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    assert round_mix.attach({"target": "t"}, root) == {"target": "t"}


# --- the CLI the topology pipes the stop through ----------------------------

def _run_cli(tmp_path, stop_path, rounds_dir, *extra):
    return subprocess.run(
        [sys.executable, str(Path(__file__).parent / "round_mix.py"), "attach",
         "--stop-file", str(stop_path), "--rounds-dir", str(rounds_dir), *extra],
        capture_output=True, text=True)


def test_cli_prints_the_extended_stop_as_json(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    stop_path = tmp_path / "stop.json"
    stop_path.write_text(json.dumps(STOP), encoding="utf-8")
    proc = _run_cli(tmp_path, stop_path, root)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {**STOP, "mix": {
        "signal": "structural-rewrite", "area": "pkg/x/a.py",
        "reason": "r1: regression; r2: regression"}}


def test_cli_prints_the_stop_unchanged_when_there_is_no_mix(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()])
    stop_path = tmp_path / "stop.json"
    stop_path.write_text(json.dumps(STOP), encoding="utf-8")
    proc = _run_cli(tmp_path, stop_path, root)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == STOP


def test_cli_unreadable_stop_file_exits_2(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    proc = _run_cli(tmp_path, tmp_path / "absent.json", root)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert len(proc.stderr.strip().splitlines()) == 1


def test_cli_non_object_stop_json_exits_2(tmp_path):
    root = _rounds(tmp_path, [_regression(), _regression()],
                   [_regression(), _regression()])
    stop_path = tmp_path / "stop.json"
    stop_path.write_text("[]", encoding="utf-8")
    proc = _run_cli(tmp_path, stop_path, root)
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_cli_unknown_subcommand_exits_2():
    proc = subprocess.run([sys.executable,
                           str(Path(__file__).parent / "round_mix.py"), "nope"],
                          capture_output=True, text=True)
    assert proc.returncode == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
