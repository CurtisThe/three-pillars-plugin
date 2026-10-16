"""test_refactor_invariance_cli.py — the `refactor_invariance` CLI (design:
fragile-test-prevention, plan.md Task 7.3).

Oracle: ``example``. Each case builds a real tmp git repo and a plan.md built from
task dicts (never parsed prose), then runs `refactor_invariance.main` as the phase's
review step would: the CLI derives the phase's Targets from the plan
(`task_scope.phase_tasks` + `parse_targets`) and the changed files from
`git diff --name-only <base>..HEAD`, and maps the `run` verdict to its exit code.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import refactor_invariance as rv
import task_scope  # the shipped env scrub; git_env is dev-only

IDENTITY = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"}

DOC_LINES = [
    "# Guide",
    "",
    "## Intro",
    "",
    "This opening paragraph is written across several deliberately short lines,",
    "so that re-wrapping it at another width moves every line break and",
    "changes which text sits on each line.",
    "",
]
DOC = "\n".join(DOC_LINES) + "\n"
DOC2 = DOC + "\n"  # a trivial edit: trailing blank line, still eligible for md-reflow

_READ_DOC = ("from pathlib import Path\n\n"
             "TEXT = (Path(__file__).parent / 'docs' / 'guide.md').read_text(encoding='utf-8')\n\n")
WRAP_SRC = _READ_DOC + ("def test_wrapping():\n"
                        f"    assert TEXT.splitlines()[5] == {DOC_LINES[5]!r}\n")
BEHAVIOUR_SRC = _READ_DOC + (
    "def test_intro_heading():\n"
    "    heads = [ln.lstrip('# ') for ln in TEXT.splitlines() if ln.startswith('#')]\n"
    "    assert 'Intro' in heads\n")
FILES = {
    "docs/guide.md": DOC, "pytest.ini": "", "test_wrap.py": WRAP_SRC,
    "test_behaviour.py": BEHAVIOUR_SRC,
}
WRAP, BEHAVIOUR = "test_wrap.py::test_wrapping", "test_behaviour.py::test_intro_heading"


def _git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=task_scope._git_env(**IDENTITY))
    return done.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    """A tmp repo on `main`, one base commit, one edit commit to the doc: `(repo, base)`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for rel, text in FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "docs" / "guide.md").write_text(DOC2, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "edit the doc")
    return repo, base


def _plan(tmp_path: Path, target: str) -> Path:
    """A plan.md outside the repo (M23: the repo's HEAD is only ever the commits under
    test), one phase-1 task whose Targets is `target`."""
    text = "\n".join([
        "# Plan", "", "## Phase 1: demo", "",
        "### Task 1.1: demo task", "**File**: `docs/guide.md` (modify)",
        "**Test**: demo", f"**Targets**: `{target}`", "**Status**: Pending", "",
    ])
    plan = tmp_path / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(text, encoding="utf-8")
    return plan


def run(repo: Path, plan: Path, *extra: str) -> tuple[int, str]:
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = rv.main(["--root", str(repo), "--plan", str(plan), "--phase", "1", *extra])
    return code, buf.getvalue()


def test_behavioural_target_with_explicit_base_is_clean(tmp_path):
    repo, base = _repo(tmp_path)
    plan = _plan(tmp_path, BEHAVIOUR)
    code, out = run(repo, plan, "--base", base, "--json")
    assert code == 0
    assert json.loads(out)["verdict"] == "clean"


def test_wrapping_pin_target_with_explicit_base_is_over_specified(tmp_path):
    repo, base = _repo(tmp_path)
    plan = _plan(tmp_path, WRAP)
    code, out = run(repo, plan, "--base", base, "--json")
    assert code == 1
    payload = json.loads(out)
    assert payload["verdict"] == "over-specified"
    assert payload["over_specified"] == [{"node": WRAP, "transform": "md-reflow"}]


def test_a_bad_base_is_could_not_evaluate(tmp_path):
    repo, _base = _repo(tmp_path)
    plan = _plan(tmp_path, BEHAVIOUR)
    code, _out = run(repo, plan, "--base", "no-such-ref")
    assert code == 2


def test_no_runner_is_could_not_evaluate(tmp_path):
    repo, base = _repo(tmp_path)
    (repo / "pytest.ini").unlink()
    _git(repo, "commit", "-q", "-am", "drop the pytest config")
    plan = _plan(tmp_path, BEHAVIOUR)
    code, out = run(repo, plan, "--base", base, "--json")
    assert code == 2
    assert json.loads(out)["verdict"] == "could-not-evaluate"


def test_omitted_base_falls_back_to_the_default_branch(tmp_path):
    repo, _base = _repo(tmp_path)  # HEAD is `main` with the doc edit already committed
    _git(repo, "checkout", "-q", "-b", "work")
    (repo / "docs" / "guide.md").write_text(DOC2 + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "more edits on work")
    plan = _plan(tmp_path, BEHAVIOUR)
    code, out = run(repo, plan, "--json")
    assert code == 0
    assert json.loads(out)["verdict"] == "clean"


def test_cli_leaves_head_and_worktrees_untouched(tmp_path):
    repo, base = _repo(tmp_path)
    plan = _plan(tmp_path, BEHAVIOUR)
    head = _git(repo, "rev-parse", "HEAD")
    run(repo, plan, "--base", base)
    assert _git(repo, "rev-parse", "HEAD") == head
    listing = _git(repo, "worktree", "list", "--porcelain").splitlines()
    assert len([line for line in listing if line.startswith("worktree ")]) == 1
