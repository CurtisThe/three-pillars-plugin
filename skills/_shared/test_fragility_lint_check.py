"""test_fragility_lint_check.py — `check`: the lint gated on the lines a diff adds.

design: fragile-test-prevention (detailed-design-lint §Scoping and exit codes)

`check` lints the files a diff adds or modifies and keeps only the hits on added lines.
Exit 1 means a gating hit that no waiver silences; exit 2 means the diff or a file could
not be judged; exit 0 otherwise. `--head` reads committed text (never the worktree) and
`--cached` reads the index (never an unstaged edit). Every git call runs in a throwaway
repo with a local identity and signing off; output lines are parsed by their grammar.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from fragility_lint import CheckResult, check_diff, main

GOLDEN = '''\
import hashlib
from pathlib import Path


def test_pin():
    body = Path("hooks/x.sh").read_bytes()
    assert hashlib.sha256(body).hexdigest() == "abc123"{tail}
'''
GOLDEN_LINE = 7
CLEAN = "def test_ok():\n    assert 1 + 1 == 2\n"
TEST = "skills/_shared/test_pin.py"

_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<rule>[a-z0-9-]+) "
                   r"\[(?P<flag>gating|flag)\](?: (?P<rest>.*))?$")


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


def _write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


def _commit(root: Path, files: dict[str, str], message: str = "c") -> str:
    for name, text in files.items():
        _write(root, name, text)
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _hits(out: str) -> list[dict]:
    return [m.groupdict() for m in map(_LINE.match, out.splitlines()) if m]


def _check(capsys, *args: str) -> tuple[int, str]:
    code = main(["check", *args])
    return code, capsys.readouterr().out


def _json(capsys, *args: str) -> dict:
    code, out = _check(capsys, *args, "--json")
    payload = json.loads(out)
    assert payload["exit"] == code
    return payload


@pytest.fixture
def base(repo: Path) -> str:
    return _commit(repo, {"README.md": "# demo\n"}, "base")


# --- what the diff adds gates -------------------------------------------------------

def test_a_commit_adding_a_golden_hash_test_exits_one_and_lists_the_hit(repo, base, capsys):
    _commit(repo, {TEST: GOLDEN.format(tail="")})
    code, out = _check(capsys, "--base", base)
    (hit,) = _hits(out)
    assert code == 1
    assert (hit["path"], int(hit["line"]), hit["rule"], hit["flag"]) == \
        (TEST, GOLDEN_LINE, "golden-hash", "gating")


def test_the_same_pattern_on_an_untouched_line_exits_zero(repo, capsys):
    base = _commit(repo, {TEST: GOLDEN.format(tail="")}, "existing pin")
    _commit(repo, {TEST: GOLDEN.format(tail="") + "\n\n" + CLEAN}, "add a clean test")
    code, out = _check(capsys, "--base", base, "--head", "HEAD")
    assert (code, _hits(out)) == (0, [])


def test_removing_a_file_or_its_lines_never_gates(repo, capsys):
    gone = "skills/_shared/test_gone.py"
    base = _commit(repo, {TEST: GOLDEN.format(tail=""), gone: GOLDEN.format(tail="")}, "pins")
    _git(repo, "rm", "-q", gone)
    _commit(repo, {TEST: CLEAN}, "drop the pins")
    code, out = _check(capsys, "--base", base, "--head", "HEAD")
    assert (code, _hits(out)) == (0, [])


def test_a_waived_hit_on_an_added_line_is_printed_and_does_not_block(repo, base, capsys):
    _commit(repo, {TEST: GOLDEN.format(tail="  # tp-allow-fragile: vendored blob")})
    code, out = _check(capsys, "--base", base)
    (hit,) = _hits(out)
    assert code == 0 and "[waived: vendored blob]" in hit["rest"]


def test_an_empty_waiver_on_an_added_line_still_blocks(repo, base, capsys):
    _commit(repo, {TEST: GOLDEN.format(tail="  # tp-allow-fragile:")})
    code, out = _check(capsys, "--base", base)
    assert code == 1 and "waiver-empty" in _hits(out)[0]["rest"]


def test_a_renamed_file_is_linted_on_the_lines_the_rename_adds(repo, capsys):
    old = "".join(f"def test_ok{i}():\n    assert {i} + 1 == {i + 1}\n\n\n" for i in range(6))
    base = _commit(repo, {"skills/_shared/test_old.py": old}, "before the rename")
    _git(repo, "mv", "skills/_shared/test_old.py", TEST)
    _commit(repo, {TEST: old + GOLDEN.format(tail="")}, "rename and pin")
    code, out = _check(capsys, "--base", base, "--head", "HEAD")
    (hit,) = _hits(out)
    assert code == 1
    assert (hit["path"], int(hit["line"])) == (TEST, len(old.splitlines()) + GOLDEN_LINE)


def test_check_from_a_subdirectory_lints_the_repo_files(repo, base, capsys, monkeypatch):
    _commit(repo, {TEST: GOLDEN.format(tail="")})
    monkeypatch.chdir(repo / "skills")
    for extra in ([], ["--head", "HEAD"]):
        code, out = _check(capsys, "--base", base, *extra)
        assert (code, [h["path"] for h in _hits(out)]) == (1, [TEST])


# --- the text a verdict is about -------------------------------------------------------

@pytest.mark.parametrize("committed, dirty, expected", [
    (GOLDEN.format(tail=""), CLEAN, 1),
    (CLEAN, GOLDEN.format(tail=""), 0),
])
def test_head_reads_the_committed_text_so_a_dirty_worktree_never_changes_the_verdict(
        repo, base, capsys, committed, dirty, expected):
    _commit(repo, {TEST: committed})
    _write(repo, TEST, dirty)
    code, _ = _check(capsys, "--base", base, "--head", "HEAD")
    assert code == expected


def test_worktree_mode_reads_the_working_tree(repo, base, capsys):
    _commit(repo, {TEST: CLEAN})
    _write(repo, TEST, GOLDEN.format(tail=""))
    code, out = _check(capsys, "--base", base)
    assert (code, [h["rule"] for h in _hits(out)]) == (1, ["golden-hash"])


def test_cached_ignores_an_unstaged_fragile_edit(repo, base, capsys):
    _write(repo, TEST, CLEAN)
    _git(repo, "add", TEST)
    _write(repo, TEST, GOLDEN.format(tail=""))
    code, out = _check(capsys, "--base", base, "--cached")
    assert (code, _hits(out)) == (0, [])


def test_cached_lints_the_staged_text_even_when_the_worktree_is_clean(repo, base, capsys):
    _write(repo, TEST, GOLDEN.format(tail=""))
    _git(repo, "add", TEST)
    _write(repo, TEST, CLEAN)
    code, out = _check(capsys, "--base", base, "--cached")
    assert (code, [h["rule"] for h in _hits(out)]) == (1, ["golden-hash"])


# --- could not evaluate ------------------------------------------------------------------

def test_a_failing_diff_exits_two_and_says_so(repo, base, capsys):
    code, out = _check(capsys, "--base", "no-such-ref")
    assert code == 2
    assert [line for line in out.splitlines() if line.startswith("could-not-evaluate:")]


def test_check_outside_a_repository_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert _check(capsys, "--base", "HEAD")[0] == 2


def test_an_unparseable_added_python_file_exits_two_and_names_it(repo, base, capsys):
    _commit(repo, {"skills/_shared/test_broken.py": "def (:\n"})
    code, out = _check(capsys, "--base", base)
    assert code == 2
    assert "test_broken.py" in out and "could-not-evaluate:" in out


@pytest.mark.parametrize("mode", [["--head", "HEAD"], ["--cached"], []])
def test_a_symlinked_py_file_is_not_source_and_never_blocks_the_diff(repo, base, capsys, mode):
    _write(repo, "util.py", "x = 1\n")
    (repo / "pkg").mkdir()
    os.symlink("../util.py", repo / "pkg" / "util.py")
    _git(repo, "add", "util.py", "pkg/util.py")
    _git(repo, "commit", "-q", "-m", "add a symlink to valid python")
    payload = _json(capsys, "--base", base, *mode)
    assert (payload["exit"], payload["could_not_evaluate"]) == (0, [])


def test_a_gating_hit_still_exits_one_beside_an_unparseable_file(repo, base, capsys):
    _commit(repo, {TEST: GOLDEN.format(tail=""), "skills/_shared/test_broken.py": "def (:\n"})
    payload = _json(capsys, "--base", base)
    assert payload["exit"] == 1 and len(payload["could_not_evaluate"]) == 1


def test_head_and_cached_together_are_refused(repo, base):
    with pytest.raises(SystemExit) as raised:
        main(["check", "--base", base, "--head", "HEAD", "--cached"])
    assert raised.value.code == 2


# --- non-python files and the JSON shape -----------------------------------------------------

def test_a_code_file_is_listed_as_skipped_and_marks_the_judge_dimension(repo, base, capsys):
    _commit(repo, {"web/pin.js": "expect(hash).toBe('abc');\n", "docs/notes.md": "# n\n"})
    payload = _json(capsys, "--base", base)
    assert payload["exit"] == 0 and payload["hits"] == []
    assert payload["skipped"] == ["web/pin.js"]
    assert payload["judge_dimension_required"] is True
    _, out = _check(capsys, "--base", base)
    assert "skipped (non-python): web/pin.js" in out.splitlines()


def test_json_hits_carry_the_generic_source(repo, base, capsys):
    _commit(repo, {TEST: GOLDEN.format(tail="")})
    payload = _json(capsys, "--base", base)
    (hit,) = payload["hits"]
    assert hit == {"path": TEST, "line": GOLDEN_LINE, "rule": "golden-hash", "gating": True,
                   "waiver": None, "source": "generic"}
    assert payload["judge_dimension_required"] is False


# --- check_diff, in process --------------------------------------------------------------------

def test_check_diff_returns_a_check_result_whose_exit_equals_mains(repo, base, capsys):
    _commit(repo, {TEST: GOLDEN.format(tail="")})
    result = check_diff(repo, base)
    assert isinstance(result, CheckResult)
    assert result.exit == 1 and result.could_not_evaluate == [] and result.skipped == []
    assert [(h.path, h.line, h.rule_id, h.gating, h.waived) for h in result.hits] == \
        [(TEST, GOLDEN_LINE, "golden-hash", True, False)]
    assert result.judge_dimension_required is False
    assert result.exit == _check(capsys, "--base", base)[0]


@pytest.mark.parametrize("ref, expected", [("HEAD", 0), ("no-such-ref", 2)])
def test_check_diff_exit_equals_mains_for_clean_and_failing_diffs(repo, base, capsys, ref,
                                                                  expected):
    _commit(repo, {TEST: CLEAN})
    result = check_diff(repo, ref, "HEAD")
    assert result.exit == expected == _check(capsys, "--base", ref, "--head", "HEAD")[0]
    assert (result.could_not_evaluate != []) is (expected == 2)


def test_check_diff_accepts_cached_as_a_keyword(repo, base):
    _write(repo, TEST, GOLDEN.format(tail=""))
    _git(repo, "add", TEST)
    assert check_diff(repo, base, cached=True).exit == 1
