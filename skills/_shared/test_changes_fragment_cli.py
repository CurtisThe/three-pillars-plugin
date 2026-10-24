"""test_changes_fragment_cli.py — Task 1.1: `validate --repo-root` and the CLI exit codes.

design: living-doc-fragments, Task 1.1. Fixture repos and fragments are built here; the CLI runs as a
subprocess so the exit code and the `changes_fragment: <section>: <reason>` lines are the real ones (B4).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import changes_fragment as cf  # noqa: E402

MODULE = Path(__file__).resolve().parent / "changes_fragment.py"
DOCS = "three-pillars-docs"
FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n"

ROADMAP = "# Roadmap\n\n## Current Focus\n\n- old row\n- keep row\n\n## Design Inventory\n\n| a | b |\n"
ARCH = "# Architecture\n\n## Components\n\n- existing bullet\n"


def make_repo(root: Path, *, roadmap: str = ROADMAP, arch: str = ARCH) -> Path:
    docs = root / DOCS
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "product_roadmap.md").write_text(roadmap, encoding="utf-8")
    (docs / "architecture.md").write_text(arch, encoding="utf-8")
    return root


def write_fragment(root: Path, body: str = "", *, name: str = "demo", fm: str = FM) -> Path:
    path = root / DOCS / "changes" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fm + body, encoding="utf-8")
    return path


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(MODULE), *map(str, args)], capture_output=True,
                          text=True, encoding="utf-8", check=False)


def problem_lines(proc: subprocess.CompletedProcess) -> list[list[str]]:
    """Each printed problem as [prefix, section, reason...], split on the documented `: `."""
    return [line.split(": ", 2) for line in proc.stdout.splitlines() if line.strip()]


# --- validate(repo_root=...) against the target docs ---------------------------------------------

def test_validate_against_repo_targets(tmp_path):
    root = make_repo(tmp_path)
    body = ("\n## Roadmap\n\n### Current Focus\n- - old row\n+ - new row\n\n"
            "## Architecture\n\n### Components\n+ - added\n- - existing bullet\n")
    fragment = cf.parse(FM + body, stem="demo")
    assert cf.validate(fragment, repo_root=root) == []


def test_missing_heading_and_missing_line_are_problems(tmp_path):
    root = make_repo(tmp_path)
    body = ("\n## Roadmap\n\n### No Such Heading\n+ x\n\n### Current Focus\n- - not in the doc\n\n"
            "## Architecture\n\n### Components\n- - existing bullet\n\n### Also Missing\n+ y\n")
    problems = cf.validate(cf.parse(FM + body, stem="demo"), repo_root=root)
    assert sorted((p.section, p.line) for p in problems) == [
        ("Architecture", 20), ("Roadmap", 9), ("Roadmap", 13)]


def test_removal_matches_the_whole_line_not_a_substring(tmp_path):
    root = make_repo(tmp_path)
    for text in ("old", "- old", " - old row", "- old row "):
        frag = cf.parse(FM + f"\n## Roadmap\n\n### Current Focus\n- {text}\n", stem="demo")
        assert [p.section for p in cf.validate(frag, repo_root=root)] == ["Roadmap"], text
    ok = cf.parse(FM + "\n## Roadmap\n\n### Current Focus\n- - old row\n", stem="demo")
    assert cf.validate(ok, repo_root=root) == []


def test_heading_matches_at_any_level_but_by_exact_text(tmp_path):
    root = make_repo(tmp_path)
    ok = cf.parse(FM + "\n## Roadmap\n\n### Design Inventory\n+ | c | d |\n", stem="demo")
    assert cf.validate(ok, repo_root=root) == []
    partial = cf.parse(FM + "\n## Roadmap\n\n### Design\n+ | c | d |\n", stem="demo")
    assert [p.section for p in cf.validate(partial, repo_root=root)] == ["Roadmap"]


def test_each_section_is_checked_against_its_own_doc(tmp_path):
    root = make_repo(tmp_path)
    body = "\n## Architecture\n\n### Current Focus\n+ x\n"  # a roadmap heading, not an arch one
    problems = cf.validate(cf.parse(FM + body, stem="demo"), repo_root=root)
    assert [p.section for p in problems] == ["Architecture"]


def test_missing_target_doc_is_a_problem_not_a_crash(tmp_path):
    (tmp_path / DOCS).mkdir()
    body = "\n## Roadmap\n\n### Current Focus\n+ x\n"
    problems = cf.validate(cf.parse(FM + body, stem="demo"), repo_root=tmp_path)
    assert [p.section for p in problems] == ["Roadmap"]


def test_other_sections_need_no_docs_at_the_root(tmp_path):
    body = ("\n## Known issues — add\n\n### M-new-a: T\nbody\n\n## Known issues — resolve\n\n"
            "- M1: done\n\n## Vision\n\nprose\n")
    assert cf.validate(cf.parse(FM + body, stem="demo"), repo_root=tmp_path) == []


def test_frontmatter_only_fragment_validates_against_an_empty_root(tmp_path):
    assert cf.validate(cf.parse(FM, stem="demo"), repo_root=tmp_path) == []


# --- the CLI --------------------------------------------------------------------------------------

def test_cli_exit_codes_and_section_named(tmp_path):
    root = make_repo(tmp_path)
    good = write_fragment(root, "\n## Roadmap\n\n### Current Focus\n+ - new\n")
    proc = run_cli("validate", good, "--repo-root", root)
    assert (proc.returncode, problem_lines(proc)) == (0, [])

    bad = write_fragment(root, "\n## Notes\n\ntext\n\n## Roadmap\n\nprose line\n", name="bad",
                         fm=FM.replace("demo", "bad"))
    proc = run_cli("validate", bad)
    assert proc.returncode == 1
    lines = problem_lines(proc)
    assert [(p[0], p[1]) for p in lines] == [("changes_fragment", "Notes"),
                                             ("changes_fragment", "Roadmap")]
    assert all(len(p) == 3 and p[2] for p in lines)


def test_cli_usage_errors_exit_2(tmp_path):
    good = write_fragment(make_repo(tmp_path))
    assert run_cli().returncode == 2
    assert run_cli("nonsense", good).returncode == 2
    assert run_cli("validate").returncode == 2
    assert run_cli("validate", good, "--no-such-flag").returncode == 2
    assert run_cli("validate", good, "--repo-root", tmp_path / "absent").returncode == 2


def test_cli_json_output(tmp_path):
    root = make_repo(tmp_path)
    bad = write_fragment(root, "\n## Notes\n\ntext\n")
    proc = run_cli("validate", bad, "--json")
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert [(p["section"], p["line"]) for p in payload["problems"]] == [("Notes", 7)]
    good = write_fragment(root, "", name="demo")
    proc = run_cli("validate", good, "--json")
    assert (proc.returncode, json.loads(proc.stdout)) == (0, {"ok": True, "problems": []})


def test_missing_file_is_a_problem_exit_1(tmp_path):
    proc = run_cli("validate", tmp_path / DOCS / "changes" / "ghost.md")
    assert proc.returncode == 1
    assert "changes_fragment: file: missing" in proc.stdout.splitlines()
    proc = run_cli("validate", tmp_path / "ghost.md", "--json", "--require-learned")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["problems"] == [
        {"section": "file", "line": None, "reason": "missing"}]


def test_a_directory_or_non_utf8_file_is_a_file_problem(tmp_path):
    proc = run_cli("validate", tmp_path)
    assert (proc.returncode, problem_lines(proc)[0][:2]) == (1, ["changes_fragment", "file"])
    binary = tmp_path / "demo.md"
    binary.write_bytes(b"---\nslug: \xff\xfe\n---\n")
    proc = run_cli("validate", binary)
    assert (proc.returncode, problem_lines(proc)[0][:2]) == (1, ["changes_fragment", "file"])


def test_slug_must_equal_the_file_stem(tmp_path):
    path = write_fragment(make_repo(tmp_path), name="other")  # frontmatter says slug: demo
    proc = run_cli("validate", path)
    assert proc.returncode == 1
    assert problem_lines(proc)[0][:2] == ["changes_fragment", "front" + "matter"]


def test_frontmatter_only_fragment_exits_0(tmp_path):
    root = make_repo(tmp_path)
    path = write_fragment(root)
    assert run_cli("validate", path).returncode == 0
    assert run_cli("validate", path, "--repo-root", root).returncode == 0


def test_cli_repo_root_checks_target_docs(tmp_path):
    root = make_repo(tmp_path)
    path = write_fragment(root, "\n## Roadmap\n\n### Missing Heading\n+ x\n")
    assert run_cli("validate", path).returncode == 0  # no root = grammar only
    proc = run_cli("validate", path, "--repo-root", root)
    assert proc.returncode == 1
    assert problem_lines(proc)[0][:2] == ["changes_fragment", "Roadmap"]


def test_require_learned_flag(tmp_path):
    root = make_repo(tmp_path)
    plain = write_fragment(root)
    assert run_cli("validate", plain).returncode == 0
    proc = run_cli("validate", plain, "--require-learned")
    assert proc.returncode == 1
    assert "changes_fragment: learned: missing" in proc.stdout.splitlines()

    learned_fm = FM.replace("date: 2026-10-22\n", "date: 2026-10-22\nlearned: 2026-10-23\n")
    learned = write_fragment(root, "", fm=learned_fm)
    assert run_cli("validate", learned, "--require-learned").returncode == 0

    bad_fm = FM.replace("date: 2026-10-22\n", "date: 2026-10-22\nlearned: tomorrow\n")
    bad = write_fragment(root, "", fm=bad_fm)
    assert run_cli("validate", bad).returncode == 1
    assert run_cli("validate", bad, "--require-learned").returncode == 1
