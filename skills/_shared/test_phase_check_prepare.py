"""test_phase_check_prepare.py — the deterministic half of a phase check (task 8.3).

design: review-convergence (Phase 8, `SH/phase_check.py`)

Oracle: ``example`` — a real tmp repo (``attempt_fixture``) whose commits are built by
hand, so the range ``base..head`` is a fact of the fixture rather than a mock. Every
case is one contract line from the design companion: the hits are limited to the range,
a closed carry entry skips once per phase, an open entry resumes with byte-identical
prompts, a Targets file touched after its red commit is a targets hit (never under
``local`` or ``jdi``), and only the finder prompt ends with ``BUDGET_LINE``.

The invariance check is ALWAYS a stub — a real run makes a scratch worktree and a
pytest subprocess, which is task 8.4's business, not this test's.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import agent_caps
import phase_check
import trust_boundary
from attempt_fixture import commit, git

_HERE = Path(__file__).resolve().parent
_ANGLES_SCRIPTS = _HERE.parents[1] / "skills" / "tp-pr-iterate" / "scripts"
if str(_ANGLES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ANGLES_SCRIPTS))

import angles  # noqa: E402 — the one REVIEW_BAR source, imported as the template test does

DD = "three-pillars-docs/tp-designs/demo"
PLAN = f"{DD}/plan.md"
CARRY_PATH = f"{DD}/{phase_check.CARRY}"

PLAN_TEXT = """# Demo plan

## Phase 1: demo phase

The demo phase must keep the behaviour of `impl/a.py`.

### Task 1.1: demo task
**File**: `impl/a.py`
**Test**: Behaviour 1.
**Targets**: `tests/test_x.py`
**Red**: `tests/test_x.py` fails.
**Green**: `impl/a.py` makes it pass.
"""

SURFACE = "import subprocess\nsubprocess.run(['ls'])\n"


def _stub_invariance(repo, plan_path, phase, base, head) -> dict:
    """The seam's stand-in: no scratch worktree, no pytest subprocess."""
    return {"verdict": "clean", "stub": True, "phase": phase}


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n", PLAN: PLAN_TEXT}, "base")
    return repo


def _reset(repo: Path) -> None:
    """Drop the carry entry so the next ``prepare`` runs again (not ``resume``).

    The carry makes a phase check once-per-phase, so a second ``prepare`` in the same
    fixture would read back the first run's prompts instead of re-running the checks.
    """
    (repo / DD / phase_check.CARRY).unlink(missing_ok=True)


def _prepare(repo: Path, base: str, head: str, **kw) -> dict:
    kw.setdefault("invariance", _stub_invariance)
    return phase_check.prepare(repo / DD, 1, base=base, head=head, repo=repo, **kw)


def _scratch(reply: dict) -> Path:
    return Path(reply["scratch"])


def _read(scratch: Path, name: str) -> str:
    return (scratch / name).read_text(encoding="utf-8")


def _det(scratch: Path) -> dict:
    return json.loads(_read(scratch, "deterministic.json"))


def _carry(repo: Path) -> dict:
    return json.loads(_read(repo / DD, phase_check.CARRY))


def test_scratch_dir_lives_in_the_git_dir_not_the_work_tree(tmp_path):
    repo = _repo(tmp_path)
    assert phase_check.scratch_dir(repo, "demo", 1) == (
        repo / ".git" / "three-pillars" / "phase-check" / "demo" / "1")


def test_hits_cover_only_the_base_to_head_range(tmp_path):
    repo = _repo(tmp_path)
    commit(repo, {"impl/before.py": SURFACE}, "surface committed before base")
    base = commit(repo, {"impl/at_base.py": SURFACE}, "surface AT base (excluded)")
    head = commit(repo, {"impl/after.py": SURFACE}, "surface after base")
    res = _prepare(repo, base, head)
    det = _det(_scratch(res))
    assert {s["path"] for s in det["surfaces"]} == {"impl/after.py"}
    assert isinstance(det["lint"], list)


