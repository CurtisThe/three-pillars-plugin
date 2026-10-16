"""test_fragility_lint_nonpython.py — the non-Python fixture under `check`.

design: fragile-test-prevention (detailed-design-lint §Scoping, §Shape, exit codes)

A repo whose code is JavaScript: `check --base <base> --json` must list both of the
newly added code files under `skipped`, turn on `judge_dimension_required`, report no
hit for them (the lint has no JavaScript rules) and exit 0 — never crash. Output is
parsed as a JSON document; the fixture repo is throwaway with a local identity.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from fragility_lint import main

PKG = "lib/pkg.js"
TEST = "test/pkg.test.js"


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


def _commit(root: Path, files: dict[str, str], message: str = "c") -> str:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _json(repo: Path, capsys, *args: str) -> tuple[int, dict, str]:
    code = main(["check", *args, "--json"])
    out = capsys.readouterr().out
    return code, json.loads(out), out


def test_a_javascript_repo_is_listed_as_skipped_sets_the_judge_dimension_and_exits_zero(
        repo, capsys):
    base = _commit(repo, {"README.md": "# demo\n"}, "base")
    _commit(repo, {
        PKG: "export function add(a, b) {\n  return a + b;\n}\n",
        TEST: "const { add } = require('../lib/pkg.js');\n"
              "console.log(add(1, 2) === 3 ? 'ok' : 'no');\n",
    }, "js package and its test")
    code, payload, _ = _json(repo, capsys, "--base", base)
    assert code == 0
    assert payload["skipped"] == sorted([PKG, TEST])
    assert payload["judge_dimension_required"] is True
    assert payload["hits"] == []
    assert payload["could_not_evaluate"] == []
