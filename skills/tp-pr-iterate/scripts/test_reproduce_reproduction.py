"""reproduce records `reproduction`, and `severity.finalize` runs last in the CLI.

design: review-convergence (Phase 1, D1) — `PI/test_reproduce_reproduction.py`

Two halves:

1. `run_reproducers` writes the reproducer's outcome onto the finding as
   `reproduction` — `reproduced` / `refuted` (today's `not-reproduced`) /
   `inconclusive` — for every structural, non-sentinel finding that has a valid
   reproducer. Findings with no reproducer (a note, a legacy shape, a sentinel)
   carry no `reproduction` key at all, so `severity.is_blocking` cannot read a
   refutation that never happened.
2. Through `reproduce.main`, a scaffold-adopted claim that Opus downgraded
   (`escape.disposition == "downgraded"`) ends non-blocking even though its
   scaffold reproduces: `run_cli` runs `severity.finalize` after the reproducers
   and before `findings.json` / `tally`, so the written file and the tally both
   carry the final severity (#231).
"""

from __future__ import annotations

import json
import subprocess  # noqa: F401 — the injected runners raise/return these
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402
import review_prep_scaffold as rps  # noqa: E402
from finding_class import tally  # noqa: E402
from reproduce import run_reproducers  # noqa: E402
from test_reproduce_adopted import (  # noqa: E402 — fixture reuse, plan §1.3
    SRC,
    _load_schema,
    _round,
    _target_claim,
    _write,
)

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


# --- 1. `reproduction` per outcome -----------------------------------------


def test_reproduction_reproduced(tmp_path):
    out, downgrades = _run([_test_finding()], _Runner(rc=1), tmp_path)
    assert out[0]["reproduction"] == "reproduced"
    assert out[0]["blocking"] is True and out[0]["verdict"] == "structural"
    assert "downgrade" not in out[0] and downgrades == []


def test_reproduction_refuted_is_todays_not_reproduced(tmp_path):
    out, downgrades = _run([_test_finding()], _Runner(rc=0, stdout="1 passed\n"), tmp_path)
    assert out[0]["reproduction"] == "refuted"
    assert out[0]["downgrade"]["reason"] == reproduce.NOT_REPRODUCED
    assert [d["reason"] for d in downgrades] == [reproduce.NOT_REPRODUCED]


def test_reproduction_command_matching_expect_is_refuted(tmp_path):
    out, _ = _run([_cmd_finding({"exit": 0, "stdout_contains": "ok"})],
                  _Runner(rc=0, stdout="all ok\n"), tmp_path)
    assert out[0]["reproduction"] == "refuted"


def test_reproduction_command_violating_expect_is_reproduced(tmp_path):
    out, _ = _run([_cmd_finding({"exit": 0})], _Runner(rc=1), tmp_path)
    assert out[0]["reproduction"] == "reproduced"
    assert "downgrade" not in out[0]


def test_reproduction_inconclusive_codes(tmp_path):
    for rc in (2, 3, 4, 5):
        out, _ = _run([_test_finding()], _Runner(rc=rc), tmp_path)
        assert out[0]["reproduction"] == "inconclusive", rc
        assert out[0]["downgrade"]["reason"] == reproduce.INCONCLUSIVE, rc


def test_reproduction_inconclusive_timeout_and_oserror(tmp_path):
    runner = _Runner(exc=subprocess.TimeoutExpired(["python3"], 1))
    out, _ = _run([_test_finding()], runner, tmp_path, timeout=1)
    assert out[0]["reproduction"] == "inconclusive"
    out, _ = _run([_cmd_finding({"exit": 0})], _Runner(exc=OSError("no such tool")), tmp_path)
    assert out[0]["reproduction"] == "inconclusive"


def test_reproduction_no_key_without_a_valid_reproducer(tmp_path):
    note = _finding({"kind": "test", "source": TEST_SRC}, verdict="minor", blocking=False)
    legacy = {"source": "code-review", "file": "src/a.py", "line_range": [1, 1],
              "summary": "old shape", "verdict": "structural"}
    sentinel = {"source": "no-angles", "file": "<review-output:no-angles>",
                "verdict": "structural"}
    out, _ = _run([dict(note), dict(legacy), dict(sentinel)], _Runner(rc=1), tmp_path)
    assert all("reproduction" not in f for f in out)
    assert out[1]["schema_note"] == reproduce.LEGACY
    assert out[2] == sentinel


def test_reproduction_survives_dedupe_twin_search(tmp_path):
    """The twin that reproduces names the finding's reproduction."""
    f = _finding({"kind": "command", "argv": ["tool"], "expect": {"exit": 0}},
                 alt_reproducers=[{"kind": "command", "argv": ["tool2"],
                                   "expect": {"exit": 0}}])
    out, _ = _run([f], _Runner(rc=0), tmp_path)
    assert out[0]["reproduction"] == "refuted"
    out, _ = _run([f], _Runner(rc=1), tmp_path)
    assert out[0]["reproduction"] == "reproduced"


def test_reproduction_input_not_mutated(tmp_path):
    f = _test_finding()
    snapshot = dict(f)
    _run([f], _Runner(rc=0), tmp_path)
    assert f == snapshot


# --- 2. An adopted red scaffold cannot re-block an Opus-downgraded claim -----


def _downgraded_target_claim():
    """A target claim Opus's check downgraded: still a scaffold target, never blocking."""
    claim = _target_claim()
    claim["escape"] = {"disposition": "downgraded", "reason": "not shipped behaviour"}
    return claim


def test_adopted_scaffold_cannot_reblock_opus_downgraded_claim(tmp_path):
    claim = _downgraded_target_claim()
    repo, head, rd, _log = _round(tmp_path, "r1", [claim])
    key = rps.targets(rd)[0]["key"]
    rps.write_note(rd, key, {"source": SRC, "test_name": "test_adopted"}, head)
    adopted = rd / "tail" / "adopted.json"
    _write(rd, "tail/adopted.json", json.dumps([{"key": key}]))
    assert reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head,
                           "--adopted", str(adopted)]) == 0
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    f = [x for x in findings if x.get("reproducer_origin") == "scaffold-adopted"]
    assert len(f) == 1
    f = f[0]
    assert f["blocking"] is False
    assert f["verdict"] == "minor"
    assert f["severity_note"] == "opus-downgraded"
    assert f["reproduction"] == "reproduced"
    assert f["escape"] == {"disposition": "downgraded",
                           "reason": "not shipped behaviour"}
    assert Draft202012Validator(_load_schema()).is_valid(f)
    assert tally(findings)["blocking"] == 0


def test_run_cli_finalizes_blocking_findings_unchanged(tmp_path):
    """A claim Opus kept and whose scaffold reproduces still blocks after finalize."""
    repo, head, rd, _log = _round(tmp_path, "r1", [_target_claim()])
    key = rps.targets(rd)[0]["key"]
    rps.write_note(rd, key, {"source": SRC, "test_name": "test_adopted"}, head)
    adopted = rd / "tail" / "adopted.json"
    _write(rd, "tail/adopted.json", json.dumps([{"key": key}]))
    summary = reproduce.run_cli(rd, repo, head, adopted=adopted)
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    f = [x for x in findings if x.get("reproducer_origin") == "scaffold-adopted"][0]
    assert f["blocking"] is True and f["verdict"] == "structural"
    assert f["reproduction"] == "reproduced"
    assert "severity_note" not in f
    assert summary["blocking"] == 1
    assert summary["tally"]["blocking"] == 1
    assert summary["tally"]["reproduced"] == 1
