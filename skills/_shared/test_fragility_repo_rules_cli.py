"""test_fragility_repo_rules_cli.py — the per-repo rules CLI: `validate` and `add`.

design: fragile-test-prevention (detailed-design-lint §Per-repo rules, §The learning loop)

`main` runs in process against a temp root; the Behavior 7 test runs both scripts as
subprocesses in a temp git repo. Files are compared as bytes and rules as loaded objects.
An error is checked for the rule id and file it names, never its wording.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import fragility_lint
import fragility_repo_rules
from fragility_repo_rules import RULES_PATH, load, main

CALL = json.dumps({"call": "mymod.helper"})
ADD = ["--kind", "forbidden-call", "--params", CALL, "--reason", "a helper is not a contract",
       "--approved-by", "Curtis"]
GOOD_RULE = {"id": "no-helper", "kind": "forbidden-call", "params": {"call": "mymod.helper"},
             "reason": "r", "approved_by": "Curtis", "date": "2026-09-30"}
TEST_SRC = "import mymod\n\n\ndef test_a():\n    mymod.helper()\n"
LINT = Path(fragility_lint.__file__).resolve()
RULES_CLI = Path(fragility_repo_rules.__file__).resolve()


def _write(root: Path, doc) -> Path:
    path = root / RULES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def _doc(*rules: dict) -> dict:
    return {"schema_version": 1, "rules": list(rules)}


def _run(capsys, *args: str) -> tuple[int, str]:
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _add(capsys, root: Path, *extra: str) -> tuple[int, str]:
    return _run(capsys, "add", "--root", str(root), *ADD, *extra)


def _siblings(root: Path) -> list[str]:
    return sorted(p.name for p in (root / RULES_PATH).parent.iterdir())


# --- validate ------------------------------------------------------------------------

def test_validate_an_absent_file_exits_zero(tmp_path, capsys):
    assert _run(capsys, "validate", "--root", str(tmp_path))[0] == 0


def test_validate_a_valid_file_exits_zero(tmp_path, capsys):
    _write(tmp_path, _doc(GOOD_RULE))
    assert _run(capsys, "validate", "--root", str(tmp_path))[0] == 0


def test_validate_defaults_the_root_to_the_working_directory(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, _doc({**GOOD_RULE, "reason": ""}))
    assert _run(capsys, "validate")[0] == 1


def test_validate_a_schema_error_exits_one_naming_the_rule_and_the_file(tmp_path, capsys):
    path = _write(tmp_path, _doc(GOOD_RULE, {**GOOD_RULE, "id": "other", "kind": "nope"}))
    code, out = _run(capsys, "validate", "--root", str(tmp_path))
    assert code == 1
    assert "other" in out and str(path) in out


@pytest.mark.parametrize("text, expected", [("{not json", 2), ('"a string"', 1)],
                         ids=["not-json", "not-an-object"])
def test_validate_a_bad_document_names_the_file(tmp_path, capsys, text, expected):
    _write(tmp_path, text)
    code, out = _run(capsys, "validate", "--root", str(tmp_path))
    assert code == expected
    assert str(tmp_path / RULES_PATH) in out


def test_validate_an_unreadable_path_exits_two(tmp_path, capsys):
    (tmp_path / RULES_PATH).mkdir(parents=True)
    assert _run(capsys, "validate", "--root", str(tmp_path))[0] == 2


# --- add: creating and appending -------------------------------------------------------

def test_add_creates_an_absent_file_with_one_valid_rule(tmp_path, capsys):
    assert not (tmp_path / ".three-pillars").exists()
    code, _ = _add(capsys, tmp_path, "--id", "no-helper")
    loaded = load(tmp_path)
    assert (code, list(loaded.errors)) == (0, [])
    [rule] = loaded.rules
    assert (rule.id, rule.kind, rule.params) == ("no-helper", "forbidden-call",
                                                 {"call": "mymod.helper"})
    assert (rule.approved_by, rule.applies_to, rule.gating) == ("Curtis", "all", False)
    assert _run(capsys, "validate", "--root", str(tmp_path))[0] == 0


def test_add_records_the_optional_fields(tmp_path, capsys):
    assert _add(capsys, tmp_path, "--applies-to", "tests", "--gating")[0] == 0
    [rule] = load(tmp_path).rules
    assert (rule.applies_to, rule.gating) == ("tests", True)


def test_add_without_an_id_derives_a_valid_one_from_the_params(tmp_path, capsys):
    assert _add(capsys, tmp_path)[0] == 0
    assert _add(capsys, tmp_path, "--id", "second")[0] == 0
    first, second = load(tmp_path).rules
    assert first.id and second.id == "second"
    assert list(load(tmp_path).errors) == []


def test_add_appends_and_keeps_the_earlier_rules(tmp_path, capsys):
    _write(tmp_path, _doc(GOOD_RULE))
    assert _add(capsys, tmp_path, "--id", "second")[0] == 0
    assert [r.id for r in load(tmp_path).rules] == ["no-helper", "second"]
    assert load(tmp_path).rules[0].params == GOOD_RULE["params"]


# --- add: refusals write nothing -------------------------------------------------------

def test_add_refuses_a_duplicate_id_and_leaves_the_file_byte_identical(tmp_path, capsys):
    path = _write(tmp_path, _doc(GOOD_RULE))
    before = path.read_bytes()
    code, out = _add(capsys, tmp_path, "--id", "no-helper")
    assert (code, path.read_bytes()) == (1, before)
    assert "no-helper" in out
    assert _siblings(tmp_path) == [path.name]


INVALID = [
    pytest.param(["--kind", "forbidden-import"], id="kind-unknown"),
    pytest.param(["--params", "{}"], id="param-missing"),
    pytest.param(["--params", '{"call": ""}'], id="param-empty"),
    pytest.param(["--params", '{"call": "a.b", "name_glob": "X"}'], id="param-unknown"),
    pytest.param(["--params", "{not json"], id="params-not-json"),
    pytest.param(["--params", "[1]"], id="params-not-an-object"),
    pytest.param(["--reason", "  "], id="reason-blank"),
    pytest.param(["--approved-by", ""], id="approved-by-empty"),
    pytest.param(["--applies-to", "docs"], id="applies-to-unknown"),
    pytest.param(["--id", "Bad_Id"], id="id-shape"),
    pytest.param(["--id", ""], id="id-empty"),
]


def _override(*pairs: str) -> list[str]:
    """`ADD` with each `--flag value` pair of `pairs` replacing the flag's default."""
    merged = dict(zip(ADD[::2], ADD[1::2]))
    merged.update(zip(pairs[::2], pairs[1::2]))
    return [part for item in merged.items() for part in item]


