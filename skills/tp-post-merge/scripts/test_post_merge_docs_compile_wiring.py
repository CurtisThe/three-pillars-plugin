"""test_post_merge_docs_compile_wiring.py — Task 1.14: post-merge step 6.2 runs the compile publish.

design: living-doc-fragments, Task 1.14. Oracle: example. Structure only (skills/_shared/test-fragility.md):
the SKILL.md command is read through ``skill_invocations`` (code spans, never prose), filled and run on a
fixture repo that has no ``origin``; the test pins the exit code, a ``docs-compile:`` line and the local
branch, never wording.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))

pytest.importorskip("skill_spans")  # dev-only modules: a plugin copy skips this file
from skill_invocations import invocations  # noqa: E402
from test_docs_compile import ROADMAP, frag, git, make_repo  # noqa: E402
from test_docs_compile_close import ARCHIVE, BODY, DESIGN, ROADMAP2  # noqa: E402

SKILL = ROOT / "skills" / "tp-post-merge" / "SKILL.md"


def _calls(fill):
    return invocations(SKILL, "docs_compile_publish.py", fill=fill, root=ROOT)


def test_step_6_2_invocation_runs_on_a_fixture(tmp_path):
    repo = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", BODY)},
                     docs={ROADMAP: ROADMAP2, DESIGN: "# alpha\n"})
    calls = [c for c in _calls({"base": "main", "name": "alpha", "number": "7"}) if c[2] == "run"]
    assert calls, "post-merge SKILL.md has no docs_compile_publish.py run command"
    with_pr = [c for c in calls if "--pr" in c]
    assert with_pr and with_pr[0][with_pr[0].index("--pr") + 1] == "alpha=7"
    argv = [sys.executable, *with_pr[0][1:], "--repo-root", str(repo)]
    out = subprocess.run(argv, capture_output=True, text=True, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert [ln for ln in out.stdout.splitlines() if ln.startswith("docs-compile:")]
    row = [ln for ln in git(repo, "show", f"tp/docs-compile:{ARCHIVE}").splitlines() if ln.startswith("| alpha ")]
    assert row and "PR #7" in row[0]
    assert git(repo, "rev-list", "--count", "main..tp/docs-compile") == "1"
