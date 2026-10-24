"""A test that reads a skill through a helper declares its source.

design: followups-1023 (Task 1.5, Behavior 3). `pin_tests_for` finds a pin test by
the source's path in the test text. A test that builds the path at run time
(a `_read(...)` helper, a variable dir) never names it, so it declares the source
with a `# pin-source: <path>` line, which the path arm already matches.
"""
from __future__ import annotations

from pathlib import Path

from rule_ledger_extract import pin_tests_for

REPO_ROOT = Path(__file__).resolve().parents[2]
# split so rule_ledger_extract.pin_tests_for does not take this file for a pin test
SRC = "/".join(["skills", "tp-implementation-audit", "SKILL" + ".md"])
READERS = (
    "test_certification_wiring_skills.py",
    "test_certifier_agent.py",
    "test_skill_effort.py",
    "test_cert_phrase_scan_sentinel.py",
    "test_issue_id_placeholder_docs.py",
)
BODY = 'def test_x():\n    assert _read("skills", name, "SKILL.md")\n'


def _tree(tmp_path, declare):
    skill = tmp_path / "skills" / "tp-foo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# foo\n", encoding="utf-8")
    reader = tmp_path / "skills" / "_shared" / "test_reader.py"
    reader.parent.mkdir(parents=True)
    line = "# pin-source: skills/tp-foo/SKILL.md\n" if declare else ""
    reader.write_text('"""reader."""\n' + line + BODY, encoding="utf-8")
    return reader


def test_a_declared_helper_reader_is_matched(tmp_path):
    reader = _tree(tmp_path, declare=True)
    assert pin_tests_for("skills/tp-foo/SKILL.md", tmp_path) == [reader]


def test_an_undeclared_helper_reader_is_not_matched(tmp_path):
    _tree(tmp_path, declare=False)
    assert pin_tests_for("skills/tp-foo/SKILL.md", tmp_path) == []


def test_the_matcher_docstring_names_the_declared_form():
    assert "# pin-source: <path>" in (pin_tests_for.__doc__ or "")


def test_the_five_helper_readers_of_the_real_tree_are_pin_tests():
    found = {p.relative_to(REPO_ROOT).as_posix() for p in pin_tests_for(SRC, REPO_ROOT)}
    want = {f"skills/_shared/{n}" for n in READERS if (REPO_ROOT / "skills/_shared" / n).exists()}
    assert want, "none of the five readers exists in this tree"
    assert want <= found, f"declare the source in: {sorted(want - found)}"
    assert Path(__file__).resolve() not in {p.resolve() for p in pin_tests_for(SRC, REPO_ROOT)}
