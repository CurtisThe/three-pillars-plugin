"""test_plan_couplings.py — the plan-audit prechecks: couplings + split targets.

design: run-throughput Part C (detailed-design-part-c.md, §plan_couplings)

`plan_couplings.py <design-dir> [--root .]` runs two checks over
`<design-dir>/plan.md`:
  (a) couplings — a `(new)` File item matching a `plan_audit.couplings`
      `when_new` glob must have `requires_listed` in the same task's File list;
  (b) split targets — an edit of an existing capped file is flagged when
      `lines(File) + growth >= the class's HARD line cap` (default growth +50),
      unless the task declares a `**Split**` line, or the file is grandfathered
      and the declared growth is <= 0; exempt and uncapped paths never fire.
Findings print as one JSON object; exit 0 clean, 1 findings, 2 usage error.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import plan_couplings  # noqa: E402

CONFIG = {
    "schema_version": 1,
    "plan_audit": {"couplings": [
        {"when_new": "skills/_shared/*hot_patch*",
         "requires_listed": "skills/_shared/hot_patch.py"}]},
}
EXPECTED_KEYS = {"task", "check", "category", "confidence", "severity",
                 "description", "suggested_fix"}


def _write(root: Path, rel: str, lines: int) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("line\n" * lines, encoding="utf-8")


def _repo(tmp_path, files=None, config=None, grandfather=()) -> Path:
    """A tmp repo root: config, the given files, an optional grandfather list."""
    root = tmp_path / "repo"
    (root / ".three-pillars").mkdir(parents=True)
    (root / ".three-pillars" / "config.json").write_text(
        json.dumps(config if config is not None else CONFIG), encoding="utf-8")
    for rel, n in (files or {}).items():
        _write(root, rel, n)
    if grandfather:
        (root / ".three-pillars" / "file-size-grandfather.txt").write_text(
            "\n".join(grandfather) + "\n", encoding="utf-8")
    return root


def _design(root: Path, title: str, items, extra_fields="") -> Path:
    """A design dir with one task under id 1.1; items are (path, marker|None)."""
    file_field = ", ".join(
        f"`{p}` ({m})" if m else f"`{p}`" for p, m in items)
    design = root / "three-pillars-docs" / "tp-designs" / "d"
    design.mkdir(parents=True, exist_ok=True)
    (design / "plan.md").write_text(
        "# plan\n\n## Phase 1\n\n"
        f"### Task 1.1: {title}\n\n"
        f"**File**: {file_field}\n\n"
        f"{extra_fields}"
        "**Test**: x\n",
        encoding="utf-8")
    return design


def _finding_shape(f):
    assert EXPECTED_KEYS <= set(f), f
    assert f["category"] == "INCONSISTENT", f
    assert f["confidence"] == "medium", f
    assert f["severity"] == "medium", f


# --- (a) couplings -------------------------------------------------------------

def test_new_hot_patch_file_without_required_listing_finds(tmp_path):
    root = _repo(tmp_path, files={"skills/_shared/hot_patch.py": 10})
    design = _design(root, "add a helper",
                     [("skills/_shared/foo_hot_patch_x.py", "new")])
    findings = plan_couplings.run_checks(design, root)
    assert len(findings) == 1
    _finding_shape(findings[0])
    assert findings[0]["check"] == "coupling"
    assert findings[0]["task"] == "1.1"
    assert "skills/_shared/hot_patch.py" in findings[0]["description"]
    assert "skills/_shared/hot_patch.py" in findings[0]["suggested_fix"]


def test_new_hot_patch_file_with_required_listing_is_clean(tmp_path):
    root = _repo(tmp_path, files={"skills/_shared/hot_patch.py": 10})
    design = _design(root, "add a helper",
                     [("skills/_shared/foo_hot_patch_x.py", "new"),
                      ("skills/_shared/hot_patch.py", "modify")])
    assert plan_couplings.run_checks(design, root) == []


def test_unmarked_hot_patch_file_is_not_a_new_file(tmp_path):
    # A "touches" item (no marker) does not trigger the coupling.
    root = _repo(tmp_path, files={"skills/_shared/hot_patch.py": 10})
    design = _design(root, "touch", [("skills/_shared/foo_hot_patch_x.py", None)])
    assert plan_couplings.run_checks(design, root) == []


def test_only_the_violating_task_finds(tmp_path):
    root = _repo(tmp_path, files={"a/b.py": 10,
                                 "skills/_shared/hot_patch.py": 10})
    design = root / "three-pillars-docs" / "tp-designs" / "d"
    design.mkdir(parents=True)
    (design / "plan.md").write_text(
        "# plan\n\n## Phase 1\n\n"
        "### Task 1.1: edit b\n\n"
        "**File**: `a/b.py` (modify)\n\n**Test**: x\n\n"
        "## Phase 2\n\n"
        "### Task 2.1: add a helper\n\n"
        "**File**: `skills/_shared/foo_hot_patch_x.py` (new)\n\n**Test**: x\n",
        encoding="utf-8")
    findings = plan_couplings.run_checks(design, root)
    assert [f["task"] for f in findings] == ["2.1"]
    assert findings[0]["check"] == "coupling"


# --- (b) split targets ----------------------------------------------------------

def test_edit_near_hard_cap_without_split_finds(tmp_path):
    root = _repo(tmp_path, files={"skills/a/big.py": 475})
    design = _design(root, "edit big", [("skills/a/big.py", "modify")])
    findings = plan_couplings.run_checks(design, root)
    assert len(findings) == 1
    _finding_shape(findings[0])
    assert findings[0]["check"] == "split"
    assert findings[0]["task"] == "1.1"
    assert "skills/a/big.py" in findings[0]["description"]


def test_edit_near_hard_cap_with_split_path_is_clean(tmp_path):
    root = _repo(tmp_path, files={"skills/a/big.py": 475})
    design = _design(root, "edit big", [("skills/a/big.py", "modify")],
                     "**Split**: skills/a/big_part.py\n\n")
    assert plan_couplings.run_checks(design, root) == []


def test_edit_near_hard_cap_with_split_none_is_clean(tmp_path):
    root = _repo(tmp_path, files={"skills/a/big.py": 475})
    design = _design(root, "edit big", [("skills/a/big.py", "modify")],
                     "**Split**: none — one-field change, no growth expected\n\n")
    assert plan_couplings.run_checks(design, root) == []


def test_small_edit_below_cap_is_clean(tmp_path):
    # 417 + default growth 50 = 467 < 500 hard cap: not flagged.
    root = _repo(tmp_path, files={"skills/a/mid.py": 417})
    design = _design(root, "edit mid", [("skills/a/mid.py", "modify")])
    assert plan_couplings.run_checks(design, root) == []


def test_declared_growth_can_push_over_the_cap(tmp_path):
    # 417 + 100 = 517 >= 500: flagged.
    root = _repo(tmp_path, files={"skills/a/mid.py": 417})
    design = _design(root, "edit mid", [("skills/a/mid.py", "modify")],
                     "**Growth**: +100\n\n")
    findings = plan_couplings.run_checks(design, root)
    assert len(findings) == 1
    assert findings[0]["check"] == "split"


def test_grandfathered_over_cap_file_with_zero_growth_is_clean(tmp_path):
    # 520 is already OVER the 500 cap: it would be flagged (520 >= 500) were
    # it not grandfathered + declared non-growing — grandfathering decides.
    root = _repo(tmp_path, files={"skills/a/legacy.py": 520},
                 grandfather=("skills/a/legacy.py",))
    design = _design(root, "edit legacy", [("skills/a/legacy.py", "modify")],
                     "**Growth**: +0\n\n")
    assert plan_couplings.run_checks(design, root) == []


def test_over_cap_file_with_zero_growth_but_not_grandfathered_finds(tmp_path):
    # Same file, same Growth: +0, but NOT on the grandfather list: grandfather
    # (not the zero growth) is what exempts it, so it is flagged.
    root = _repo(tmp_path, files={"skills/a/legacy.py": 520})
    design = _design(root, "edit legacy", [("skills/a/legacy.py", "modify")],
                     "**Growth**: +0\n\n")
    findings = plan_couplings.run_checks(design, root)
    assert len(findings) == 1
    assert findings[0]["check"] == "split"


def test_grandfathered_over_cap_file_without_growth_declared_finds(tmp_path):
    # Grandfathering alone does not exempt: a declared `**Growth**` <= 0 is
    # required, so an undeclared growth (default +50) still flags.
    root = _repo(tmp_path, files={"skills/a/legacy.py": 520},
                 grandfather=("skills/a/legacy.py",))
    design = _design(root, "edit legacy", [("skills/a/legacy.py", "modify")])
    findings = plan_couplings.run_checks(design, root)
    assert len(findings) == 1
    assert findings[0]["check"] == "split"


def test_new_file_is_never_split_checked(tmp_path):
    # A (new) file starts at zero lines: no split finding even at 0 bytes.
    root = _repo(tmp_path)
    design = _design(root, "create", [("skills/a/big_new.py", "new")])
    assert plan_couplings.run_checks(design, root) == []


def test_uncapped_file_is_not_checked(tmp_path):
    root = _repo(tmp_path, files={"a/big.txt": 600})
    design = _design(root, "edit txt", [("a/big.txt", "modify")])
    assert plan_couplings.run_checks(design, root) == []


def test_exempt_design_doc_is_not_checked(tmp_path):
    root = _repo(tmp_path,
                 files={"three-pillars-docs/tp-designs/d/notes.md": 600})
    design = root / "three-pillars-docs" / "tp-designs" / "d"
    design.mkdir(parents=True, exist_ok=True)
    (design / "plan.md").write_text(
        "# plan\n\n## Phase 1\n\n"
        "### Task 1.1: extend notes\n\n"
        "**File**: `three-pillars-docs/tp-designs/d/notes.md` (modify)\n\n"
        "**Test**: x\n",
        encoding="utf-8")
    assert plan_couplings.run_checks(design, root) == []


def test_markdown_class_cap_is_used(tmp_path):
    # markdown hard cap is 500 too: 470 + 50 >= 500 → flagged.
    root = _repo(tmp_path, files={"docs/guide.md": 470})
    design = _design(root, "edit guide", [("docs/guide.md", "modify")])
    findings = plan_couplings.run_checks(design, root)
    assert len(findings) == 1
    assert findings[0]["check"] == "split"


# --- CLI: exit codes 0 / 1 / 2 ---------------------------------------------------

def _run_cli(design: Path, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "plan_couplings.py"), str(design),
         "--root", str(root)],
        capture_output=True, text=True, check=False)


def test_cli_exit_0_clean(tmp_path):
    root = _repo(tmp_path, files={"skills/a/mid.py": 417})
    design = _design(root, "edit mid", [("skills/a/mid.py", "modify")])
    p = _run_cli(design, root)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["findings"] == []


def test_cli_exit_1_with_finding_json(tmp_path):
    root = _repo(tmp_path, files={"skills/a/big.py": 475})
    design = _design(root, "edit big", [("skills/a/big.py", "modify")])
    p = _run_cli(design, root)
    assert p.returncode == 1, p.stdout
    data = json.loads(p.stdout)
    assert len(data["findings"]) == 1
    assert EXPECTED_KEYS <= set(data["findings"][0])
    assert data["findings"][0]["check"] == "split"


def test_cli_exit_2_missing_design_dir(tmp_path):
    root = _repo(tmp_path)
    p = _run_cli(root / "no-such-design", root)
    assert p.returncode == 2
    assert p.stdout.strip() == ""  # the error goes to stderr


def test_cli_exit_2_missing_plan_md(tmp_path):
    root = _repo(tmp_path)
    design = root / "three-pillars-docs" / "tp-designs" / "d"
    design.mkdir(parents=True)
    p = _run_cli(design, root)
    assert p.returncode == 2


def test_cli_exit_2_bad_config(tmp_path):
    root = _repo(tmp_path, config="{not valid json")
    design = _design(root, "edit", [("a/b.py", "modify")])
    p = _run_cli(design, root)
    assert p.returncode == 2
