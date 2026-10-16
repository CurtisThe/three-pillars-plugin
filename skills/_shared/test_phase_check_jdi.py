"""test_phase_check_jdi.py — the just-do-it phase and the advisory warning (task 8.5).

design: review-convergence (Phase 8, `SH/phase_check.py`)

Oracle: ``example`` — a real tmp repo (``attempt_fixture``) whose design dir is a
just-do-it design.md with a ``## Scope`` section and NO plan.md, so the criteria come
from the design doc rather than a plan block. Every case is one contract line from the
phase-check companion: the ``jdi`` phase key in the carry, no invariance run (the stub is
never called), the design.md Scope as the finder's acceptance criteria, a Targets list
that stays empty, ``--phase jdi`` implying ``--jdi`` on the CLI, and ``jdi-warn`` printing
exactly one line for a just-do-it design with no ``jdi`` carry entry — silent otherwise,
exit 0 both ways because the warning is advisory and never blocks.
"""
from __future__ import annotations

import json
from pathlib import Path

import phase_check
from attempt_fixture import commit, git

DD = "three-pillars-docs/tp-designs/demo"
DESIGN_MD = f"{DD}/design.md"
CARRY_PATH = f"{DD}/{phase_check.CARRY}"

WARN_LINE = ("phase-check: just-do-it design has no jdi entry in phase-"
             "check-carry.json")

JDI_DESIGN = """---
weight-class: just-do-it
---
# Demo design

## Scope

The demo design must keep the greeting of `impl/a.py` working.

## Non-goals

No plugin surface changes.
"""

FULL_DESIGN = """---
weight-class: full
---
# Demo design

## Scope

The demo design must keep the greeting of `impl/a.py` working.
"""

PLAIN_DESIGN = """# Demo design

## Scope

The demo design must keep the greeting of `impl/a.py` working.
"""


def _stub_invariance(repo, plan_path, phase, base, head) -> dict:
    """The seam's stand-in — and the witness: a jdi prepare must never call it."""
    calls.append({"repo": str(repo), "plan": str(plan_path), "phase": phase})
    return {"verdict": "clean", "stub": True}


calls: list = []


def _repo(tmp_path: Path, design_text: str = JDI_DESIGN) -> Path:
    """A tmp repo whose design dir is a just-do-it design.md with no plan.md."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n", DESIGN_MD: design_text}, "base")
    return repo


def _read(path: Path, name: str) -> str:
    return (path / name).read_text(encoding="utf-8")


def _det(scratch: Path) -> dict:
    return json.loads(_read(scratch, "deterministic.json"))


def _carry(repo: Path) -> dict:
    return json.loads(_read(repo / DD, phase_check.CARRY))


def _prepare(repo: Path, base: str, head: str, **kw) -> dict:
    kw.setdefault("invariance", _stub_invariance)
    return phase_check.prepare(repo / DD, "jdi", base=base, head=head, repo=repo,
                               jdi=True, **kw)


def test_jdi_prepare_records_a_jdi_phase_key(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    res = _prepare(repo, base, head)
    assert res["status"] == "ready"
    entry = _carry(repo)["phases"]["jdi"]
    assert entry["status"] == "open"
    assert entry["base"] == base and entry["head"] == head
    assert Path(res["scratch"]).name == "jdi"


def test_jdi_prepare_runs_no_invariance_and_no_targets(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    calls.clear()
    res = _prepare(repo, base, head)
    assert calls == []
    det = _det(Path(res["scratch"]))
    assert det["phase"] == "jdi"
    assert det["targets"] == []
    assert det["invariance"] == {"skipped": "jdi"}


def test_jdi_criteria_come_from_the_design_md_scope(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    res = _prepare(repo, base, head)
    scratch = Path(res["scratch"])
    finder = _read(scratch, "finder.prompt.md")
    checker = _read(scratch, "checker.prompt.md")
    assert "keep the greeting of `impl/a.py` working" in finder
    assert "keep the greeting of `impl/a.py` working" in checker
    assert "No plugin surface changes" not in finder


def test_a_design_md_without_a_scope_section_says_so(tmp_path):
    repo = _tmp_repo_no_scope(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    res = _prepare(repo, base, head)
    finder = _read(Path(res["scratch"]), "finder.prompt.md")
    assert "no design.md Scope section" in finder


def _tmp_repo_no_scope(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n",
                  DESIGN_MD: "---\nweight-class: just-do-it\n---\n# Demo design\n"},
           "base")
    return repo


def test_cli_prepare_with_phase_jdi_needs_no_jdi_flag(tmp_path):
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    out = phase_check.main(["prepare", "--design-dir", str(repo / DD), "--phase", "jdi",
                            "--base", base, "--head", head, "--repo", str(repo)])
    assert out == 0
    assert _carry(repo)["phases"]["jdi"]["status"] == "open"


def test_jdi_warning_lines_and_silences(tmp_path):
    missing = _repo(tmp_path)
    assert phase_check.jdi_warning(missing / DD) == WARN_LINE

    covered = _repo(tmp_path / "covered")
    commit(covered, {CARRY_PATH: json.dumps({"phases": {"jdi": {"status": "open"}}})},
           "carry has jdi")
    assert phase_check.jdi_warning(covered / DD) is None

    for name, text in (("full", FULL_DESIGN), ("plain", PLAIN_DESIGN)):
        other = _repo(tmp_path / name, text)
        assert phase_check.jdi_warning(other / DD) is None, name

    absent = tmp_path / "nothing"
    absent.mkdir()
    assert phase_check.jdi_warning(absent) is None


def test_cli_jdi_warn_prints_the_line_and_exits_zero(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert phase_check.main(["jdi-warn", "--design-dir", str(repo / DD)]) == 0
    assert capsys.readouterr().out.strip() == WARN_LINE


def test_cli_jdi_warn_is_silent_and_exits_zero(tmp_path, capsys):
    repo = _repo(tmp_path, FULL_DESIGN)
    assert phase_check.main(["jdi-warn", "--design-dir", str(repo / DD)]) == 0
    assert capsys.readouterr().out == ""