def test_closed_phase_skips_once_whatever_head_is_passed(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    commit(repo, {CARRY_PATH: json.dumps({"phases": {"1": {"status": "closed"}}})},
           "carry closed")
    assert _prepare(repo, base, head) == {"status": "skip", "reason": "already-checked"}


def test_an_open_entry_resumes_with_byte_identical_prompts(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/after.py": SURFACE}, "surface after base")
    first = _prepare(repo, base, head)
    assert first["status"] == "ready"
    assert first["finder"]["cheap_class"] == "review_finder"
    assert first["checker"]["agent"] == "tp-phase-checker"
    scratch = _scratch(first)
    entry = _carry(repo)["phases"]["1"]
    assert entry["status"] == "open" and entry["head"] == head
    assert entry["base"] == base

    second = _prepare(repo, base, "HEAD")
    assert second["status"] == "resume"
    assert Path(second["scratch"]) == scratch
    assert second["finder"]["prompt"] == _read(scratch, "finder.prompt.md")
    assert second["checker"]["prompt"] == _read(scratch, "checker.prompt.md")
    assert first["finder"]["prompt"] == _read(scratch, "finder.prompt.md")


def test_targets_touched_after_the_red_commit_is_a_targets_hit(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, {"tests/test_x.py": "def test_x():\n    assert True\n"},
           "Red: demo 1.1 — x")
    head = commit(repo, {"impl/a.py": "A = 1\n",
                         "tests/test_x.py": "def test_x():\n    assert True  # after red\n"},
                  "Implement: demo 1.1 — x")
    det = _det(_scratch(_prepare(repo, base, head)))
    assert [f["task_id"] for f in det["targets"]] == ["1.1"]
    assert "tests/test_x.py" in det["targets"][0]["reason"]
    for kw in ({"local": True}, {"jdi": True}):
        _reset(repo)
        other = _det(_scratch(_prepare(repo, base, head, **kw)))
        assert other["targets"] == [], kw


def test_only_the_finder_prompt_ends_with_the_budget_line(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/after.py": SURFACE}, "surface after base")
    res = _prepare(repo, base, head)
    finder = _read(_scratch(res), "finder.prompt.md")
    checker = _read(_scratch(res), "checker.prompt.md")
    assert finder.strip().splitlines()[-1] == agent_caps.BUDGET_LINE
    assert agent_caps.BUDGET_LINE not in checker
    assert angles.REVIEW_BAR in finder and angles.REVIEW_BAR in checker
    assert "demo phase must keep the behaviour" in finder
    assert "demo phase must keep the behaviour" in checker
    assert f"{_scratch(res)}/finder.reply.json" in checker


def test_the_security_lens_appears_only_with_surfaces(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    quiet = commit(repo, {"impl/quiet.py": "A = 1\n"}, "no surface")
    checker = _read(_scratch(_prepare(repo, base, quiet)), "checker.prompt.md")
    assert trust_boundary.SECURITY_BAR not in checker
    loud = commit(repo, {"impl/loud.py": SURFACE}, "a surface")
    _reset(repo)
    checker = _read(_scratch(_prepare(repo, base, loud)), "checker.prompt.md")
    assert trust_boundary.SECURITY_BAR in checker


def test_a_missing_plan_is_said_so_in_the_prompts(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/after.py": SURFACE}, "surface after base")
    res = _prepare(repo, base, head, plan_path=repo / "nope" / "plan.md")
    finder = _read(_scratch(res), "finder.prompt.md")
    assert "no plan" in finder.lower()


def test_put_accepts_only_a_slot_and_a_strict_json_reply(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(ValueError):
        phase_check.put(scratch, "bogus", "{}")
    with pytest.raises(ValueError):
        phase_check.put(scratch, "finder", "here is what I found")
    out = phase_check.put(scratch, "checker", '{"findings": []}')
    assert out == scratch / "checker.reply.json"
    assert json.loads(out.read_text(encoding="utf-8")) == {"findings": []}
