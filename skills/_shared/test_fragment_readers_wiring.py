"""test_fragment_readers_wiring.py -- Task 1.15: design-complete and the readers in fragment mode.

design: living-doc-fragments, Task 1.15. Oracle: example. Structure only (skills/_shared/test-fragility.md):
each markdown file is read through ``skill_invocations`` (its code spans, never its prose); the command is
filled and run on a fixture repo, and ``skill_refs.check`` covers the five files. No test pins wording.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

pytest.importorskip("skill_spans")  # dev-only modules: a plugin copy skips this file
skill_refs = pytest.importorskip("skill_refs")
from skill_invocations import invocations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "skills" / "_shared"
COMPLETE = ROOT / "skills" / ("tp-design" + "-complete") / "SKILL.md"
TIER6 = ROOT / "skills" / "tp-run-full-design" / "tier-6-pr.md"
READ_DOCS = SHARED / ("read-proj" + "ect-docs" + ".md")
RESTORE = ROOT / "skills" / ("tp-sessio" + "n-restore") / "SKILL.md"
FINAL_DOC_STATE = SHARED / "final-doc-state.md"
FILL = {"design-name": "demo", "slug": "demo", "name": "demo", "base": "main", "n": "7"}
KI = "three-pillars-docs/known_issues.md"
FRAGMENT = "three-pillars-docs/changes/demo.md"
FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n{extra}---\n"


def _calls(md: Path, script: str, sub: str | None = None) -> list[list[str]]:
    """Every ``python3 …/<script> [sub] …`` command of ``md``, placeholders filled."""
    found = invocations(md, script, fill=FILL, root=ROOT)
    return [c for c in found if sub is None or c[2:3] == [sub]]


def _run(call: list[str], cwd: Path):
    argv = [sys.executable, str(SHARED / call[1].rsplit("/", 1)[-1]), *call[2:]]
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)


def _commit(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", f"edit {rel}")


def _branch_repo(tmp_path: Path) -> Path:
    """A repo on ``tp/demo`` cut from ``main``, with ``origin/main`` as a remote-tracking ref."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user" + ".email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _commit(root, KI, "base\n")
    _git(root, "update-ref", "refs/remotes/origin/main", "main")
    _git(root, "checkout", "-q", "-b", "tp/demo")
    return root


def _only(calls: list[list[str]]) -> list[str]:
    assert len(calls) == 1, calls
    assert not any("{" in token for token in calls[0]), calls[0]
    return calls[0]


def test_complete_guard_invocation_refuses_fixture(tmp_path):
    call = _only(_calls(COMPLETE, "living_doc_guard.py", "check"))
    assert call[call.index("--base") + 1] == "origin/main", call
    refused = _branch_repo(tmp_path)
    _commit(refused, KI, "edited on the design branch\n")
    assert _run(call, refused).returncode == 1
    clean = _branch_repo(tmp_path / "clean")
    _commit(clean, FRAGMENT, FM.format(extra=""))
    assert _run(call, clean).returncode == 0


def test_complete_self_check_passes_the_base(tmp_path):
    checks = [c for c in _calls(COMPLETE, "final_doc_state.py", "check") if "--json" in c]
    call = _only(checks)
    assert call[call.index("--base") + 1] == "origin/main", call
    root = _branch_repo(tmp_path)
    _commit(root, FRAGMENT, FM.format(extra=""))
    done = _run(call, root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["verdict"] == "pending-compile"
    _commit(root, KI, "edited on the design branch\n")
    assert _run(call, root).returncode == 1


def test_complete_step3_validate_invocation(tmp_path):
    learned = [c for c in _calls(COMPLETE, "changes_fragment.py", "validate") if "--require-learned" in c]
    call = _only(learned)
    assert call[-1] == FRAGMENT, call
    fragment = tmp_path / FRAGMENT
    assert _run(call, tmp_path).returncode == 1  # no fragment: learn did not run
    fragment.parent.mkdir(parents=True)
    fragment.write_text(FM.format(extra=""), encoding="utf-8")  # registration only: no `learned:` stamp
    assert _run(call, tmp_path).returncode == 1
    fragment.write_text(FM.format(extra="learned: 2026-10-22\n"), encoding="utf-8")  # frontmatter-only
    done = _run(call, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_read_project_docs_summary_invocation_runs(tmp_path):
    call = _only(_calls(READ_DOCS, "pending_changes.py", "summary"))
    fragment = tmp_path / FRAGMENT
    fragment.parent.mkdir(parents=True)
    fragment.write_text(FM.format(extra=""), encoding="utf-8")
    done = _run(call, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[0].startswith("demo")  # the merged slug reads as done (B5)


@pytest.mark.parametrize("md", [COMPLETE, TIER6], ids=["complete", "tier6"])
def test_pr_writeback_invocation_is_a_noop_in_fragment_mode(md, tmp_path):
    call = _only([c for c in _calls(md, "reconcile_docs.py") if "--pre-merge" in c])
    fragment = tmp_path / FRAGMENT
    fragment.parent.mkdir(parents=True)
    fragment.write_text(FM.format(extra=""), encoding="utf-8")
    done = _run(call, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout) == {"mode": "fragment", "edits": []}


def test_restore_and_final_doc_state_md_refs_resolve(tmp_path):
    assert _only(_calls(RESTORE, "pending_changes.py", "summary"))
    based = [c for c in _calls(FINAL_DOC_STATE, "final_doc_state.py", "check") if "--base" in c]
    call = _only(based)
    assert call[call.index("--base") + 1] == "origin/main", call
    report = skill_refs.check(ROOT, [COMPLETE, TIER6, READ_DOCS, RESTORE, FINAL_DOC_STATE], cache_dir=tmp_path)
    assert report.issues == [], report.issues
