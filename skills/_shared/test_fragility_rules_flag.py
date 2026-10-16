"""test_fragility_rules_flag.py — the flag-only test rules `md-read-assert`,
`line-literal` and `doc-line-cap`.

design: fragile-test-prevention (detailed-design-lint §Rule registry, §Scoping and exit codes)

Every case is a source string parsed here: a line ending in `# HIT` must be reported by
the rule under test and no other line may be; a source with no marker is a counter-example
that passes. The three rules fire only on test files, never gate on their own, and never
change `check`'s exit code. The tables are checked against the registry's flag family,
never a hard-coded count; the other two flag rules have their own test module.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

from fragility_lint import check_diff, lint_source, main, scan
from fragility_registry import RULES
from fragility_rules_flag import VISITORS, visit

TEST_PATH = "skills/_shared/test_sample.py"
PROD_PATH = "skills/_shared/sample.py"
MD = 'Path("skills/x/SKILL.md").read_text(encoding="utf-8")'

# --- the tables: (name, source); `fn` wraps body lines in a test function ---------------
def fn(*body: str) -> str:
    return "\n".join(["def test_a():", *(f"    {line}" for line in body)]) + "\n"


def mod(*lines: str) -> str:
    return "\n".join(lines) + "\n"


TEXT = f"text = {MD}"
HELPER = f"def _skill_text():\n    return {MD}\n"

MD_READ_ASSERT = [
    ("in, on a name bound to a read", fn(TEXT, 'assert "tp-merge" in text  # HIT')),
    ("not in", fn(TEXT, 'assert "old name" not in text  # HIT')),
    ("in, with the read inline", fn(f'assert "tp-merge" in {MD}  # HIT')),
    ("in, through a method chain off the read", fn(TEXT, 'assert "a" in text.lower()  # HIT')),
    ("in, on a read through a path held in a name",
     fn('path = Path("docs") / "guide.md"', 'text = path.read_text(encoding="utf-8")',
        'assert "step" in text  # HIT')),
    ("in, on open().read() traced through a with",
     fn('with open("guide.md", encoding="utf-8") as fh:', "    text = fh.read()",
        'assert "step" in text  # HIT')),
    ("re.search", fn(TEXT, 'assert re.search(r"tp-\\w+", text)  # HIT')),
    ("re.match", fn(f'assert re.match(r"# ", {MD})  # HIT')),
    ("re.fullmatch", fn(TEXT, 'assert re.fullmatch(r"(?s).*", text)  # HIT')),
    ("re.findall", fn(TEXT, 'assert len(re.findall(r"tp-", text)) == 3  # HIT')),
    ("a compiled pattern's search", fn(TEXT, 'assert re.compile(r"tp-").search(text)  # HIT')),
    ("startswith", fn(TEXT, 'assert text.startswith("# Skill")  # HIT')),
    ("endswith", fn(f'assert {MD}.endswith("done")  # HIT')),
    ("a read bound at module level, asserted in a test",
     mod(f"TEXT = {MD}", "", "def test_a():", '    assert "tp-merge" in TEXT  # HIT')),
    ("a module-level assert on a module-level read",
     mod(f"TEXT = {MD}", 'assert "tp-merge" in TEXT  # HIT')),
    ("through a one-hop _skill_text() helper, called in the assert",
     HELPER + "\n" + fn('assert "tp-merge" in _skill_text()  # HIT')),
    ("through a one-hop helper, the call bound to a name",
     HELPER + "\n" + fn("text = _skill_text()", 'assert text.startswith("# ")  # HIT')),
    ("a hit inside a method of a test class",
     mod("class TestDoc:", "    def test_it(self):", f"        {TEXT}",
         '        assert "a" in text  # HIT')),
    ("an assert on a JSON-loaded structure",
     fn('data = json.loads(Path("x.json").read_text(encoding="utf-8"))', 'assert "a" in data')),
    ("an assert on a YAML-loaded structure",
     fn(f"meta = yaml.safe_load({MD})", 'assert "name" in meta')),
    ("an assert on a parsed frontmatter dict",
     fn(f"front = parse_frontmatter({MD})", 'assert "a" in front["names"]')),
    ("an assert on a registry-derived name set",
     fn("parsed_names = {s.name for s in registry.SKILLS}", 'assert "tp-merge" in parsed_names')),
    ("in, on a read of a non-markdown file",
     fn('text = Path("notes.txt").read_text(encoding="utf-8")', 'assert "a" in text')),
    ("a parameter shadowing a module-level read",
     mod(f"TEXT = {MD}", "", "def test_a(TEXT):", '    assert "a" in TEXT')),
    ("a markdown read that is never asserted on", fn(TEXT, "assert text")),
]

LINE_LITERAL = [
    ("lineno == int", fn("assert node.lineno == 7  # HIT")),
    ("end_lineno == int", fn("assert node.end_lineno == 9  # HIT")),
    ("the constant on the left", fn("assert 7 == node.lineno  # HIT")),
    ("an attribute named line", fn("assert hit.line == 3  # HIT")),
    ("an attribute named line_number", fn("assert hit.line_number == 3  # HIT")),
    ("an element of a line_range", fn("assert hit.line_range[0] == 3  # HIT")),
    ("a key named line", fn('assert hit["line"] == 3  # HIT')),
    ("a key read through get", fn('assert hit.get("lineno") == 3  # HIT')),
    ("an int() of a line key", fn('assert int(m["line"]) == 12  # HIT')),
    ("an ordering comparison", fn("assert node.lineno < 40  # HIT")),
    ("not equal", fn("assert node.lineno != 0  # HIT")),
    ("a negative constant", fn("assert node.lineno == -1  # HIT")),
    ("inside a larger assert", fn("assert ok and node.lineno == 7  # HIT")),
    ("two computed line numbers", fn("assert a.lineno == b.lineno")),
    ("a line number computed in the test",
     fn('expected = src.splitlines().index("x = 1") + 1', "assert hit.line == expected")),
    ("an int compared with a plain name", fn("assert count == 7")),
    ("an int compared with another attribute", fn("assert node.col == 7")),
    ("a line attribute compared with a string", fn('assert hit.line == "7"')),
    ("a line attribute compared with a boolean", fn("assert hit.line is True")),
    ("a line attribute compared with None", fn("assert hit.line != None")),
]

DOC_LINE_CAP = [
    ("len(splitlines()) <= int", fn(TEXT, "assert len(text.splitlines()) <= 500  # HIT")),
    ("len(splitlines()) < int, the read inline",
     fn(f"assert len({MD}.splitlines()) < 300  # HIT")),
    ("the constant on the left", fn(TEXT, "assert 500 >= len(text.splitlines())  # HIT")),
    ("count of newlines", fn(TEXT, 'assert text.count("\\n") == 120  # HIT')),
    ("through a method chain off the read",
     fn(TEXT, "assert len(text.strip().splitlines()) == 12  # HIT")),
    ("a module-level read",
     mod(f"TEXT = {MD}", "", "def test_a():", "    assert len(TEXT.splitlines()) <= 500  # HIT")),
    ("a one-hop helper", HELPER + "\n" + fn('assert _skill_text().count("\\n") < 300  # HIT')),
    ("a line count of something that is not a markdown read",
     fn('out = subprocess.run(["ls"], capture_output=True, text=True).stdout',
        "assert len(out.splitlines()) == 3")),
    ("a line count of a JSON read",
     fn('text = Path("x.json").read_text(encoding="utf-8")', "assert len(text.splitlines()) == 3")),
    ("two computed counts compared with each other",
     fn(TEXT, "assert len(text.splitlines()) == len(other.splitlines())")),
    ("a count of something other than newlines", fn(TEXT, 'assert text.count("step") == 3')),
    ("a markdown line count that is never compared",
     fn(TEXT, "lines = len(text.splitlines())", "assert lines")),
]

TABLES = {
    "md-read-assert": MD_READ_ASSERT,
    "line-literal": LINE_LITERAL,
    "doc-line-cap": DOC_LINE_CAP,
}
ROWS = [pytest.param(rule, src, id=f"{rule}: {name}")
        for rule, cases in TABLES.items() for name, src in cases]
FLAGGED = [pytest.param(rule, src, id=f"{rule}: {name}")
           for rule, cases in TABLES.items() for name, src in cases if "# HIT" in src]


def _marked(src: str) -> list[int]:
    return [n for n, line in enumerate(src.splitlines(), 1) if line.endswith("# HIT")]


def _hits(src: str, path: str, rule_id: str) -> list[int]:
    return [f.line for f in visit(ast.parse(src), path, None) if f.rule_id == rule_id]


@pytest.mark.parametrize("rule_id, src", ROWS)
def test_each_example_is_flagged_and_each_counter_example_passes(rule_id, src):
    assert _hits(src, TEST_PATH, rule_id) == _marked(src)


@pytest.mark.parametrize("rule_id, src", ROWS)
def test_no_other_flag_rule_reports_an_example(rule_id, src):
    assert {f.rule_id for f in visit(ast.parse(src), TEST_PATH, None)} <= {rule_id}


def test_the_tables_are_flag_rules_of_the_registry_with_a_visitor():
    flag_ids = {rule.id for rule in RULES if rule.family == "flag" and rule.side == "test"}
    assert set(TABLES) <= flag_ids
    assert set(TABLES) <= set(VISITORS)
    assert set(VISITORS) <= {rule.id for rule in RULES if rule.family == "flag"}
    for rule_id, cases in TABLES.items():
        assert any(_marked(src) for _, src in cases), f"{rule_id} has no flagged example"
        assert any(not _marked(src) for _, src in cases), f"{rule_id} has no counter-example"


@pytest.mark.parametrize("rule_id, src", FLAGGED)
def test_a_flag_rule_fires_only_on_a_test_file(rule_id, src):
    assert _hits(src, PROD_PATH, rule_id) == []
    assert _hits(src, TEST_PATH, rule_id) == _marked(src)
    assert _hits(src, "skills/_shared/conftest.py", rule_id) == _marked(src)


def test_a_finding_carries_the_asserts_span_and_findings_are_sorted_by_line():
    src = (f"def test_a():\n    text = {MD}\n    assert (\n        'a' in text\n    )\n"
           "    assert 'b' in text\n")
    found = visit(ast.parse(src), TEST_PATH, None)
    assert [(f.rule_id, f.line, f.end_line) for f in found] == [
        ("md-read-assert", 3, 5), ("md-read-assert", 6, 6)]


# --- flag rules never gate: lint_source, scan and check ---------------------------------
ALL_THREE = f"""\
def test_all():
    text = {MD}
    assert "tp-merge" in text
    assert node.lineno == 7
    assert len(text.splitlines()) <= 500
