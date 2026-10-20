"""Hermetic tests for jdi_plan.py — the mechanical one-task plan.md.

A fixture mini design (just-do-it, `## Scope`, `## Behaviors`, `## Done when`)
renders a plan.md that survives the real plan checks (`plan_couplings`, the
**Targets** grammar, `weight_class.check_consistency`) and the jdi-mechanical
pass record; `write` is idempotent and never overwrites a resumed plan.md.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))
import jdi_plan  # noqa: E402
import task_targets  # noqa: E402
import weight_class  # noqa: E402

_ROOT = _SHARED.parent.parent
_AUDIT = _ROOT / "skills" / "tp-plan-audit" / "scripts"

BEHAVIOUR_TEXT = "The helper prints one line and exits 0."
DONE_TEXT = "The targets pass."

DESIGN_TWO = (
    "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
    "# fixture — design\n\n"
    "## Scope\n\n"
    "- `skills/foo/bar.py`\n"
    "- `skills/foo/test_bar.py`\n\n"
    "### Out of scope\n\n- nothing\n\n"
    "## Behaviors\n\n" + BEHAVIOUR_TEXT + "\n\n"
    "## Done when\n\n" + DONE_TEXT + "\n"
)

DESIGN_NO_TEST = (
    "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
    "# fixture — design\n\n"
    "## Scope\n\n- `skills/foo/bar.py`\n\n"
    "## Behaviors\n\n" + BEHAVIOUR_TEXT + "\n\n"
    "## Done when\n\n" + DONE_TEXT + "\n"
)

DESIGN_FALSE_TEST = (
    "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
    "# fixture — design\n\n"
    "## Scope\n\n"
    "- `skills/_shared/attest_helpers.py`\n"
    "- `skills/_shared/test_attest_helpers.py`\n\n"
    "## Behaviors\n\n" + BEHAVIOUR_TEXT + "\n\n"
    "## Done when\n\n" + DONE_TEXT + "\n"
)

DESIGN_TEST_IN_NAME_ONLY = (
    "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
    "# fixture — design\n\n"
    "## Scope\n\n- `skills/foo/latest_report.py`\n\n"
    "## Behaviors\n\n" + BEHAVIOUR_TEXT + "\n\n"
    "## Done when\n\n" + DONE_TEXT + "\n"
)

DESIGN_NO_SCOPE = (
    "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
    "# fixture — design\n\n"
    "## Behaviors\n\n" + BEHAVIOUR_TEXT + "\n\n"
    "## Done when\n\n" + DONE_TEXT + "\n"
)

_TARGETS_RE = re.compile(r"^\*\*Targets\*\*:\s*(.*)$", re.M)
_FILE_RE = re.compile(r"^\*\*File\*\*:\s*(.*)$", re.M)


def _design(tmp_path, body=DESIGN_TWO) -> Path:
    d = tmp_path / "design"
    d.mkdir(exist_ok=True)
    (d / "design.md").write_text(body, encoding="utf-8")
    return d


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A tmp git repo (GIT_* stripped — the `rig` pattern) with nothing in it."""
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "init", "-q"],
                   cwd=str(r), check=True, capture_output=True)
    return r


def _cli(*argv, cwd=None):
    return subprocess.run([sys.executable, str(_SHARED / "jdi_plan.py"), *argv],
                          capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None)


def _audit_cli(script, *argv, cwd):
    return subprocess.run([sys.executable, str(_AUDIT / script), *argv],
                          capture_output=True, text=True, cwd=str(cwd))


# --- (a) the rendered plan.md -------------------------------------------------------

def test_write_renders_one_task_plan(tmp_path, repo):
    d = _design(tmp_path)
    r = _cli("write", "--design-dir", str(d), "--repo", str(repo))
    assert r.returncode == 0, r.stderr
    text = (d / "plan.md").read_text(encoding="utf-8")
    front = text.split("---")[1]
    assert "weight-class: just-do-it" in front
    assert "plan-schema: 2" in front
    assert text.count("## Phase 1") == 1
    assert text.count("### Task 1.1") == 1
    assert len(re.findall(r"^### Task ", text, re.M)) == 1
    field = _FILE_RE.search(text).group(1)
    assert "`skills/foo/bar.py`" in field
    assert "`skills/foo/test_bar.py`" in field
    assert _TARGETS_RE.search(text).group(1).strip() == "`skills/foo/test_bar.py`"
    task = text.split("### Task 1.1", 1)[1]
    for label in ("**Test**:", "**Red**:"):
        assert BEHAVIOUR_TEXT in task.split(label, 1)[1].split("**", 1)[0]
    assert DONE_TEXT in task.split("**Green**:", 1)[1]


def test_render_marks_existing_paths_modify(tmp_path, repo):
    d = _design(tmp_path)
    bar = repo / "skills" / "foo" / "bar.py"
    bar.parent.mkdir(parents=True)
    bar.write_text("print()\n", encoding="utf-8")
    text = jdi_plan.render(str(d), str(repo))
    field = _FILE_RE.search(text).group(1)
    assert "`skills/foo/bar.py` (modify)" in field
    assert "`skills/foo/test_bar.py` (new)" in field


# --- (b) the rendered plan passes the real plan checks ------------------------------

def test_plan_passes_plan_checks_and_pass_record(tmp_path, repo):
    d = _design(tmp_path)
    assert _cli("write", "--design-dir", str(d), "--repo", str(repo)).returncode == 0
    text = (d / "plan.md").read_text(encoding="utf-8")

    pc = _audit_cli("plan_couplings.py", str(d), "--root", str(repo), cwd=repo)
    assert pc.returncode == 0, pc.stderr
    assert pc.stdout.strip() == '{"findings": []}'

    assert task_targets.validate(_TARGETS_RE.search(text).group(1)) == []
    assert weight_class.check_consistency(d) == []

    w = _audit_cli("audit_artifact.py", "--write", str(d), "--mode",
                   "jdi-mechanical", cwd=repo)
    assert w.returncode == 0, w.stderr
    c = _audit_cli("audit_artifact.py", "--check", str(d), cwd=repo)
    assert c.returncode == 0, c.stdout + c.stderr


