"""test_task_scope.py — the shared plan-field predicates (design: local-implement-and-review).

Unit tests (no git, no filesystem) for `task_scope`'s File-field parsing,
`classify_path`, and task blocks / status. The **Targets** grammar lives in
`test_task_targets.py`; dirty-tree and runner resolution in `test_task_scope_resolve.py`;
the archived-plan corpus in `test_task_scope_corpus.py`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import task_scope

# --- Module hygiene ---------------------------------------------------------------

def _top_level_imports(path: Path) -> list[str]:
    roots: list[str] = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            roots += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots.append((node.module or "").split(".")[0])
    return roots


def test_module_imports_stdlib_only():
    """No third-party dependency: every top-level import is stdlib, or a sibling
    module (split out by responsibility) that is itself stdlib-only."""
    shared = Path(task_scope.__file__).resolve().parent
    pending, seen = [Path(task_scope.__file__).resolve()], set()
    while pending:
        path = pending.pop()
        seen.add(path)
        for root in _top_level_imports(path):
            if root == "__future__" or root in sys.stdlib_module_names:
                continue
            sibling = shared / f"{root}.py"
            assert sibling.is_file(), f"{path.name} imports non-stdlib {root}"
            if sibling not in seen:
                pending.append(sibling)


# --- Task 1.2: File-field parsing and allowed-change classes ----------------------

_DD = "three-pillars-docs/tp-designs/demo"

_FILE_FORMS = [
    ("single", "`skills/_shared/a.py` (new)", ["skills/_shared/a.py"], []),
    ("list", "`skills/a.py` (modify), `skills/test_a.py` (new)",
     ["skills/a.py", "skills/test_a.py"], []),
    ("brace", f"`{_DD}/{{design.md, plan.md}}` (modify)",
     [f"{_DD}/design.md", f"{_DD}/plan.md"], []),
    ("spaces", "`docs/My Notes/file name.md` (new)", ["docs/My Notes/file name.md"], []),
    ("dot-slash", "`./framework-check.sh` (modify)", ["framework-check.sh"], []),
    ("dotfile", "`.gitignore` (modify)", [".gitignore"], []),
    ("non-path-spans", "`skills/a.py` + `strip_stale_approval` in `b.py`, tests beside them.",
     ["skills/a.py", "b.py"], []),
    ("heading-span", "`skills/x/SKILL.md` (modify — `## Audit fan-out (Slots 4/6/8)`)",
     ["skills/x/SKILL.md"], []),
    ("none-reuses", "none (reuses `task_scope.py`)", [], []),
    ("no-new-file", "(no new file — verification gate)", [], []),
    ("glob", "`skills/_shared/test_x_*.py` (new)", [], ["skills/_shared/test_x_*.py"]),
    ("brace-no-comma", "`skills/tdd-{27 dirs}/` (rename)", [], ["skills/tdd-{27 dirs}/"]),
    ("prose", "the orchestrator's dispatch prose", [], ["the orchestrator's dispatch prose"]),
    ("empty", "", [], []),
    # Corpus gaps (1.7): unbackticked lists, verification-only forms, line refs.
    ("unbackticked", "skills/_shared/a.py (new); skills/_shared/b.py",
     ["skills/_shared/a.py", "skills/_shared/b.py"], []),
    ("unbackticked-prose", "the ~24 flagged SKILL.md sites (modify)",
     [], ["the ~24 flagged SKILL.md sites (modify)"]),
    ("verification-only", "(no source edit — verification task)", [], []),
    ("no-production-file", "no production file (regression pin only)", [], []),
    ("line-ref", "`skills/x/SKILL.md:227` (modify)", ["skills/x/SKILL.md"], []),
]


@pytest.mark.parametrize(
    "field,paths,unparsed", [f[1:] for f in _FILE_FORMS], ids=[f[0] for f in _FILE_FORMS]
)
def test_parse_files_forms(field, paths, unparsed):
    assert task_scope.parse_files(field) == (paths, unparsed)


_CLASSES = [
    ("skills/_shared/a.py", "listed"),
    ("./skills/_shared/a.py", "listed"),
    ("docs/sub/x.md", "listed"),  # a listed directory covers its contents
    (f"{_DD}/plan.md", "design-dir"),
    (f"{_DD}/decisions.md", "design-dir"),
    (f"{_DD}-other/plan.md", "unlisted"),
    ("skills/_shared/b.py", "unlisted"),
]


def test_classify_path_policy():
    paths, _ = task_scope.parse_files("`skills/_shared/a.py` (modify), `docs/` (modify)")
    # task_verify passes one task's listed set; the re-run passes the phase union; the
    # design dir may arrive with or without a trailing slash. The class is identical.
    callers = [
        (set(paths), _DD),
        (frozenset(paths) | {"skills/other.py"}, _DD + "/"),
        (list(paths), _DD),
    ]
    for path, want in _CLASSES:
        got = {task_scope.classify_path(path, listed, dd) for listed, dd in callers}
        assert got == {want}, path


@pytest.mark.parametrize("listed", [
    [f"{_DD}/decisions.md"],                       # the file itself is listed
    [f"./{_DD}/decisions.md"],
    ["three-pillars-docs/"],                       # a listed dir covers the design dir
])
def test_classify_path_design_dir_wins_over_listed(listed):
    assert task_scope.classify_path(f"{_DD}/decisions.md", listed, _DD) == "design-dir"


# --- Task 1.3: task blocks and status ----------------------------------------------

def _task(tid: str, status: str | None) -> str:
    line = f"**Status**: {status}\n" if status else ""
    return (f"### Task {tid}: t{tid}\n**File**: `skills/a{tid}.py` (new)\n"
            f"**Test**: `skills/test_a{tid}.py::test_a`\n**Red**: it fails first here.\n"
            f"**Green**: g\n**Done when**: d\n{line}\n")


_PLAN = (
    "# demo — Plan\n\n## Phase 1: one [TP] (~10k)\n\n" + _task("1.1", "Done ✓")
    + _task("1.2", None) + "## Phase 2: two [TP] (~10k)\n\nPhase prose.\n\n"
    + _task("2.1", "Blocked (hook failed)") + _task("2.2", "Skipped (pre-exists)")
    + _task("2.3", "Reversed") + _task("2.4", "Skipped (needs the operator)")
    + "## Phase 3: three [TP] (~10k)\n\n" + _task("3.1", None)
)

_STATUS = {"2.1": "Blocked", "2.2": "Skipped", "2.3": "Reversed", "2.4": "Skipped"}


def test_task_status_excluded():
    blocks = {b["id"]: b for b in task_scope.phase_tasks(_PLAN, 2)}
    for tid, word in _STATUS.items():
        assert task_scope.task_status(blocks[tid]) == word
        assert task_scope.task_status(blocks[tid]["raw"]) == word  # text blocks too
        assert word in task_scope.EXCLUDED
    done = task_scope.phase_tasks(_PLAN, 1)
    assert [task_scope.task_status(b) for b in done] == ["Done", ""]
    assert "Done" not in task_scope.EXCLUDED
    assert task_scope.task_status("**Status**: Done ✓") == "Done"


def test_rerun_excluded_keeps_pre_exists():
    blocks = {b["id"]: b for b in task_scope.phase_tasks(_PLAN, 2)}
    assert task_scope.rerun_excluded(blocks["2.1"]) is True
    assert task_scope.rerun_excluded(blocks["2.3"]) is True
    assert task_scope.rerun_excluded(blocks["2.4"]) is True
    # A self-reported "already passes" claim: the re-run verifies it.
    assert task_scope.rerun_excluded(blocks["2.2"]) is False
    for block in task_scope.phase_tasks(_PLAN, 1):
        assert task_scope.rerun_excluded(block) is False


def test_phase_tasks_uses_audit_plan_splitter():
    scripts = Path(task_scope.__file__).resolve().parent.parent / "tp-plan-audit" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import audit_plan
    finally:
        sys.path.remove(str(scripts))
    want = [t for t in audit_plan.extract_tasks(_PLAN) if t["phase"] == 2]
    got = task_scope.phase_tasks(_PLAN, 2)
    assert got == want
    assert [t["id"] for t in got] == ["2.1", "2.2", "2.3", "2.4"]
    assert [t["id"] for t in task_scope.phase_tasks(_PLAN, 3)] == ["3.1"]
    assert task_scope.phase_tasks(_PLAN, 9) == []


# --- Worker work dirs: <design-dir>/ledgers/ and <design-dir>/staging/ -----------------

_WORK_PATHS = [f"{_DD}/ledgers/x.jsonl", f"{_DD}/staging/x.md"]
_DISPATCHER_PATHS = [f"{_DD}/decisions.md", f"{_DD}/plan.md", f"{_DD}/lock.json",
                     f"{_DD}/candidates/single/summary.md"]


@pytest.mark.parametrize("path", _WORK_PATHS)
def test_classify_path_work_dir_listed_is_listed(path):
    assert task_scope.classify_path(path, [path], _DD) == "listed"


@pytest.mark.parametrize("path", _WORK_PATHS)
def test_classify_path_work_dir_unlisted_is_unlisted(path):
    assert task_scope.classify_path(path, ["skills/a.py"], _DD) == "unlisted"


@pytest.mark.parametrize("path", _DISPATCHER_PATHS)
def test_classify_path_other_design_dir_stays_design_dir_even_listed(path):
    assert task_scope.classify_path(path, [path], _DD) == "design-dir"


@pytest.mark.parametrize("path", [f"{_DD}/ledgers-evil/x", f"{_DD}/stagingx/y"])
def test_classify_path_work_dir_prefix_is_on_directory_boundary(path):
    assert task_scope.classify_path(path, [path], _DD) == "design-dir"


def test_step_scope_accepts_listed_ledger_and_rejects_plan():
    import task_verify
    ledger = f"{_DD}/ledgers/x.jsonl"
    row = {"files": [ledger, f"{_DD}/plan.md"]}
    assert task_verify._step_scope([ledger], row, _DD, "sonnet") == []
    with pytest.raises(task_verify._Fail, match="design-dir touched"):
        task_verify._step_scope([f"{_DD}/plan.md"], row, _DD, "sonnet")
