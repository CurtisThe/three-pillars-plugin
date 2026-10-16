"""test_audit_plan_oracle_wiring.py — Behavior 4 through ``audit_plan.py``'s exit code.

design: fragile-test-prevention (detailed-design-stages Part C2)

``audit_plan.py <dir>`` runs as a subprocess over temp design dirs built from
structured task dicts (never a real plan file). On a ``plan-schema: 2`` plan a
missing Oracle, Entry point or Targets, a line pin and a hash pin each exit 1; a
wording pin is a WARN and exits 0; a clean task exits 0; spike mode ignores all
of them; the same gaps without the marker are NOTEs and exit 0 (the NOTE lines
for the new fields go to stderr, so a legacy plan's stdout report is unchanged).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import audit_plan as ap  # noqa: E402

CLEAN = {
    "File": "`src/widget.py` (new)",
    "Test": "`src/test_widget.py` test_render",
    "Targets": "`src/test_widget.py::test_render` (new)",
    "Oracle": "example",
    "Entry point": "`src/widget.py::render`",
    "Red": "Assert render(widget) returns markup.",
    "Green": "Implement render.",
    "Done when": "render returns markup for a widget.",
}
SPIKE_TASK = {"Hypothesis": "It renders.", "Try": "Render it.", "Evaluate": "Look."}
DESIGN = "# Fixture\n\n## Scope\n### In scope\n- The widget\n"


def plan_text(task: dict, *, marker: bool, spike: bool = False) -> str:
    """One-task plan.md from a structured field dict; ``marker`` adds the schema key."""
    head = "---\nweight-class: light\n" + ("plan-schema: 2\n" if marker else "") + "---\n"
    body = "\n".join(f"**{k}**: {v}" for k, v in task.items())
    deliverable = "\n**Deliverable**: notes\n" if spike else ""
    return f"{head}# Plan\n\n## Phase 1: Build (~80k)\n\n### Task 1.1: Build widget\n{body}\n{deliverable}"


def run_audit(tmp_path: Path, task: dict, *, marker: bool, flag: str = "--light"):
    """Run ``audit_plan.py`` over a temp design dir → ``(returncode, stdout, stderr)``."""
    d = tmp_path / "design"
    d.mkdir()
    (d / "design.md").write_text("---\nweight-class: light\n---\n" + DESIGN)
    (d / "plan.md").write_text(plan_text(task, marker=marker, spike=flag == "--spike"))
    proc = subprocess.run([sys.executable, str(SCRIPTS / "audit_plan.py"), str(d), flag],
                          capture_output=True, text=True, cwd=tmp_path)
    return proc.returncode, proc.stdout, proc.stderr


def without(field: str) -> dict:
    return {k: v for k, v in CLEAN.items() if k != field}


def test_extract_tasks_returns_oracle_and_entry_point():
    tasks = ap.extract_tasks(plan_text(CLEAN, marker=True), fields=ap.STANDARD_FIELDS)
    assert tasks[0]["fields"]["Oracle"] == "example"
    assert tasks[0]["fields"]["Entry point"] == "`src/widget.py::render`"


def test_new_fields_are_optional_to_the_generic_completeness_check():
    t = ap.extract_tasks(plan_text(without("Oracle"), marker=True), fields=ap.STANDARD_FIELDS)
    assert "Oracle" in ap.STANDARD_FIELDS and "Entry point" in ap.STANDARD_FIELDS
    assert ap.check_completeness(t, fields=ap.STANDARD_FIELDS) == []


def test_clean_marked_task_exits_zero(tmp_path):
    rc, out, _ = run_audit(tmp_path, CLEAN, marker=True)
    assert rc == 0, out
    assert "ERROR" not in out


@pytest.mark.parametrize("missing, needle", [
    ("Oracle", "no **Oracle** field"),
    ("Entry point", "no **Entry point** field"),
    ("Targets", "no **Targets** field"),
])
def test_marked_missing_field_exits_one(tmp_path, missing, needle):
    rc, out, _ = run_audit(tmp_path, without(missing), marker=True)
    assert rc == 1, out
    assert "--- ERROR" in out and needle in out


@pytest.mark.parametrize("pin, kind", [
    ("`src/widget.py:42`", "line"),
    ("`" + "a1b2c3d4" * 4 + "`", "hash"),
])
def test_marked_line_and_hash_pins_exit_one(tmp_path, pin, kind):
    task = dict(CLEAN, **{"Done when": f"the output equals {pin}."})
    rc, out, _ = run_audit(tmp_path, task, marker=True)
    assert rc == 1, out
    assert f"criteria pin a {kind}" in out


def test_marked_wording_pin_is_a_warn_and_exits_zero(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\nKeep a Changelog\n")
    task = dict(CLEAN, **{"Done when": "`grep -q \"Keep a Changelog\" CHANGELOG.md` passes."})
    rc, out, _ = run_audit(tmp_path, task, marker=True)
    assert rc == 0, out
    assert "--- WARN (1) ---" in out and "criteria pin wording" in out
    assert "ERROR" not in out


def test_spike_mode_ignores_all_of_them(tmp_path):
    rc, out, err = run_audit(tmp_path, SPIKE_TASK, marker=True, flag="--spike")
    assert rc == 0, out
    assert "Oracle" not in out + err and "Entry point" not in out + err


@pytest.mark.parametrize("missing, needle", [
    ("Oracle", "no **Oracle** field"),
    ("Entry point", "no **Entry point** field"),
    ("Targets", "no **Targets** field"),
])
def test_unmarked_gaps_are_notes_and_exit_zero(tmp_path, missing, needle):
    rc, out, err = run_audit(tmp_path, without(missing), marker=False)
    assert rc == 0, out
    assert "NOTE" in out + err and needle in out + err
    assert "ERROR" not in out + err


def test_unmarked_pins_are_notes_and_exit_zero(tmp_path):
    task = dict(CLEAN, **{"Done when": "the output equals `src/widget.py:42`."})
    rc, out, err = run_audit(tmp_path, task, marker=False)
    assert rc == 0, out
    assert "NOTE" in out + err and "criteria pin a line" in out + err


def test_unmarked_oracle_notes_leave_stdout_unchanged(tmp_path):
    rc, out, err = run_audit(tmp_path, without("Oracle"), marker=False)
    assert rc == 0
    assert "Oracle" not in out
    assert "no **Oracle** field" in err
