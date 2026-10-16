"""test_fragility_repo_rules.py — per-repo fragility rules: load, validate, enforce.

design: fragile-test-prevention (detailed-design-lint §Per-repo rules)

Every rules file is built here as a dict and written as JSON into a temp tree. An error is
checked for the rule id and file it names, never its wording. Enforcement runs through
`fragility_lint.main --json`; a flagged fixture line is marked `# hit`.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import fragility_repo_rules
from fragility_lint import main
from fragility_registry import RULES
from fragility_repo_rules import RULES_PATH, load

KIND_RULES = [
    {"id": "no-helper", "kind": "forbidden-call", "params": {"call": "mymod.helper"}},
    {"id": "no-skip-names", "kind": "forbidden-literal-name",
     "params": {"name_glob": "SKIP_*"}},
    {"id": "no-json-pin", "kind": "forbidden-read-assert",
     "params": {"path_glob": "fixtures/*.json"}},
]
APPROVAL = {"reason": "a golden file is not a contract", "approved_by": "Curtis",
            "date": "2026-09-30"}

CALL_SRC = """\
import mymod


def test_a():
    mymod.helper()  # hit
    mymod.other()
    helper()
"""
LITERAL_SRC = """\
SKIP_NAMES = {"a", "b"}  # hit
SKIP_ALL: frozenset = frozenset(("x", "y"))  # hit
SKIP_DERIVED = frozenset(REGISTRY)
KEEP_NAMES = {"a"}
"""
READ_SRC = """\
import json
from pathlib import Path

DATA = Path(__file__).parent / "fixtures" / "golden.json"


def test_pin():
    text = DATA.read_text(encoding="utf-8")
    assert "status" in text  # hit
    assert json.loads(text)["status"] == "ok"


def test_other_file():
    assert "x" in Path("fixtures/notes.txt").read_text(encoding="utf-8")
