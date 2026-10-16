"""test_plan_coverage.py — module coverage against declared file paths (Task 3.4).

design: consumer-repo-parity (H4, Phase 3)

``audit_plan.check_module_coverage(tasks, modules) -> (issues, notes)`` classifies
each detailed-design module in three steps:

1. **Covered** — a declared path (the canonical File items, or the lenient-parse
   paths of a non-canonical File field, plus the Targets files, all normalised
   with ``task_scope_files.norm_path``) equals the module, or a directory entry
   ending in ``/`` contains it;
2. **NOTE** — no declared match, but the legacy text tier (``mod in tf or tf in
   mod`` over the File field and the raw task backtick paths) matches:
   ``module <m> matched only by text`` (never a failure);
3. **MISSING** — neither matches, exactly as before.

Also pins the rewire to the declared phase list: a standard-mode audit of a
neither-shape Implementation Order is exactly one INCOMPLETE naming both shapes,
and a canonical ``list``-shape order aligns by count.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import audit_plan as ap  # noqa: E402
from design_phases import parse_implementation_order  # noqa: E402
from task_scope_files import parse_files  # noqa: E402


def _task(file=None, targets=None, raw=""):
    fields = {}
    if file is not None:
        fields["File"] = file
    if targets is not None:
        fields["Targets"] = targets
    return {"id": "1.1", "name": "T", "phase": 1, "fields": fields, "raw": raw}


# --- declared-path tier -------------------------------------------------------


def test_covered_by_declared_file_path():
    tasks = [_task(file="`src/widget.py` (modify)")]
    issues, notes = ap.check_module_coverage(tasks, ["src/widget.py"])
    assert issues == []
    assert notes == []


def test_covered_by_declared_file_no_marker():
    tasks = [_task(file="`src/widget.py`")]
    issues, notes = ap.check_module_coverage(tasks, ["src/widget.py"])
    assert issues == []
    assert notes == []


def test_covered_by_targets_file():
    tasks = [_task(file="`src/widget.py` (modify)",
                   targets="`src/legacy.py::test_x` (new)")]
    issues, notes = ap.check_module_coverage(tasks, ["src/legacy.py"])
    assert issues == []
    assert notes == []


def test_covered_by_directory_entry():
    tasks = [_task(file="`src/widget.py` (modify)")]
    issues, notes = ap.check_module_coverage(tasks, ["src/"])
    assert issues == []
    assert notes == []


def test_non_canonical_file_field_uses_lenient_paths():
    field = "modify `src/legacy2.py`"
    assert parse_files(field)[0] == ["src/legacy2.py"]  # the lenient parse sees it
    assert not ap.plan_files.parse_file_field(field)["canonical"]
    issues, notes = ap.check_module_coverage([_task(file=field)], ["src/legacy2.py"])
    assert issues == []
    assert notes == []


# --- text tier (NOTE) and MISSING --------------------------------------------


def test_text_only_match_is_a_note_not_a_failure():
    tasks = [_task(file="`src/widget.py` (modify)",
                   raw="Refactor `src/legacy.py` in place.")]
    issues, notes = ap.check_module_coverage(tasks, ["src/legacy.py"])
    assert issues == []
    assert len(notes) == 1
    assert notes[0][2] == "module src/legacy.py matched only by text"


def test_text_only_note_never_blocks():
    # The NOTE tier is advisory: a text-only match still lets the audit pass.
    tasks = [_task(file="`src/widget.py` (modify)",
                   raw="Extend `src/legacy.py` for parity.")]
    issues, _notes = ap.check_module_coverage(tasks, ["src/legacy.py"])
    assert not any(t == "MISSING" for t, _, _ in issues)


def test_neither_declared_nor_text_is_missing():
    tasks = [_task(file="`src/widget.py` (modify)")]
    issues, notes = ap.check_module_coverage(tasks, ["src/other.py"])
    assert len(issues) == 1
    assert issues[0][0] == "MISSING"
    assert "other.py" in issues[0][2]
    assert notes == []


def test_directory_module_miss_is_missing():
    tasks = [_task(file="`pkg/a.py` (new)")]
    issues, _notes = ap.check_module_coverage(tasks, ["src/"])
    assert len(issues) == 1
    assert issues[0][0] == "MISSING"


# --- declared phase list wiring -----------------------------------------------


def test_phase_alignment_consumes_declared_list():
    tasks = [{"id": "1.1", "name": "A", "phase": 1, "fields": {}, "raw": ""}]
    detailed = "## Implementation Order\n\n1. **Build** — the work\n"
    phases = parse_implementation_order(detailed)["phases"]
    assert phases == ["Build"]
    assert ap.check_phase_alignment(tasks, phases) == []


# --- main() end-to-end (standard mode) ----------------------------------------

DESIGN = """\
    # D

    ## Scope
    ### In scope
    - the widget

    ## Entities
    - **Widget**: a thing

    ## Behaviors
    - **Render**: draws
"""

DETAILED_NEITHER = """\
    # Detailed

    ## Module Structure
    - `src/widget.py` (new)

    ## Implementation Order
    Ship everything in one go, no phases declared.
"""

DETAILED_LIST = """\
    # Detailed

    ## Module Structure
    - `src/widget.py` (new)

    ## Interfaces

    ### `render(widget)` (new)
    Draws.

    ## Implementation Order

    1. **Build** — build the widget
"""

PLAN_ONE_PHASE = """\
    # P

    ## Phase 1: Build (~80k)

    ### Task 1.1: Build
    **File**: `src/widget.py` (new)
    **Test**: prose
    **Red**: assert render(widget) works
    **Green**: implement render
    **Done when**: renders
"""


def _run(tmp_path, files, flags=()):
    d = tmp_path / "d"
    d.mkdir()
    for name, content in files.items():
        (d / name).write_text(textwrap.dedent(content), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_plan.py"), str(d), *flags],
        capture_output=True, text=True)


def test_neither_shape_order_is_one_incomplete(tmp_path):
    r = _run(tmp_path, {
        "design.md": DESIGN,
        "detailed-design.md": DETAILED_NEITHER,
        "plan.md": PLAN_ONE_PHASE,
    })
    assert r.returncode == 1, r.stdout
    assert "INCOMPLETE" in r.stdout
    needle = "Implementation Order is not a declared phase list"
    assert r.stdout.count(needle) == 1, "emitted exactly once"
    assert "N. **Title**" in r.stdout, "names the list shape"
    assert "### Phase N:" in r.stdout, "names the headings shape"


def test_list_shape_order_aligns_and_passes(tmp_path):
    r = _run(tmp_path, {
        "design.md": DESIGN,
        "detailed-design.md": DETAILED_LIST,
        "plan.md": PLAN_ONE_PHASE,
    })
    assert r.returncode == 0, r.stdout
    assert "RESULT: ALL CHECKS PASSED" in r.stdout
    assert "Detailed: 1 modules, 1 interfaces, 1 phases" in r.stdout
    assert (tmp_path / "d" / ".plan-audit-pass.json").is_file()