@pytest.mark.parametrize("over", INVALID)
def test_add_refuses_an_invalid_rule_without_creating_the_file(tmp_path, capsys, over):
    code, _ = _run(capsys, "add", "--root", str(tmp_path), *_override(*over))
    assert code == 1
    assert not (tmp_path / RULES_PATH).exists()


@pytest.mark.parametrize("over", INVALID)
def test_add_refuses_an_invalid_rule_leaving_the_file_byte_identical(tmp_path, capsys, over):
    path = _write(tmp_path, _doc(GOOD_RULE))
    before = path.read_bytes()
    code, _ = _run(capsys, "add", "--root", str(tmp_path), *_override(*over))
    assert (code, path.read_bytes()) == (1, before)


def test_add_refuses_a_generic_rule_id(tmp_path, capsys):
    generic = fragility_repo_rules.RULES[0].id
    assert _add(capsys, tmp_path, "--id", generic)[0] == 1
    assert not (tmp_path / RULES_PATH).exists()


@pytest.mark.parametrize("text", ["{not json", json.dumps(_doc({**GOOD_RULE, "reason": ""}))],
                         ids=["not-json", "schema-error"])
def test_add_never_extends_a_broken_file(tmp_path, capsys, text):
    path = _write(tmp_path, text)
    before = path.read_bytes()
    code, out = _add(capsys, tmp_path, "--id", "second")
    assert (code, path.read_bytes()) == (2, before)
    assert str(path) in out


# --- add: the write is atomic ----------------------------------------------------------

@pytest.mark.parametrize("existing", [True, False])
def test_a_failure_before_the_replace_leaves_the_old_state(tmp_path, capsys, monkeypatch,
                                                           existing):
    path = _write(tmp_path, _doc(GOOD_RULE)) if existing else tmp_path / RULES_PATH
    before = path.read_bytes() if existing else None

    def boom(src, dst):
        raise OSError("injected failure before the replace")

    monkeypatch.setattr(fragility_repo_rules.os, "replace", boom)
    code, _ = _add(capsys, tmp_path, "--id", "second")
    assert code == 2
    assert path.exists() == existing
    assert (path.read_bytes() if existing else None) == before
    leftovers = [p for p in path.parent.iterdir() if p != path] if path.parent.exists() else []
    assert leftovers == []


def test_add_replaces_through_a_temp_file_in_the_same_directory(tmp_path, capsys, monkeypatch):
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(fragility_repo_rules.os, "replace", spy)
    assert _add(capsys, tmp_path, "--id", "one")[0] == 0
    [(src, dst)] = seen
    assert (src.parent, dst) == (dst.parent, tmp_path / RULES_PATH) and src != dst
    assert not src.exists()


# --- Behavior 7: add, then the next lint run enforces the rule ---------------------------

@pytest.fixture
def clean_env(monkeypatch):
    """A test run from a git hook inherits GIT_DIR / GIT_INDEX_FILE; drop them all."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _sh(root: Path, *cmd: str) -> str:
    done = subprocess.run(list(cmd), cwd=root, capture_output=True, text=True, check=True,
                          encoding="utf-8")
    return done.stdout.strip()


def _git(root: Path, *args: str) -> str:
    return _sh(root, "git", "-c", "commit.gpgsign=false", *args)


def test_a_rule_added_by_the_cli_is_enforced_by_the_next_lint_run(tmp_path, clean_env):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _git(tmp_path, "add", "test_ok.py")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    _sh(tmp_path, sys.executable, str(RULES_CLI), "add", *ADD, "--id", "no-helper")
    (tmp_path / "test_calls.py").write_text(TEST_SRC, encoding="utf-8")
    _git(tmp_path, "add", str(RULES_PATH), "test_calls.py")
    _git(tmp_path, "commit", "-q", "-m", "test that calls the helper")

    done = subprocess.run([sys.executable, str(LINT), "check", "--base", base, "--head", "HEAD",
                           "--json"], cwd=tmp_path, capture_output=True, text=True)
    payload = json.loads(done.stdout)
    hits = [h for h in payload["hits"] if h["source"] == "repo"]
    assert [(h["path"], h["rule"], h["line"]) for h in hits] == [("test_calls.py", "no-helper", 5)]
    assert (payload["repo_rules"], payload["exit"], done.returncode) == (1, 0, 0)
