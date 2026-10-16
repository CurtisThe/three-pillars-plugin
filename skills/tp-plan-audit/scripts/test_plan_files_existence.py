"""test_plan_files_existence.py — existence against the disk **plus** earlier tasks.

design: consumer-repo-parity (H4, Phase 3, Task 3.2)

``check_file_existence(tasks, root)`` walks the tasks in plan order keeping
``created = set()``:

* ``(modify)`` of a path that is neither on disk nor in ``created`` →
  WARN ``task X: modifies <p>, which does not exist and no earlier task creates it``
* ``(new)`` of a path that already exists on disk → NOTE (re-runs are legitimate)
* ``(new)`` adds the path to ``created`` — as do the ``new`` **Targets** files
* a markerless (touches) path that does not exist →
  NOTE ``task X: touches <p>, … mark it (new) or (modify)``; it never enters ``created``
* a non-canonical **File** field falls back to the lenient ``parse_files`` with
  one NOTE and its paths treated as unmarked — a legacy plan gets NOTEs, never
  WARNs, and a canonical all-``(new)`` greenfield plan gets neither
* there is no parent-directory check; relative paths resolve against ``root``,
  not the cwd
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from plan_files import check_file_existence  # noqa: E402

_WARN_MODIFY = "task {t}: modifies {p}, which does not exist and no earlier task creates it"
_NOTE_TOUCHES = "task {t}: touches {p}, which does not exist yet; mark it (new) or (modify)"
_NOTE_NONCANON = ("task {t}: File field is not declared-form (`path` (new|modify), …)"
                  "; coverage used a lenient parse")


def make_task(task_id, file=None, targets=None):
    """One dict in the shape ``audit_plan.extract_tasks`` produces."""
    fields = {}
    if file is not None:
        fields["File"] = file
    if targets is not None:
        fields["Targets"] = targets
    return {"id": task_id, "name": f"task {task_id}", "phase": 3,
            "fields": fields, "raw": ""}


def check(tasks, root):
    issues, notes = check_file_existence(tasks, root=str(root))
    return issues, notes


# --- (modify): the WARN line ----------------------------------------------------

def test_modify_of_unknown_path_is_warn(tmp_path):
    issues, notes = check([make_task("3.1", file="`ghost.py` (modify)")], tmp_path)
    assert issues == [("WARN", "Task 3.1", _WARN_MODIFY.format(t="3.1", p="ghost.py"))]
    assert notes == []


def test_modify_of_earlier_created_path_is_clean(tmp_path):
    tasks = [
        make_task("1.1", file="`pkg/core.py` (new)"),
        make_task("1.2", file="`pkg/core.py` (modify)"),
    ]
    assert check(tasks, tmp_path) == ([], []), (
        "EARLIER-CREATED: a modify after its (new) task was not judged clean"
    )

    # Task ORDER matters: a (modify) BEFORE the task that creates the path is
    # judged against disk + EARLIER creations only, so it IS a WARN.
    reordered = [
        make_task("1.1", file="`pkg/late.py` (modify)"),
        make_task("1.2", file="`pkg/late.py` (new)"),
    ]
    issues, notes = check(reordered, tmp_path)
    assert issues == [
        ("WARN", "Task 1.1", _WARN_MODIFY.format(t="1.1", p="pkg/late.py")),
    ], "EARLIER-CREATED: a modify before its (new) task was not a WARN"
    assert notes == []


# --- (new): NOTE only when the path is already on disk --------------------------

def test_new_of_existing_path_is_note_not_warn(tmp_path):
    (tmp_path / "core.py").write_text("x")
    issues, notes = check([make_task("1.1", file="`core.py` (new)")], tmp_path)
    assert issues == []
    assert len(notes) == 1
    cat, ctx, msg = notes[0]
    assert (cat, ctx) == ("NOTE", "Task 1.1")
    assert "core.py" in msg


def test_new_after_earlier_package_new_is_clean(tmp_path):
    tasks = [
        make_task("1.1", file="`src/pkg/__init__.py` (new)"),
        make_task("1.2", file="`src/pkg/core.py` (new)"),
    ]
    assert check(tasks, tmp_path) == ([], [])


def test_new_targets_files_count_as_created(tmp_path):
    tasks = [
        make_task("1.1", file="none", targets="`pkg/mod.py` (new)"),
        make_task("1.2", file="`pkg/mod.py` (modify)"),
    ]
    assert check(tasks, tmp_path) == ([], [])


def test_new_targets_count_even_without_file_field(tmp_path):
    tasks = [
        {"id": "1.1", "name": "no File", "phase": 3,
         "fields": {"Targets": "`pkg/mod.py` (new)"}, "raw": ""},
        make_task("1.2", file="`pkg/mod.py` (modify)"),
    ]
    assert check(tasks, tmp_path) == ([], [])


def test_canonical_all_new_greenfield_is_silent(tmp_path):
    tasks = [
        make_task("1.1", file="`src/pkg/__init__.py` (new)"),
        make_task("1.2", file="`src/pkg/core.py` (new), `tests/test_core.py` (new)"),
    ]
    assert check(tasks, tmp_path) == ([], [])


# --- unmarked (touches): NOTE, and never creates --------------------------------

def test_unmarked_nonexistent_is_note_and_never_created(tmp_path):
    tasks = [
        make_task("1.1", file="`lib/ghost.py`"),
        make_task("1.2", file="`lib/ghost.py` (modify)"),
    ]
    issues, notes = check(tasks, tmp_path)
    assert notes == [("NOTE", "Task 1.1", _NOTE_TOUCHES.format(t="1.1", p="lib/ghost.py"))]
    # 1.1's unmarked path never entered `created`, so 1.2 still warns.
    assert issues == [("WARN", "Task 1.2", _WARN_MODIFY.format(t="1.2", p="lib/ghost.py"))]


# --- non-canonical File: one fallback NOTE, its paths unmarked -------------------

def test_non_canonical_field_notes_once_and_paths_unmarked(tmp_path):
    tasks = [
        make_task("2.1", file="`lib/ghost.py` and more prose"),
        make_task("2.2", file="`lib/ghost.py` (modify)"),
    ]
    issues, notes = check(tasks, tmp_path)
    assert notes == [
        ("NOTE", "Task 2.1", _NOTE_NONCANON.format(t="2.1")),
        ("NOTE", "Task 2.1", _NOTE_TOUCHES.format(t="2.1", p="lib/ghost.py")),
    ]
    # the lenient path was treated as unmarked → not created → 2.2 warns
    assert issues == [("WARN", "Task 2.2", _WARN_MODIFY.format(t="2.2", p="lib/ghost.py"))]


def test_non_canonical_field_without_paths_is_single_note(tmp_path):
    issues, notes = check(
        [make_task("2.1", file="some prose, no backticks")], tmp_path)
    assert issues == []
    assert notes == [("NOTE", "Task 2.1", _NOTE_NONCANON.format(t="2.1"))]


# --- root resolution, and no parent-directory check ------------------------------

def test_paths_resolve_against_root_not_cwd(tmp_path, tmp_path_factory, monkeypatch):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.chdir(elsewhere)  # the cwd holds no such file
    (tmp_path / "core.py").write_text("x")
    issues, notes = check([make_task("1.1", file="`core.py` (modify)")], tmp_path)
    assert issues == [] and notes == []


def test_default_root_is_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    issues, _ = check_file_existence([make_task("1.1", file="`nope.py` (modify)")])
    assert any("nope.py" in msg for _cat, _ctx, msg in issues)


def test_no_parent_directory_check(tmp_path):
    # The old audit required the parent of a (new) to exist. The new check has
    # no such rule: (new) under a nonexistent nested directory is clean.
    issues, notes = check([make_task("1.1", file="`a/b/c/deep.py` (new)")], tmp_path)
    assert issues == [] and notes == []


def test_task_without_declared_fields_contributes_nothing(tmp_path):
    (tmp_path / "core.py").write_text("x")
    tasks = [
        {"id": "1.1", "name": "no fields", "phase": 3, "fields": {}, "raw": ""},
        make_task("1.2", file="`core.py` (modify)"),
    ]
    assert check(tasks, tmp_path) == ([], [])
