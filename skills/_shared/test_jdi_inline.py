"""Hermetic tests for the jdi inline bound, plan estimate and `route --plan`.

A just-do-it design whose plan fits (<= 2 non-paper files, <= 80 lines) routes
`inline`; everything else keeps its existing route. Entry points: `inline_fit`,
`route(..., plan=)` and the `route --plan` CLI.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jdi_eligibility as je  # noqa: E402

SCOPE_CLEAN = "### In scope\n\n- `skills/foo/bar.py` (new)\n"
SCOPE_EXCLUDED = "### In scope\n\n- `skills/_shared/launch_design_run.py` (modify)\n"


def _plan(tmp_path, tasks, name="plan.md"):
    body = "# Plan\n\n## Phase 1: X\n\n"
    for i, (file_field, growth) in enumerate(tasks, 1):
        body += f"### Task 1.{i}: t{i}\n**File**: {file_field}\n"
        if growth is not None:
            body += f"**Growth**: {growth}\n"
        body += "**Test**: x\n\n"
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def _fit(tmp_path, tasks):
    return je.inline_fit(_plan(tmp_path, tasks))


def test_bounds_defined_once():
    assert (je.INLINE_MAX_FILES, je.INLINE_MAX_LINES) == (2, 80)


def test_two_files_sixty_lines_fits(tmp_path):
    assert _fit(tmp_path, [("`a.py`, `b.py`", "+60")])


def test_third_file_does_not_fit(tmp_path):
    assert not _fit(tmp_path, [("`a.py`, `b.py`, `c.py`", "+60")])


def test_growth_120_does_not_fit(tmp_path):
    assert not _fit(tmp_path, [("`a.py`, `b.py`", "+120")])


def test_growth_boundary_80_81(tmp_path):
    assert _fit(tmp_path, [("`a.py`, `b.py`", "+80")])
    assert not _fit(tmp_path, [("`a.py`, `b.py`", "+81")])


def test_paper_path_not_counted(tmp_path):
    f = "`a.py`, `b.py`, `three-pillars-docs/x.md`"
    assert _fit(tmp_path, [(f, "+10")])


def test_file_none_counts_zero_files(tmp_path):
    assert _fit(tmp_path, [("none", "+10")])


def test_missing_growth_counts_fifty(tmp_path):
    assert _fit(tmp_path, [("`a.py`", None)])
    assert not _fit(tmp_path, [("`a.py`", None), ("`b.py`", None)])


def test_negative_growth_uses_abs(tmp_path):
    assert not _fit(tmp_path, [("`a.py`", "-90")])


def test_unparseable_file_never_fits(tmp_path):
    assert not _fit(tmp_path, [("`src/*.py`", "+10")])


def test_no_tasks_never_fits(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("# Plan\n\nnothing\n", encoding="utf-8")
    assert not je.inline_fit(str(p))


def test_missing_plan_never_fits(tmp_path):
    assert not je.inline_fit(str(tmp_path / "nope.md"))


# --- routing ---------------------------------------------------------------


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", cwd=r)
    _git("commit", "-q", "--allow-empty", "-m", "base", cwd=r)
    return r


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def _design(tmp_path, klass="just-do-it", scope=SCOPE_CLEAN):
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    head = f"---\nweight-class: {klass}\nslug: fixture\n---\n\n"
    (d / "design.md").write_text(
        head + "# f\n\n## Scope\n\n" + scope + "\n## Behaviors\n\n1. ok.\n",
        encoding="utf-8")
    (d / "seed.md").write_text(head + "# f seed\n", encoding="utf-8")
    return d


def _route(d, repo, plan=None):
    h = _head(repo)
    return je.route(str(d), h, h, repo=str(repo), plan=plan)


def test_jdi_with_fitting_plan_routes_inline(tmp_path, repo):
    d = _design(tmp_path)
    plan = _plan(tmp_path, [("`a.py`", "+10")])
    assert _route(d, repo, plan) == ("inline", None)


def test_jdi_without_plan_routes_jdi(tmp_path, repo):
    assert _route(_design(tmp_path), repo) == ("just-do-it", None)


def test_light_with_fitting_plan_stays_light(tmp_path, repo):
    d = _design(tmp_path, klass="light")
    plan = _plan(tmp_path, [("`a.py`", "+10")])
    assert _route(d, repo, plan) == ("light", None)


def test_protected_scope_routes_light_even_with_fit(tmp_path, repo):
    d = _design(tmp_path, scope=SCOPE_EXCLUDED)
    plan = _plan(tmp_path, [("`a.py`", "+10")])
    klass, line = _route(d, repo, plan)
    assert klass == "light" and line is not None


def _cli(d, repo, *extra):
    h = _head(repo)
    return subprocess.run(
        [sys.executable, str(Path(je.__file__)), "route", "--design-dir", str(d),
         "--base", h, "--head", h, "--repo", str(repo), *extra],
        capture_output=True, text=True)


def test_cli_plan_prints_inline_and_without_prints_jdi(tmp_path, repo):
    d = _design(tmp_path)
    plan = _plan(tmp_path, [("`a.py`", "+10")])
    assert _cli(d, repo, "--plan", plan).stdout.splitlines()[0] == "route: inline"
    assert _cli(d, repo).stdout.splitlines()[0] == "route: just-do-it"