"""
_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<rule>[a-z0-9-]+) \[(?P<flag>gating|flag)\]")


def test_lint_source_reports_flag_hits_as_not_gating():
    hits = lint_source(TEST_PATH, ALL_THREE)
    assert {h.rule_id for h in hits} == set(TABLES)
    assert not any(h.gating for h in hits)


def test_a_rule_named_in_the_gating_set_gates():
    hits = lint_source(TEST_PATH, ALL_THREE, rules=["line-literal"])
    assert {h.rule_id for h in hits if h.gating} == {"line-literal"}


def test_a_waiver_silences_a_flag_hit_like_any_other():
    src = "def test_l():\n    assert node.lineno == 7  # tp-allow-fragile: fixture line\n"
    (hit,) = lint_source(TEST_PATH, src)
    assert hit.waived and hit.waiver_reason == "fixture line"


def test_scan_lists_the_flag_hits_and_exits_zero(tmp_path):
    (tmp_path / "test_pins.py").write_text(ALL_THREE, encoding="utf-8")
    result = scan([str(tmp_path)])
    assert result.exit == 0
    assert {h.rule_id for h in result.hits} == set(TABLES)


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    """A test run from a git hook inherits GIT_DIR / GIT_INDEX_FILE; drop them all."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root,
                          capture_output=True, text=True, check=True, encoding="utf-8")
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", "c")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_check_whose_only_hits_are_flag_rules_prints_flag_and_exits_zero(repo, capsys):
    base = _commit(repo, {"README.md": "# demo\n"})
    _commit(repo, {TEST_PATH: ALL_THREE})
    code = main(["check", "--base", base])
    lines = [m.groupdict() for m in map(_LINE.match, capsys.readouterr().out.splitlines()) if m]
    assert code == 0
    assert {m["rule"] for m in lines} == set(TABLES)
    assert {m["flag"] for m in lines} == {"flag"}


def test_check_diff_keeps_flag_hits_on_added_lines_only(repo):
    old = _commit(repo, {TEST_PATH: "def test_l():\n    assert node.lineno == 7\n"})
    _commit(repo, {TEST_PATH: "def test_l():\n    assert node.lineno == 7\n\n\n"
                              "def test_ok():\n    assert 1\n"})
    result = check_diff(repo, old, "HEAD")
    assert (result.exit, result.hits) == (0, [])


def test_a_gating_hit_still_blocks_beside_flag_hits(repo):
    base = _commit(repo, {"README.md": "# demo\n"})
    pin = 'def test_p():\n    assert hashlib.sha256(Path("a").read_bytes()).hexdigest() == "abc"\n'
    _commit(repo, {TEST_PATH: ALL_THREE + "\n\n" + pin})
    result = check_diff(repo, base, "HEAD")
    assert result.exit == 1
    assert {h.rule_id for h in result.hits if h.gating} == {"golden-hash"}
    assert {h.rule_id for h in result.hits if not h.gating} == set(TABLES)