# --- (b2) the Entry point field the schema-2 audit asks for -------------------------

def test_plan_carries_one_entry_point_field_and_audit_is_quiet(tmp_path, repo):
    d = _design(tmp_path, DESIGN_NO_TEST)
    assert _cli("write", "--design-dir", str(d), "--repo", str(repo)).returncode == 0
    text = (d / "plan.md").read_text(encoding="utf-8")
    task = text.split("### Task 1.1", 1)[1]
    fields = [ln for ln in task.splitlines() if ln.startswith("**Entry point**:")]
    assert len(fields) == 1
    a = _audit_cli("audit_plan.py", str(d), "--light", cwd=_ROOT)
    said = [ln for ln in (a.stdout + a.stderr).splitlines() if "Entry point" in ln]
    assert said == [], a.stdout + a.stderr


def test_plan_naming_a_test_file_carries_a_real_entry_point_and_audits_clean(tmp_path, repo):
    d = _design(tmp_path)  # DESIGN_TWO: Scope names a test_*.py, so Targets is not none
    assert _cli("write", "--design-dir", str(d), "--repo", str(repo)).returncode == 0
    task = (d / "plan.md").read_text(encoding="utf-8").split("### Task 1.1", 1)[1]
    assert "**Entry point**: none" not in task
    a = _audit_cli("audit_plan.py", str(d), "--light", cwd=_ROOT)
    assert "--- ERROR" not in a.stdout + a.stderr, a.stdout + a.stderr


# --- (c) idempotency ---------------------------------------------------------------

def test_second_write_is_byte_identical(tmp_path, repo):
    d = _design(tmp_path)
    assert _cli("write", "--design-dir", str(d), "--repo", str(repo)).returncode == 0
    first = (d / "plan.md").read_bytes()
    art = d / ".plan-audit-pass.json"
    r = _cli("write", "--design-dir", str(d), "--repo", str(repo))
    assert r.returncode == 0, r.stderr
    assert (d / "plan.md").read_bytes() == first
    if art.is_file():
        c = _audit_cli("audit_artifact.py", "--check", str(d), cwd=repo)
        assert c.returncode == 0, c.stdout + c.stderr


# --- (d) no test file named --------------------------------------------------------

def test_targets_none_when_no_test_file(tmp_path, repo):
    d = _design(tmp_path, DESIGN_NO_TEST)
    assert _cli("write", "--design-dir", str(d), "--repo", str(repo)).returncode == 0
    text = (d / "plan.md").read_text(encoding="utf-8")
    assert _TARGETS_RE.search(text).group(1).strip() == "none"
    assert task_targets.validate("none") == []


# --- (g) only basenames that START with test_ are test targets ---------------------

def test_targets_exclude_basenames_that_merely_contain_test(tmp_path, repo):
    d = _design(tmp_path, DESIGN_FALSE_TEST)
    text = jdi_plan.render(str(d), str(repo))
    assert _TARGETS_RE.search(text).group(1).strip() == (
        "`skills/_shared/test_attest_helpers.py`")
    assert task_targets.validate(_TARGETS_RE.search(text).group(1)) == []


def test_targets_none_when_test_only_appears_mid_basename(tmp_path, repo):
    d = _design(tmp_path, DESIGN_TEST_IN_NAME_ONLY)
    text = jdi_plan.render(str(d), str(repo))
    assert _TARGETS_RE.search(text).group(1).strip() == "none"
    assert task_targets.validate("none") == []


# --- (e) bad input -----------------------------------------------------------------

def test_bad_input_exits_two(tmp_path, repo):
    d = _design(tmp_path, DESIGN_NO_SCOPE)
    r = _cli("write", "--design-dir", str(d), "--repo", str(repo))
    assert r.returncode == 2
    assert r.stdout.startswith("jdi-plan: bad-input")
    assert not (d / "plan.md").exists()

    missing = tmp_path / "nothing"
    r2 = _cli("write", "--design-dir", str(missing), "--repo", str(repo))
    assert r2.returncode == 2
    assert r2.stdout.startswith("jdi-plan: bad-input")
    assert not (missing / "plan.md").exists()


# --- (f) cold resume ---------------------------------------------------------------

def test_resume_never_overwrites(tmp_path, repo):
    d = _design(tmp_path)
    resumed = (
        "---\nweight-class: just-do-it\nplan-schema: 2\n---\n\n"
        "# fixture — Implementation Plan\n\n## Phase 1: x\n\n"
        "### Task 1.1: y\n\n**Targets**: none\n\n**Status**: done\n"
    )
    (d / "plan.md").write_text(resumed, encoding="utf-8")
    r = _cli("write", "--design-dir", str(d), "--repo", str(repo))
    assert r.returncode == 0, r.stderr
    assert (d / "plan.md").read_text(encoding="utf-8") == resumed
    assert r.stdout.startswith("jdi-plan: unchanged")

    light = (
        "---\nweight-class: light\nplan-schema: 2\n---\n\n"
        "# fixture — Implementation Plan\n\n## Phase 1: x\n"
    )
    (d / "plan.md").write_text(light, encoding="utf-8")
    r2 = _cli("write", "--design-dir", str(d), "--repo", str(repo))
    assert r2.returncode == 0, r2.stderr
    assert (d / "plan.md").read_text(encoding="utf-8") == light
    assert r2.stdout.startswith("jdi-plan: unchanged")
