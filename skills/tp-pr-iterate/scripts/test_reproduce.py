"""Tests for reproduce.run_reproducers — the per-finding reproducer outcomes.

design: iterate-convergence-budget (Task 5.2)

A blocking finding stays blocking only when its reproducer demonstrates the
defect (pytest exit 1, or a command violating its `expect`). A reproducer that
runs and passes downgrades it to a note. Anything inconclusive (pytest 2/3/4/5,
timeout, OSError) keeps it blocking: the runner never fails open.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402
from reproduce import run_reproducers  # noqa: E402

TEST_SRC = "def test_bug():\n    assert 1 == 2\n"


def _finding(repro=None, **kw):
    f = {"source": "code-review", "file": "src/a.py", "line_range": [3, 4],
         "summary": "defect", "verdict": "structural", "class": "P", "blocking": True}
    if repro is not None:
        f["reproducer"] = repro
    f.update(kw)
    return f


def _test_finding():
    return _finding({"kind": "test", "source": TEST_SRC})


def _cmd_finding(expect):
    return _finding({"kind": "command", "argv": ["tool", "--flag"], "expect": expect})


class _Runner:
    """Records calls; returns a CompletedProcess or raises the given exception."""

    def __init__(self, rc=0, stdout="", stderr="", exc=None):
        self.rc, self.stdout, self.stderr, self.exc = rc, stdout, stderr, exc
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


def _run(findings, runner, tmp_path, **kw):
    return run_reproducers(findings, cwd=tmp_path / "wt", scratch_dir=tmp_path / "scratch",
                           runner=runner, **kw)


def test_outcome_pytest_fail_stays_blocking(tmp_path):
    out, downgrades = _run([_test_finding()], _Runner(rc=1), tmp_path)
    assert out[0]["blocking"] is True and out[0]["verdict"] == "structural"
    assert "downgrade" not in out[0]
    assert downgrades == []


def test_outcome_pytest_pass_downgrades(tmp_path):
    runner = _Runner(rc=0, stdout="1 passed\n" + "x" * 2000)
    out, downgrades = _run([_test_finding()], runner, tmp_path)
    f = out[0]
    assert f["blocking"] is False and f["verdict"] == "minor"
    assert f["downgrade"]["reason"] == "not-reproduced"
    assert len(f["downgrade"]["output"]) <= 500
    assert [d["reason"] for d in downgrades] == ["not-reproduced"]


def test_outcome_pytest_inconclusive_codes_stay_blocking(tmp_path):
    for rc in (2, 3, 4, 5):
        out, downgrades = _run([_test_finding()], _Runner(rc=rc), tmp_path)
        assert out[0]["blocking"] is True and out[0]["verdict"] == "structural", rc
        assert out[0]["downgrade"]["reason"] == "inconclusive", rc
        assert [d["reason"] for d in downgrades] == ["inconclusive"]


def test_outcome_timeout_stays_blocking(tmp_path):
    runner = _Runner(exc=subprocess.TimeoutExpired(["python3"], 1))
    out, _ = _run([_test_finding()], runner, tmp_path, timeout=1)
    assert out[0]["blocking"] is True
    assert out[0]["downgrade"]["reason"] == "inconclusive"
    assert runner.calls[0][1]["timeout"] == 1


def test_outcome_oserror_stays_blocking(tmp_path):
    out, _ = _run([_cmd_finding({"exit": 0})], _Runner(exc=OSError("no such tool")), tmp_path)
    assert out[0]["blocking"] is True
    assert out[0]["downgrade"]["reason"] == "inconclusive"


def test_outcome_command_violating_expect_reproduced(tmp_path):
    out, _ = _run([_cmd_finding({"exit": 0})], _Runner(rc=1), tmp_path)
    assert out[0]["blocking"] is True and "downgrade" not in out[0]
    out, _ = _run([_cmd_finding({"stdout_contains": "ok"})], _Runner(rc=0, stdout="bad"),
                  tmp_path)
    assert out[0]["blocking"] is True and "downgrade" not in out[0]


def test_outcome_command_matching_expect_downgraded(tmp_path):
    runner = _Runner(rc=0, stdout="all ok\n")
    out, _ = _run([_cmd_finding({"exit": 0, "stdout_contains": "ok"})], runner, tmp_path)
    assert out[0]["blocking"] is False and out[0]["verdict"] == "minor"
    assert out[0]["downgrade"]["reason"] == "not-reproduced"
    argv, kw = runner.calls[0]
    assert argv == ["tool", "--flag"]
    assert kw.get("shell") in (None, False)
    assert Path(kw["cwd"]) == tmp_path / "wt"


def test_outcome_stdout_contains_checks_full_stdout(tmp_path):
    runner = _Runner(rc=0, stdout="ok\n" + "y" * 2000, stderr="noise")
    out, _ = _run([_cmd_finding({"stdout_contains": "ok"})], runner, tmp_path)
    assert out[0]["downgrade"]["reason"] == "not-reproduced"


def test_outcome_legacy_downgraded_in_round_dir_mode_only(tmp_path):
    legacy = {"source": "code-review", "file": "src/a.py", "line_range": [1, 1],
              "summary": "old shape", "verdict": "structural"}
    runner = _Runner(rc=1)
    out, downgrades = _run([dict(legacy)], runner, tmp_path)
    assert out[0]["verdict"] == "minor" and out[0]["blocking"] is False
    assert out[0]["schema_note"] == "legacy-no-reproducer"
    assert [d["reason"] for d in downgrades] == ["legacy-no-reproducer"]
    out, downgrades = _run([dict(legacy)], runner, tmp_path, round_dir_mode=False)
    assert out[0] == legacy and downgrades == []
    assert runner.calls == []


def test_outcome_sentinels_untouched(tmp_path):
    sentinels = [{"source": "no-angles", "file": "<review-output:no-angles>",
                  "verdict": "structural"},
                 {"source": "angle-1", "file": "<review-output:angle-1>",
                  "verdict": "structural"}]
    runner = _Runner(rc=0)
    out, downgrades = _run([dict(s) for s in sentinels], runner, tmp_path)
    assert out == sentinels and downgrades == [] and runner.calls == []


def test_outcome_minor_findings_not_run(tmp_path):
    note = _finding({"kind": "test", "source": TEST_SRC}, verdict="minor", blocking=False)
    runner = _Runner(rc=0)
    out, downgrades = _run([dict(note)], runner, tmp_path)
    assert out == [note] and downgrades == [] and runner.calls == []


def test_outcome_test_reproducer_written_to_scratch_and_run_from_the_tree(tmp_path):
    """The audit copy lands in `scratch_dir`; pytest runs a transient copy inside the
    reviewed tree (`SCRATCH_PARTS`) that exists during the run and is gone after."""
    seen = {}

    class _Recorder(_Runner):
        def __call__(self, argv, **kw):
            seen["exists"] = Path(argv[-1]).is_file()
            seen["text"] = Path(argv[-1]).read_text(encoding="utf-8")
            return super().__call__(argv, **kw)

    runner = _Recorder(rc=1)
    findings = [_finding(verdict="minor", blocking=False), _test_finding()]
    (tmp_path / "wt").mkdir()
    _run(findings, runner, tmp_path)
    assert (tmp_path / "scratch" / "repro_1.py").read_text(encoding="utf-8") == TEST_SRC
    argv, kw = runner.calls[0]
    assert argv[:-1] == [reproduce.PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    script = Path(argv[-1])
    assert script.name == "repro_1.py"
    assert script.parent.parent == (tmp_path / "wt").resolve().joinpath(*reproduce.SCRATCH_PARTS)
    assert seen == {"exists": True, "text": TEST_SRC}
    assert Path(kw["cwd"]) == tmp_path / "wt"
    assert not (tmp_path / "wt" / ".three-pillars").exists()


def test_outcome_input_not_mutated(tmp_path):
    f = _test_finding()
    snapshot = dict(f)
    _run([f], _Runner(rc=0), tmp_path)
    assert f == snapshot


def test_outcome_output_cap_constant():
    assert reproduce.OUTPUT_CAP == 500
