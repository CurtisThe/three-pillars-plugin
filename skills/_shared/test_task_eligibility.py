"""Tests for task_eligibility.py — the per-task tier table for one plan phase.

design: local-implement-and-review (Tasks 3.3, 3.4).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_eligibility as te  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402 — git_env is dev-only

_DEV_ROOT = Path(__file__).resolve().parents[2]
_needs_dev_docs = pytest.mark.skipif(
    not (_DEV_ROOT / "three-pillars-docs").exists(),
    reason="reads the dev repo's three-pillars-docs/ (dev-repo only)")

RED = "Calling `f()` returns 2, not 1."


def _task(tid, title, *, files, targets, red=RED, status=None, refactor=None):
    """A task block; ``targets=None`` omits the **Targets** line (non-canonical)."""
    lines = [f"### Task {tid}: {title}", f"**File**: {files}",
             "**Test**: prose only, never parsed.", f"**Red**: {red}",
             "**Green**: implement it."]
    if targets is not None:
        lines.insert(3, f"**Targets**: {targets}")
    if refactor is not None:
        lines.append(f"**Refactor**: {refactor}")
    lines.append("**Done when**: node passes.")
    if status:
        lines.append(f"**Status**: {status}")
    return "\n".join(lines) + "\n"


def _plan(*tasks, phase=1):
    return f"# P\n\n## Phase {phase}: Things\n\n" + "\n".join(tasks) + "\n## Phase 9: Other\n\n" \
        + _task("9.1", "elsewhere", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`")


EXISTING = {"pkg", "pkg/a.py", "pkg/b.py", "pkg/test_a.py", "tests"}


def _classify(plan, *, runner_ok=True, max_files=3):
    return te.classify_phase(plan, 1, max_files=max_files, runner_ok=runner_ok,
                             exists=EXISTING.__contains__)


def _by_id(rows):
    return {r["task_id"]: r for r in rows}


def test_rule_fixtures():
    plan = _plan(
        _task("1.1", "local", files="`pkg/a.py` (modify)", targets="`pkg/test_a.py::test_x`",
              refactor="rename the helper"),
        _task("1.2", "blocked", files="`pkg/b.py`", targets="`pkg/test_a.py::test_y`",
              status="Blocked (hook failed)"),
        _task("1.3", "no targets", files="`pkg/c.py`", targets=None),
        _task("1.4", "malformed", files="`pkg/d.py`", targets="`test_nowhere.py` test_z"),
        _task("1.5", "declared none", files="`pkg/e.py`", targets="none"),
        _task("1.6", "placeholder red", files="`pkg/f.py`", targets="`pkg/test_f.py::test_f`",
              red="TBD"),  # Red prose is never read: the declared Targets are the oracle
        _task("1.8", "four files", files="`pkg/h1.py`, `pkg/h2.py`, `pkg/h3.py`, `pkg/h4.py`",
              targets="`pkg/test_h.py::test_h`"),
        _task("1.9", "unparsed", files="`pkg/i.py`, `$(generated)/x.py`",
              targets="`pkg/test_i.py::test_i`"),
        _task("1.10", "new at root", files="`pkg/j.py`", targets="`test_root.py` (new)"),
        _task("1.11", "no dir", files="`newpkg/k.py`", targets="`newpkg/test_k.py::test_k`"),
    )
    rows = _by_id(_classify(plan))
    assert list(rows) == ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.8", "1.9",
                          "1.10", "1.11"]  # only phase 1, in plan order
    r = rows["1.1"]
    assert (r["tier"], r["reasons"], r["excluded"]) == ("local", [], False)
    assert r["files"] == ["pkg/a.py"] and r["unparsed_files"] == []
    assert r["test"]["kind"] == "pytest-node" and r["test_paths"] == ["pkg/test_a.py"]
    assert r["new_test"] is False and r["has_refactor"] is True
    assert (rows["1.2"]["tier"], rows["1.2"]["excluded"]) == ("opus", True)
    assert rows["1.2"]["reasons"] == ["excluded:Blocked"]
    # No valid Targets (missing, malformed, or `none`): no oracle, so local (an Opus diff
    # review accepts the attempt).
    for tid, reason in (("1.3", "targets-missing"), ("1.4", "targets-malformed"),
                        ("1.5", "targets-none")):
        assert (rows[tid]["tier"], rows[tid]["reasons"]) == (
            "local", [f"test-not-runnable:{reason}"]), tid
        assert rows[tid]["test_paths"] == []
    assert (rows["1.11"]["tier"], rows["1.11"]["reasons"]) == ("local", ["target-missing"])
    assert (rows["1.6"]["tier"], rows["1.6"]["reasons"]) == ("local", [])
    assert (rows["1.8"]["tier"], rows["1.8"]["reasons"]) == ("local", ["too-many-files"])
    # Unparsed File spans: the Targets still run, so the row stays local (scope is logged).
    assert rows["1.9"]["tier"] == "local" and rows["1.9"]["reasons"] == ["unparsed-file"]
    assert rows["1.9"]["start_rung"] == "local-xhigh"
    # A recorded reason starts local at xhigh; a clean row at medium; no oracle at xhigh.
    assert (rows["1.11"]["start_rung"], rows["1.8"]["start_rung"]) == ("local-xhigh",) * 2
    assert rows["1.6"]["start_rung"] == "local-medium"
    for tid in ("1.3", "1.4", "1.5"):
        assert rows[tid]["start_rung"] == "local-xhigh", tid
    assert rows["1.9"]["unparsed_files"]
    # A declared-new file at the repo root is runnable once created.
    assert (rows["1.10"]["tier"], rows["1.10"]["new_test"]) == ("local", True)
    # A new test file in an existing dir is fine and recorded as new_test.
    assert rows["1.6"]["new_test"] is True and rows["1.1"]["new_test"] is False
    assert rows["1.6"]["has_refactor"] is False
    # max_files is the knob: 4 files are local when the cap is 4.
    assert _by_id(_classify(plan, max_files=4))["1.8"]["tier"] == "local"
    # No runner → every non-excluded row is local (no oracle) with `no-runner` first.
    no_runner = _by_id(_classify(plan, runner_ok=False))
    assert no_runner["1.1"]["tier"] == "local" and no_runner["1.1"]["reasons"] == ["no-runner"]
    assert no_runner["1.1"]["start_rung"] == "local-xhigh"
    assert no_runner["1.3"]["reasons"][0] == "no-runner"
    assert no_runner["1.2"]["reasons"] == ["excluded:Blocked"]


def test_collision_stays_local():
    plan = _plan(
        _task("1.1", "first", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
        _task("1.2", "second", files="`pkg/a.py`, `pkg/b.py`",
              targets="`pkg/test_a.py::test_y`"),
        _task("1.3", "third", files="`pkg/b.py`", targets="`pkg/test_a.py::test_z`"),
        _task("1.4", "done excluded", files="`pkg/a.py`", targets="`pkg/test_a.py::test_w`",
              status="Skipped (pre-exists)"),
    )
    rows = _by_id(_classify(plan))
    assert [rows[t]["tier"] for t in ("1.1", "1.2", "1.3")] == ["local"] * 3
    # 1.1 and 1.3 share no File, but both may write the shared Targets file.
    assert rows["1.1"]["collides_with"] == ["1.2", "1.3"]
    assert rows["1.2"]["collides_with"] == ["1.1", "1.3"]
    assert rows["1.3"]["collides_with"] == ["1.1", "1.2"]
    assert rows["1.1"]["reasons"] == ["collides:1.2,1.3"]
    # An excluded task is never dispatched, so it collides with nothing.
    assert rows["1.4"]["excluded"] is True and rows["1.4"]["collides_with"] == []


def test_a_shared_written_path_collides_whatever_its_field():
    """#165: an attempt may write its Files and its Targets files, so a path one task
    targets and another edits splits a parallel batch; disjoint rows do not collide."""
    plan = _plan(
        _task("1.1", "a", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
        _task("1.2", "b", files="`pkg/b.py`", targets="`pkg/test_b.py::test_y`"),
        _task("1.3", "c", files="`pkg/test_b.py`", targets="`pkg/test_c.py::test_z`"),
    )
    rows = _by_id(_classify(plan))
    assert rows["1.1"]["collides_with"] == []
    assert (rows["1.2"]["collides_with"], rows["1.3"]["collides_with"]) == (["1.3"], ["1.2"])



@pytest.mark.parametrize("a, b, collide", [
    ("`pkg/`", "`pkg/b.py`", True),             # a directory entry covers its children
    ("`pkg/sub/`", "`pkg/`", True),
    ("`./pkg/b.py`", "`pkg/b.py`", True),       # ./ and a/../ spell the same path
    ("`pkg/x/../b.py`", "`pkg/b.py`", True),
    ("`pkg/`", "`pkgx/b.py`", False),           # a prefix is not a parent
    ("`pkg`", "`pkg/b.py`", False),             # no trailing / → the path itself only
])
def test_collisions_compare_normalised_paths(a, b, collide):
    plan = _plan(_task("1.1", "a", files=a, targets="`t/test_a.py::test_x`"),
                 _task("1.2", "b", files=b, targets="`t/test_b.py::test_y`"))
    rows = _by_id(_classify(plan))
    assert (rows["1.1"]["collides_with"], rows["1.2"]["collides_with"]) == (
        (["1.2"], ["1.1"]) if collide else ([], []))
    if b.endswith(".py`"):  # the same answer when the other path is a Targets file
        plan = _plan(_task("1.1", "a", files=a, targets="`t/test_a.py::test_x`"),
                     _task("1.2", "b", files="`c.py`", targets=f"`{b.strip('`')}::test_y`"))
        assert _by_id(_classify(plan))["1.1"]["collides_with"] == (["1.2"] if collide else [])

def test_done_row_never_dispatched():
    """impl-audit-1 #1: a resume must not re-dispatch a finished task."""
    plan = _plan(
        _task("1.1", "finished", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`",
              status="Done ✓"),
        _task("1.2", "open", files="`pkg/a.py`", targets="`pkg/test_a.py::test_y`"),
    )
    rows = _by_id(_classify(plan))
    assert (rows["1.1"]["tier"], rows["1.1"]["excluded"]) == ("opus", True)
    assert rows["1.1"]["reasons"] == ["excluded:Done"]
    assert rows["1.2"]["tier"] == "local" and rows["1.2"]["collides_with"] == []
    # Eligibility-only: task_scope.EXCLUDED (and so the Tier 3.5 re-run) keeps Done out.
    assert "Done" in te.DISPATCH_EXCLUDED and "Done" not in te.task_scope.EXCLUDED


def test_deterministic_json():
    plan = _plan(
        _task("1.1", "a", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
        _task("1.2", "b", files="`pkg/a.py`", targets="`pkg/test_a.py`, `tests/test_b.py`"),
    )
    first = json.dumps(_classify(plan), sort_keys=True)
    for _ in range(3):
        assert json.dumps(_classify(plan), sort_keys=True) == first
    rows = json.loads(first)
    assert len({frozenset(r) for r in rows}) == 1  # one row shape
    assert te.classify_phase("# no phases\n", 1, runner_ok=True, exists=bool) == []


@pytest.mark.parametrize("order", [0, 1])
def test_every_declared_file_must_exist_in_any_order(order):
    """Every declared target file counts, wherever it sits in the field."""
    items = ["`pkg/test_a.py::test_x`", "`nowhere/test_y.py::test_y`"]
    both = ", ".join(items[::-1] if order else items)
    ok = ", ".join(["`pkg/test_a.py::test_x`", "`tests/test_b.py`"][::-1 if order else 1])
    rows = _by_id(_classify(_plan(
        _task("1.1", "both exist", files="`pkg/a.py`", targets=ok),
        _task("1.2", "one missing", files="`pkg/b.py`", targets=both))))
    assert rows["1.1"]["test_paths"] == ["pkg/test_a.py", "tests/test_b.py"]
    assert rows["1.1"]["tier"] == "local"
    assert rows["1.2"]["tier"] == "local" and "target-missing" in rows["1.2"]["reasons"]


# --- Task 3.4: CLI and corpus rows ---------------------------------------------------

SCRIPT = Path(__file__).resolve().parent / "task_eligibility.py"
_REPO = Path(__file__).resolve().parents[2]
_CORPUS = str(_REPO / "three-pillars-docs" / "completed-tp-designs" / "*" / "plan.md")


def _cli_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in ("pkg/a.py", "pkg/test_a.py", "tests/test_bare.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    plan = root / "three-pillars-docs" / "tp-designs" / "d" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan(
        _task("1.1", "local", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
        _task("1.2", "second file", files="`pkg/a.py`", targets="`tests/test_bare.py::test_y`"),
        _task("1.3", "absent", files="`pkg/z.py`", targets="`loose/test_loose.py::test_z`"),
    ), encoding="utf-8")
    return root


def _run_cli(root: Path, *extra: str):
    plan = root / "three-pillars-docs" / "tp-designs" / "d" / "plan.md"
    return subprocess.run([sys.executable, str(SCRIPT), str(plan), "--phase", "1",
                           "--root", str(root), *extra],
                          capture_output=True, text=True, cwd=str(root), env=clean_git_env())


def test_cli_emits_json(tmp_path):
    root = _cli_repo(tmp_path)
    proc = _run_cli(root)
    assert proc.returncode == 0, proc.stderr
    rows = _by_id(json.loads(proc.stdout))
    assert rows["1.1"]["tier"] == "local"
    # The CLI checks declared target files against --root.
    assert (rows["1.2"]["tier"], rows["1.2"]["test_paths"]) == ("local", ["tests/test_bare.py"])
    assert rows["1.3"]["reasons"] == ["target-missing"]
    assert rows["1.1"]["collides_with"] == ["1.2"]
    capped = _by_id(json.loads(_run_cli(root, "--max-files", "0").stdout))
    assert capped["1.1"]["tier"] == "local" and "too-many-files" in capped["1.1"]["reasons"]
    # `runner_ok` is `resolve_runner`: without a pytest config there is no runner.
    (root / "pytest.ini").unlink()
    rows = _by_id(json.loads(_run_cli(root).stdout))
    assert rows["1.1"]["tier"] == "local" and rows["1.1"]["reasons"][0] == "no-runner"
    missing = subprocess.run([sys.executable, str(SCRIPT), str(root / "nope.md"), "--phase", "1",
                              "--root", str(root)], capture_output=True, text=True)
    assert missing.returncode == 2 and "nope.md" in missing.stderr


def test_cli_reads_max_files_from_config(tmp_path):
    """impl-audit-1 #7: without --max-files the CLI uses local_implement.max_files."""
    root = _cli_repo(tmp_path)
    plan = root / "three-pillars-docs" / "tp-designs" / "d" / "plan.md"
    plan.write_text(_plan(_task("1.1", "two files", files="`pkg/a.py`, `pkg/b.py`",
                                targets="`pkg/test_a.py::test_x`")), encoding="utf-8")
    assert _by_id(json.loads(_run_cli(root).stdout))["1.1"]["tier"] == "local"  # default 3
    cfg = root / ".three-pillars" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text('{"local_implement": {"max_files": 1}}', encoding="utf-8")
    assert _by_id(json.loads(_run_cli(root).stdout))["1.1"]["reasons"] == ["too-many-files"]
    assert te.configured_max_files(root) == 1
    assert _by_id(json.loads(_run_cli(root, "--max-files", "2").stdout))["1.1"]["tier"] == "local"
    cfg.write_text('{"local_implement": {"max_files": "x"}}', encoding="utf-8")
    bad = _run_cli(root)
    assert bad.returncode == 2 and "max_files" in bad.stderr


@_needs_dev_docs
def test_corpus_rows_invariants():
    """Archived plans predate the Targets field: every dispatchable row, a non-canonical
    (no-oracle) one included, is local (an Opus diff review accepts the no-oracle ones), and
    only an excluded row is opus."""
    rows = te.corpus_rows(_CORPUS)
    assert len({r["design"] for r in rows}) >= 50 and len(rows) >= 500
    tiers = {r["tier"] for r in rows}
    assert tiers <= {"local", "opus"}
    for r in rows:
        assert (r["tier"] == "opus") == r["excluded"], (r["design"], r["task_id"])
        if r["test"]["kind"] == "not-runnable" and not r["excluded"]:
            assert r["start_rung"] in ("local-xhigh", "local-medium")
    print({t: sum(1 for r in rows if r["tier"] == t) for t in sorted(tiers)})
