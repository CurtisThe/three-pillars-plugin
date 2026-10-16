"""test_targets_frozen_range.py — the non-local range audit of stages §Part C1.

design: fragile-test-prevention (Part C1, phase 4)

Oracle: ``example``. Each case builds a real tmp repo through ``attempt_fixture`` (M23)
and a plan from task dicts (the system builds the input; no prose is parsed), then
asserts the findings ``range_audit`` returns and the exit codes ``main`` gives. Only the
tasks that break the invariant are reported; the reasons are ``check_pair``'s.
"""
from __future__ import annotations

import json
from pathlib import Path

import targets_frozen
from attempt_fixture import commit, git, make_seat

BODY = "def test_a():\n    assert 1\n"


def task(tid: str, phase: int = 1) -> dict:
    """A plan task dict: its own Targets file and implementation file."""
    n = tid.replace(".", "_")
    return {"id": tid, "phase": phase, "title": f"demo task {tid}",
            "impl": f"skills/impl/m{n}.py", "target": f"skills/_shared/test_m{n}.py"}


def write_plan(tmp_path: Path, tasks: list[dict], design: str = "demo") -> Path:
    """A plan.md under ``<design>/`` (the design name is the plan's directory) built from
    task dicts, outside the repo so the repo's HEAD is only ever the commits under test."""
    lines = ["# Plan", ""]
    current = None
    for t in tasks:
        if t["phase"] != current:
            current = t["phase"]
            lines += [f"## Phase {current}: demo", ""]
        lines += [f"### Task {t['id']}: {t['title']}", f"**File**: `{t['impl']}` (new)",
                  "**Test**: demo", f"**Targets**: `{t['target']}` (new)",
                  "**Status**: Pending", ""]
    plan = tmp_path / "plans" / design / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("\n".join(lines), encoding="utf-8")
    return plan


def red(wt: Path, t: dict) -> str:
    return commit(wt, {t["target"]: BODY}, f"Red: demo {t['id']} — {t['title']}")


def green(wt: Path, t: dict, extra: dict | None = None) -> str:
    files = {t["impl"]: "A = 1\n", **(extra or {})}
    return commit(wt, files, f"Implement: demo {t['id']} — {t['title']}")


def audit(wt: Path, plan: Path, base: str, phase: int = 1) -> list[tuple[str, str]]:
    found = targets_frozen.range_audit(wt, base, "HEAD", plan, phase)
    return [(f["task_id"], f["reason"]) for f in found]


def setup(tmp_path: Path, tasks: list[dict]):
    _seat, wt = make_seat(tmp_path)
    return wt, write_plan(tmp_path, tasks), git(wt, "rev-parse", "HEAD")


def test_only_the_offending_task_of_a_two_task_phase_is_reported(tmp_path):
    t1, t2 = task("1.1"), task("1.2")
    wt, plan, base = setup(tmp_path, [t1, t2])
    red(wt, t1)
    green(wt, t1, {t1["target"]: "def test_a():\n    assert 0\n"})  # edits its Targets
    red(wt, t2)
    green(wt, t2)
    assert audit(wt, plan, base) == [("1.1", f"targets edited after red: {t1['target']}")]


def test_single_commit_mixing_targets_and_other_files_is_reported(tmp_path):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    green(wt, t1, {t1["target"]: BODY})
    assert audit(wt, plan, base) == [
        ("1.1", f"targets changed without a red commit: {t1['target']}")]


def test_red_that_touches_an_implementation_file_is_reported(tmp_path):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    commit(wt, {t1["target"]: BODY, t1["impl"]: "A = 1\n"},
           f"Red: demo {t1['id']} — {t1['title']}")
    green(wt, t1, {"skills/impl/other.py": "B = 2\n"})
    assert audit(wt, plan, base) == [
        ("1.1", f"red commit touches non-Targets file: {t1['impl']}")]


def test_test_only_task_with_one_implement_commit_is_not_reported(tmp_path):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    commit(wt, {t1["target"]: BODY}, f"Implement: demo {t1['id']} — {t1['title']}")
    assert audit(wt, plan, base) == []


def test_clean_pairs_interleaved_with_unrelated_commits_are_not_reported(tmp_path):
    t1, t2 = task("1.1"), task("1.2")
    wt, plan, base = setup(tmp_path, [t1, t2])
    red(wt, t1)
    commit(wt, {"README.md": "changed\n"}, "chore: unrelated")
    red(wt, t2)
    green(wt, t1)
    green(wt, t2)
    assert audit(wt, plan, base) == []


def test_pairing_is_by_the_exact_task_id_not_a_prefix_of_it(tmp_path):
    t1, t10 = task("1.1"), task("1.10")
    wt, plan, base = setup(tmp_path, [t1, t10])
    red(wt, t10)
    red(wt, t1)
    green(wt, t1)
    green(wt, t10)
    assert audit(wt, plan, base) == []


def test_only_the_requested_phase_is_audited(tmp_path):
    t1, t2 = task("1.1"), task("2.1", phase=2)
    wt, plan, base = setup(tmp_path, [t1, t2])
    red(wt, t1)
    green(wt, t1)
    green(wt, t2, {t2["target"]: BODY})  # phase 2: one commit that mixes
    assert audit(wt, plan, base, phase=1) == []
    assert audit(wt, plan, base, phase=2) == [
        ("2.1", f"targets changed without a red commit: {t2['target']}")]


def test_a_commit_of_another_design_is_not_this_designs_task(tmp_path):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    commit(wt, {t1["impl"]: "A = 1\n", t1["target"]: BODY},
           f"Implement: other {t1['id']} — {t1['title']}")
    assert audit(wt, plan, base) == []


def run(wt: Path, plan: Path, base: str, *extra: str) -> int:
    return targets_frozen.main(["range", "--root", str(wt), "--plan", str(plan),
                                "--phase", "1", "--base", base, *extra])


def test_cli_exits_zero_on_a_clean_range_and_leaves_head_alone(tmp_path):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    red(wt, t1)
    green(wt, t1)
    head = git(wt, "rev-parse", "HEAD")
    assert run(wt, plan, base) == 0
    assert git(wt, "rev-parse", "HEAD") == head


def test_cli_exits_one_with_findings_and_json_lists_them(tmp_path, capsys):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    green(wt, t1, {t1["target"]: BODY})
    head = git(wt, "rev-parse", "HEAD")
    assert run(wt, plan, base, "--json") == 1
    payload = json.loads(capsys.readouterr().out)
    assert [f["task_id"] for f in payload["findings"]] == ["1.1"]
    assert git(wt, "rev-parse", "HEAD") == head


def test_cli_exits_two_on_a_bad_ref(tmp_path):
    t1 = task("1.1")
    wt, plan, base = setup(tmp_path, [t1])
    head = git(wt, "rev-parse", "HEAD")
    assert run(wt, plan, "no-such-ref") == 2
    assert git(wt, "rev-parse", "HEAD") == head
