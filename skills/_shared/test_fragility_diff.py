"""test_fragility_diff.py — the added lines of a git diff, read from hunk headers.

design: fragile-test-prevention (detailed-design-lint §Scoping and exit codes)

Behaviour only: a `+c,d` hunk adds lines c..c+d-1, a bare `+c` adds one line, `+c,0`
adds none; `added_lines` gives the added line set per new path in commit
(`base...head`), index (`cached=True`) and worktree modes; a renamed-away path and a
binary file get no lines; a git failure raises `DiffUnavailable`. A round-trip
property renders generated hunk sets as headers and parses them back. Every git
call runs in a throwaway repo with a local identity and signing off.
"""
from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

import pytest

from fragility_diff import DiffUnavailable, added_lines, parse_added


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    """A test run from a git hook inherits GIT_DIR / GIT_INDEX_FILE; drop them all."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=root, capture_output=True, text=True, check=True, encoding="utf-8",
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    return tmp_path


def _write(root: Path, name: str, lines: list[str]) -> None:
    (root / name).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _header_diff(path: str, headers: list[str]) -> str:
    body = "".join(f"{header}\n+x\n" for header in headers)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{body}"


def _runs(numbers: set[int]) -> list[list[int]]:
    """Split a line set into maximal runs of consecutive line numbers."""
    runs: list[list[int]] = []
    for n in sorted(numbers):
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def _render_header(run: list[int]) -> str:
    count = f",{len(run)}" if len(run) > 1 else ""
    return f"@@ -{run[0] - 1},0 +{run[0]}{count} @@"


@pytest.mark.parametrize("header, expected", [
    ("@@ -3,0 +4,3 @@", {4, 5, 6}),
    ("@@ -3 +4 @@", {4}),
    ("@@ -3,2 +4 @@ def f():", {4}),
    ("@@ -3,2 +3,0 @@", set()),
    ("@@ -0,0 +1,2 @@", {1, 2}),
])
def test_hunk_header_grammar(header, expected):
    assert parse_added(_header_diff("a.py", [header])).get("a.py", set()) == expected


def test_added_line_that_looks_like_a_file_header_is_not_a_path():
    text = _header_diff("a.py", ["@@ -1,0 +1,2 @@"]) + "+++ b/evil.py\n"
    assert parse_added(text) == {"a.py": {1, 2}}


def test_round_trip_of_generated_hunk_sets():
    rng = random.Random(20260930)
    for _ in range(200):
        wanted = {n for n in range(1, 60) if rng.random() < 0.4}
        headers = [_render_header(run) for run in _runs(wanted)]
        parsed = parse_added(_header_diff("p.py", headers)).get("p.py", set())
        assert parsed == wanted


def test_commit_mode_gives_added_lines_per_new_path(repo):
    _write(repo, "a.py", ["one", "two", "three"])
    base = _commit(repo, "base")
    _write(repo, "a.py", ["one", "NEW", "two", "three", "TAIL"])
    _write(repo, "b.py", ["x", "y"])
    head = _commit(repo, "head")
    assert added_lines(repo, base, head) == {"a.py": {2, 5}, "b.py": {1, 2}}


def test_commit_mode_diffs_from_the_merge_base(repo):
    _write(repo, "a.py", ["one"])
    _commit(repo, "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "f.py", ["f"])
    head = _commit(repo, "feature")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "m.py", ["m"])
    _commit(repo, "main moves on")
    assert added_lines(repo, "main", head) == {"f.py": {1}}


def test_cached_sees_staged_lines_and_ignores_an_unstaged_edit(repo):
    _write(repo, "a.py", ["one", "two"])
    _commit(repo, "base")
    _write(repo, "a.py", ["one", "STAGED", "two"])
    _git(repo, "add", "a.py")
    _write(repo, "a.py", ["one", "STAGED", "two", "UNSTAGED"])
    assert added_lines(repo, "HEAD", cached=True) == {"a.py": {2}}


def test_worktree_mode_sees_the_working_tree(repo):
    _write(repo, "a.py", ["one", "two"])
    _commit(repo, "base")
    _write(repo, "a.py", ["one", "two", "EDIT"])
    assert added_lines(repo, "HEAD") == {"a.py": {3}}


def test_renamed_away_path_and_binary_file_get_no_lines(repo):
    _write(repo, "old.py", ["one", "two", "three", "four"])
    base = _commit(repo, "base")
    _git(repo, "mv", "old.py", "new.py")
    _write(repo, "new.py", ["one", "two", "three", "four", "five"])
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02\xff\x00binary\x00")
    head = _commit(repo, "rename and add binary")
    result = added_lines(repo, base, head)
    assert "old.py" not in result
    assert "blob.bin" not in result
    assert result == {"new.py": {5}}


def test_a_deleted_file_gets_no_lines_and_hides_nothing_after_it(repo):
    _write(repo, "gone.py", ["one", "two"])
    _write(repo, "z.py", ["z"])
    base = _commit(repo, "base")
    (repo / "gone.py").unlink()
    _write(repo, "z.py", ["z", "added"])
    head = _commit(repo, "delete one, edit another")
    assert added_lines(repo, base, head) == {"z.py": {2}}


def test_paths_with_spaces_and_non_ascii_names_are_reported_verbatim(repo):
    _write(repo, "keep.py", ["k"])
    base = _commit(repo, "base")
    _write(repo, "my file.py", ["a"])
    _write(repo, "naïve.py", ["b"])
    head = _commit(repo, "odd names")
    assert added_lines(repo, base, head) == {"my file.py": {1}, "naïve.py": {1}}


def test_a_bad_ref_raises_diff_unavailable_in_every_mode(repo):
    _write(repo, "a.py", ["one"])
    good = _commit(repo, "base")
    with pytest.raises(DiffUnavailable):
        added_lines(repo, "no-such-ref", good)
    with pytest.raises(DiffUnavailable):
        added_lines(repo, good, "no-such-ref")
    with pytest.raises(DiffUnavailable):
        added_lines(repo, "no-such-ref", cached=True)
    with pytest.raises(DiffUnavailable):
        added_lines(repo, "no-such-ref")


def test_a_directory_that_is_not_a_repo_raises_diff_unavailable(tmp_path):
    with pytest.raises(DiffUnavailable):
        added_lines(tmp_path / "missing", "HEAD")
