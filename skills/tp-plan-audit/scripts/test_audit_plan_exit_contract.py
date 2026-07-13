"""Exit-contract tests for audit_plan.py (returncodes) + pass-artifact wiring.

Split from test_audit_plan.py (which is grandfathered over-cap) so the new
returncode/artifact assertions live in their own file. Fixtures keep design.md
AND plan.md frontmatter SYMMETRIC (both bare) so weight_class_consistency adds
no spurious ERROR that would mask the INCOMPLETE / zero-parse intent.
"""

import sys
import json
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
AUDIT = SCRIPTS / "audit_plan.py"
ARTIFACT = ".plan-audit-pass.json"


def _design(tmp_path, body):
    """A minimal bare-frontmatter design.md so light-mode checks have inputs."""
    (tmp_path / "design.md").write_text(
        "# Design: x\n\n## Scope\n### In scope\n- a thing\n\n"
        "## Behaviors\n- **does** the thing\n\n"
        "## Entities\n- **Thing** — a thing\n"
    )


def _plan(tmp_path, body):
    (tmp_path / "plan.md").write_text(body)


def _run(tmp_path):
    return subprocess.run(
        [sys.executable, str(AUDIT), str(tmp_path), "--light"],
        capture_output=True, text=True,
    )


CLEAN_PLAN = """# Plan: x

## Phase 1: do it (~50k)

### Task 1.1: the task
**File**: `audit_plan.py`
**Test**: a test
**Red**: fails first
**Green**: passes after
**Done when**: it works
"""


def test_incomplete_and_zero_parse_exit_1(tmp_path):
    # (a) INCOMPLETE: a task missing Test/Red/Green.
    _design(tmp_path, "")
    _plan(
        tmp_path,
        "# Plan: x\n\n## Phase 1: do it (~50k)\n\n"
        "### Task 1.1: incomplete\n**File**: modify `audit_plan.py`\n",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "INCOMPLETE" in r.stdout

    # (b) Zero-parse: a plan with no recognized '### Task N.M:' headings.
    _plan(tmp_path, "# Plan: x\n\n## Phase 1: do it (~50k)\n\nNo tasks here.\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no parseable tasks" in r.stdout

    # Docstring pins the implemented mapping: the Exit code line names INCOMPLETE
    # among the exit-1 severities.
    doc = AUDIT.read_text(encoding="utf-8")
    exit_line = next(
        ln for ln in doc.splitlines() if ln.strip().startswith("Exit code:")
    )
    assert "INCOMPLETE" in exit_line
def test_clean_writes_artifact_and_warn_exits_0(tmp_path):
    _design(tmp_path, "")
    _plan(tmp_path, CLEAN_PLAN)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    art = tmp_path / ARTIFACT
    assert art.exists()
    record = json.loads(art.read_text(encoding="utf-8"))
    assert record["verdict"] == "pass"
    sys.path.insert(0, str(SCRIPTS))
    import audit_artifact  # noqa: E402

    d1 = audit_artifact.plan_digest(tmp_path / "plan.md")
    assert record["plan_digest"] == d1

    # WARN-only currency pin: edit plan.md to a WARN state (drop the phase
    # header's (~Nk) annotation) -> still exit 0, but the on-disk artifact digest
    # must STILL be D1 (a WARN-only run must NOT refresh a stale artifact).
    warn_plan = CLEAN_PLAN.replace("## Phase 1: do it (~50k)", "## Phase 1: do it")
    assert warn_plan != CLEAN_PLAN
    _plan(tmp_path, warn_plan)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stdout
    record2 = json.loads(art.read_text(encoding="utf-8"))
    assert record2["plan_digest"] == d1  # untouched, still D1 (now stale vs D2)
    assert audit_artifact.artifact_status(tmp_path)[0] == "stale"


SKILL = (
    SCRIPTS.parent.parent / "tp-phase-implement" / "SKILL.md"
)


def test_skill_documents_artifact_preflight():
    text = SKILL.read_text(encoding="utf-8")
    # (a) invokes audit_artifact.py --check in a preflight step.
    assert "audit_artifact.py --check" in text
    # (b) names /tp-plan-audit as the remedy.
    assert "/tp-plan-audit" in text


ARTIFACT_SCRIPT = SCRIPTS / "audit_artifact.py"


def _check(tmp_path):
    return subprocess.run(
        [sys.executable, str(ARTIFACT_SCRIPT), "--check", str(tmp_path)],
        capture_output=True, text=True,
    )


INCOMPLETE_PLAN = (
    "# Plan: x\n\n## Phase 1: do it (~50k)\n\n"
    "### Task 1.1: incomplete\n**File**: `audit_plan.py`\n"
)


def test_gate_refuses_absent_failing_stale_passes_current(tmp_path):
    _design(tmp_path, "")
    _plan(tmp_path, CLEAN_PLAN)

    # (a) absent — no artifact yet → --check refuses.
    assert _check(tmp_path).returncode != 0

    # (b) current pass — a clean audit writes the artifact → --check passes.
    assert _run(tmp_path).returncode == 0
    assert (tmp_path / ARTIFACT).exists()
    assert _check(tmp_path).returncode == 0

    # (c) stale (clean edit) — mutate plan.md to a still-clean-but-different
    # state → --check refuses (any change forces a re-audit).
    clean2 = CLEAN_PLAN.replace("the task", "the renamed task")
    assert clean2 != CLEAN_PLAN
    _plan(tmp_path, clean2)
    assert _check(tmp_path).returncode != 0

    # (d) failing run writes nothing — FRESH dir, INCOMPLETE plan → rc 1, no
    # artifact, --check refuses (failing collapses to absent in the gate).
    fresh = tmp_path / "fresh_d"
    fresh.mkdir()
    _design(fresh, "")
    _plan(fresh, INCOMPLETE_PLAN)
    r = _run(fresh)
    assert r.returncode == 1, r.stdout + r.stderr
    assert not (fresh / ARTIFACT).exists()
    assert _check(fresh).returncode != 0

    # (e) failing-then-stale — clean pass at D1, then break plan.md to D2
    # (INCOMPLETE), failing re-run neither refreshes nor deletes the prior
    # artifact (still D1), so --check refuses (stale, never falsely ok).
    ft = tmp_path / "ft_d"
    ft.mkdir()
    _design(ft, "")
    _plan(ft, CLEAN_PLAN)
    assert _run(ft).returncode == 0
    d1 = json.loads((ft / ARTIFACT).read_text(encoding="utf-8"))["plan_digest"]
    _plan(ft, INCOMPLETE_PLAN)
    r = _run(ft)
    assert r.returncode == 1, r.stdout + r.stderr
    assert (ft / ARTIFACT).exists()
    assert json.loads((ft / ARTIFACT).read_text(encoding="utf-8"))["plan_digest"] == d1
    assert _check(ft).returncode != 0