"""
KIND_CASES = [  # (rule, fixture file, fixture source, the side that file is on)
    (KIND_RULES[0], "test_calls.py", CALL_SRC, "tests"),
    (KIND_RULES[1], "filters.py", LITERAL_SRC, "production"),
    (KIND_RULES[2], "test_reads.py", READ_SRC, "tests"),
]
OTHER_SIDE = {"tests": "production", "production": "tests"}
CLEAN = "def test_ok():\n    assert 1 + 1 == 2\n"


def _rule(base: dict, **over) -> dict:
    return {**base, **APPROVAL, **over}


def _doc(*rules: dict, version=1) -> dict:
    return {"schema_version": version, "rules": list(rules)}


GOOD = _rule(KIND_RULES[0])


def _without(key: str) -> dict:
    return {k: v for k, v in GOOD.items() if k != key}


def _write(root: Path, rel: str | Path, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_rules(root: Path, doc: dict) -> Path:
    return _write(root, RULES_PATH, json.dumps(doc))


def _marked(source: str) -> set[int]:
    return {n for n, line in enumerate(source.splitlines(), 1) if line.endswith("# hit")}


def _json(capsys, *args: str) -> dict:
    code = main([*args, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit"] == code
    return payload


def _repo_hits(payload: dict) -> list[dict]:
    return [h for h in payload["hits"] if h["source"] == "repo"]


# --- load and validate --------------------------------------------------------------

def test_a_valid_file_with_the_three_kinds_loads(tmp_path):
    _write_rules(tmp_path, _doc(*(_rule(r) for r in KIND_RULES)))
    loaded = load(tmp_path)
    assert list(loaded.errors) == []
    assert [(r.id, r.kind, r.params) for r in loaded.rules] == \
        [(r["id"], r["kind"], r["params"]) for r in KIND_RULES]
    assert [r.gating for r in loaded.rules] == [False] * len(KIND_RULES)


def test_the_table_covers_every_kind():
    assert {r["kind"] for r in KIND_RULES} == set(fragility_repo_rules.KINDS)


def test_an_absent_file_gives_zero_rules_and_repo_rules_zero(tmp_path, capsys, monkeypatch):
    loaded = load(tmp_path)
    assert (list(loaded.rules), list(loaded.errors)) == ([], [])
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, "test_ok.py", CLEAN)
    payload = _json(capsys, "scan", ".")
    assert (payload["exit"], payload["repo_rules"]) == (0, 0)


FIELD_ERRORS = [
    *(pytest.param(r.id, _doc(_rule(GOOD, id=r.id)), id=f"generic-{r.id}") for r in RULES),
    pytest.param("Bad_Id", _doc(_rule(GOOD, id="Bad_Id")), id="id-shape"),
    pytest.param("", _doc(_rule(GOOD, id="")), id="id-empty"),
    pytest.param("no-helper", _doc(GOOD, GOOD), id="id-duplicate"),
    pytest.param("no-helper", _doc(_rule(GOOD, kind="forbidden-import")), id="kind-unknown"),
    pytest.param("no-helper", _doc(_rule(GOOD, params={})), id="param-missing"),
    pytest.param("no-helper", _doc(_rule(GOOD, params={"call": "a.b", "name_glob": "X"})),
                 id="param-unknown"),
    pytest.param("no-helper", _doc(_rule(GOOD, params={"call": ""})), id="param-empty"),
    pytest.param("no-helper", _doc(_rule(GOOD, reason="")), id="reason-empty"),
    pytest.param("no-helper", _doc(_rule(GOOD, reason="   ")), id="reason-blank"),
    pytest.param("no-helper", _doc(_without("reason")), id="reason-missing"),
    pytest.param("no-helper", _doc(_rule(GOOD, approved_by="")), id="approved-by-empty"),
    pytest.param("no-helper", _doc(_without("approved_by")), id="approved-by-missing"),
    pytest.param("no-helper", _doc(_rule(GOOD, date="2026-13-01")), id="date-no-such-day"),
    pytest.param("no-helper", _doc(_rule(GOOD, date="30/09/2026")), id="date-not-iso"),
    pytest.param("no-helper", _doc(_rule(GOOD, date="20260930")), id="date-compact"),
    pytest.param("no-helper", _doc(_without("date")), id="date-missing"),
    pytest.param("no-helper", _doc(_rule(GOOD, applies_to="docs")), id="applies-to-unknown"),
    pytest.param("no-helper", _doc(_rule(GOOD, gating="yes")), id="gating-not-bool"),
    pytest.param("no-helper", _doc(_rule(GOOD, owner="me")), id="rule-key-unknown"),
]


def _errors_of(root: Path, doc: dict) -> tuple[Path, list[str]]:
    path = _write_rules(root, doc)
    loaded = load(root)
    assert list(loaded.rules) == [], "a file with an error loads no rule"
    return path, list(loaded.errors)


@pytest.mark.parametrize("rule_id, doc", FIELD_ERRORS)
def test_each_field_error_is_an_error_naming_the_rule_and_the_file(tmp_path, rule_id, doc):
    path, errors = _errors_of(tmp_path, doc)
    assert any(rule_id in e and str(path) in e for e in errors), errors


@pytest.mark.parametrize("doc", [
    pytest.param(_doc(GOOD, version=2), id="version-2"),
    pytest.param(_doc(GOOD, version="1"), id="version-string"),
    pytest.param({"rules": [GOOD]}, id="version-missing"),
    pytest.param({"schema_version": 1, "rules": {"no-helper": GOOD}}, id="rules-not-a-list"),
    pytest.param([GOOD], id="not-an-object"),
])
def test_a_bad_document_shape_is_an_error_naming_the_file(tmp_path, doc):
    path, errors = _errors_of(tmp_path, doc)
    assert errors and all(str(path) in e for e in errors)


# --- the lint: repo_rules, a broken file, --rules ------------------------------------

def test_scan_json_counts_the_loaded_repo_rules(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_rules(tmp_path, _doc(*(_rule(r) for r in KIND_RULES)))
    _write(tmp_path, "test_ok.py", CLEAN)
    payload = _json(capsys, "scan", ".")
    assert (payload["exit"], payload["repo_rules"]) == (0, len(KIND_RULES))


BROKEN = [pytest.param(json.dumps(_doc(GOOD, version=2)), id="schema-version"),
          pytest.param(json.dumps(_doc(_rule(GOOD, date="soon"))), id="rule-error"),
          pytest.param("{not json", id="not-json")]


@pytest.mark.parametrize("text", BROKEN)
def test_a_broken_rules_file_makes_scan_exit_two(tmp_path, capsys, monkeypatch, text):
    monkeypatch.chdir(tmp_path)
    path = _write(tmp_path, RULES_PATH, text)
    _write(tmp_path, "test_ok.py", CLEAN)
    payload = _json(capsys, "scan", ".")
    assert payload["exit"] == 2
    assert any(path.name in e for e in payload["could_not_evaluate"])


def test_the_rules_flag_names_another_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    other = _write(tmp_path, "elsewhere/rules.json", json.dumps(_doc(GOOD)))
    _write(tmp_path, "test_calls.py", CALL_SRC)
    payload = _json(capsys, "scan", "test_calls.py", "--rules", str(other))
    assert payload["repo_rules"] == 1
    assert {h["line"] for h in _repo_hits(payload)} == _marked(CALL_SRC)


# --- each kind, respecting applies_to ------------------------------------------------

@pytest.mark.parametrize("rule, name, source, side", KIND_CASES,
                         ids=[case[0]["kind"] for case in KIND_CASES])
@pytest.mark.parametrize("scope", ["own-side", "all", "other-side"])
def test_each_kind_matches_its_shape_where_it_applies(tmp_path, capsys, monkeypatch,
                                                      rule, name, source, side, scope):
    applies_to = {"own-side": side, "all": "all", "other-side": OTHER_SIDE[side]}[scope]
    monkeypatch.chdir(tmp_path)
    _write_rules(tmp_path, _doc(_rule(rule, applies_to=applies_to)))
    _write(tmp_path, name, source)
    payload = _json(capsys, "scan", ".")
    hits = _repo_hits(payload)
    assert {h["line"] for h in hits} == (set() if scope == "other-side" else _marked(source))
    assert all((h["rule"], h["gating"]) == (rule["id"], False) for h in hits)
    assert payload["exit"] == 0


# --- check: a gating per-repo rule gates on added lines only --------------------------

@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    """A test run from a git hook inherits GIT_DIR / GIT_INDEX_FILE; drop them all."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root,
                          capture_output=True, text=True, check=True, encoding="utf-8")
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(root: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        _write(root, name, text)
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", "c")
    return _git(root, "rev-parse", "HEAD")


ADDED_CALL = "\n\ndef test_c():\n    mymod.helper()  # hit\n"
ADDED_CLEAN = "\n\ndef test_b():\n    assert True\n"


@pytest.mark.parametrize("gating, blocked", [(True, 1), (False, 0)])
def test_a_repo_rule_gates_by_its_flag_on_added_lines_only(repo, capsys, gating, blocked):
    _write_rules(repo, _doc(_rule(GOOD, gating=gating)))
    base = _commit(repo, {"test_calls.py": CALL_SRC})
    _commit(repo, {"test_calls.py": CALL_SRC + ADDED_CLEAN})
    untouched = _json(capsys, "check", "--base", base, "--head", "HEAD")
    assert (untouched["exit"], untouched["hits"]) == (0, [])
    _commit(repo, {"test_calls.py": CALL_SRC + ADDED_CLEAN + ADDED_CALL})
    added = _json(capsys, "check", "--base", base, "--head", "HEAD")
    new_lines = _marked(CALL_SRC + ADDED_CLEAN + ADDED_CALL) - _marked(CALL_SRC)
    assert added["exit"] == blocked
    assert [(h["rule"], h["source"], h["gating"], h["line"] in new_lines)
            for h in added["hits"]] == [(GOOD["id"], "repo", gating, True)]


def test_a_broken_rules_file_makes_check_exit_two_naming_it(repo, capsys):
    base = _commit(repo, {"test_ok.py": CLEAN})
    path = _write_rules(repo, _doc(_rule(GOOD, gating=True), version=2))
    _commit(repo, {"test_calls.py": CALL_SRC})
    payload = _json(capsys, "check", "--base", base)
    assert payload["exit"] == 2
    assert any(path.name in e for e in payload["could_not_evaluate"])
