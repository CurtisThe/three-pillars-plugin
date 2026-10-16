#!/usr/bin/env python3
"""test_trust_boundary_range.py — the git-range reader and the CLI of trust_boundary.

design: review-convergence (detailed-design-security.md, Task 3.2)

Reads a real fixture repo (two-dot and three-dot ranges), fails closed on a git error,
and checks the CLI's three exit codes and its two print shapes.
"""
from __future__ import annotations

import json
import subprocess

import pytest

import trust_boundary as tb


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """A throwaway repo with one commit; identity is set inside the fixture only."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "tp fixture")
    _git(root, "config", "user.email", "tp@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "notes.txt").write_text("nothing here\n", encoding="utf-8")
    _git(root, "add", "notes.txt")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _commit(repo, name, text):
    """Commit ``name`` and return the new head sha."""
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _base_sha(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


SURFACE_BODY = 'import subprocess\n\n\ndef go():\n    return subprocess.run(["ls"])\n'
QUIET_BODY = "def go():\n    return 1 + 1\n"


def test_two_dot_range_reports_the_surface(repo):
    base = _base_sha(repo)
    head = _commit(repo, "tool.py", SURFACE_BODY)
    found = tb.surfaces_for_range(repo, base, head)
    assert [e["surface"] for e in found] == ["argv-subprocess"]
    assert found[0]["path"] == "tool.py"
    assert found[0]["removed"] is False
    assert "subprocess.run" in found[0]["text"]


def test_three_dot_range_reports_the_same_surface(repo):
    base = _base_sha(repo)
    head = _commit(repo, "tool.py", SURFACE_BODY)
    assert tb.surfaces_for_range(repo, base, head, three_dot=True) == \
        tb.surfaces_for_range(repo, base, head)


def test_range_uses_the_two_dot_spec_by_default(repo):
    seen = []

    def fake_run_git(argv, cwd):
        seen.append((argv, cwd))
        return ""

    tb.surfaces_for_range(repo, "b1", "h2", run_git=fake_run_git)
    argv, cwd = seen[0]
    assert argv[:3] == ["diff", "--unified=0", "--no-color"]
    assert argv[3] == "b1..h2"
    assert str(cwd) == str(repo)


def test_three_dot_uses_the_three_dot_spec(repo):
    seen = []

    def fake_run_git(argv, cwd):
        seen.append(argv)
        return ""

    tb.surfaces_for_range(repo, "b1", "h2", three_dot=True, run_git=fake_run_git)
    assert seen[0][3] == "b1...h2"


def test_range_with_no_matching_line_is_empty(repo):
    base = _base_sha(repo)
    head = _commit(repo, "quiet.py", QUIET_BODY)
    assert tb.surfaces_for_range(repo, base, head) == []


def test_bad_sha_raises_trust_boundary_error(repo):
    with pytest.raises(tb.TrustBoundaryError) as exc:
        tb.surfaces_for_range(repo, "no-such-rev", "HEAD")
    assert "no-such-rev" in str(exc.value)


def test_run_git_failure_is_wrapped(repo):
    def boom(argv, cwd):
        raise RuntimeError("git exploded")

    with pytest.raises(tb.TrustBoundaryError):
        tb.surfaces_for_range(repo, "b1", "h2", run_git=boom)


def test_run_git_error_is_not_double_wrapped(repo):
    def boom(argv, cwd):
        raise tb.TrustBoundaryError("already an error")

    with pytest.raises(tb.TrustBoundaryError) as exc:
        tb.surfaces_for_range(repo, "b1", "h2", run_git=boom)
    assert str(exc.value) == "already an error"


def test_main_prints_names_and_exits_3(repo, capsys):
    base = _base_sha(repo)
    head = _commit(repo, "tool.py", SURFACE_BODY)
    code = tb.main(["--base", base, "--head", head, "--repo", str(repo)])
    assert code == 3
    assert capsys.readouterr().out.split() == ["argv-subprocess"]


def test_main_json_prints_the_entries(repo, capsys):
    base = _base_sha(repo)
    head = _commit(repo, "tool.py", SURFACE_BODY)
    code = tb.main(["--base", base, "--head", head, "--repo", str(repo), "--json"])
    assert code == 3
    entries = json.loads(capsys.readouterr().out)
    assert [e["surface"] for e in entries] == ["argv-subprocess"]


def test_main_exits_0_when_no_surface(repo, capsys):
    base = _base_sha(repo)
    head = _commit(repo, "quiet.py", QUIET_BODY)
    code = tb.main(["--base", base, "--head", head, "--repo", str(repo)])
    assert code == 0
    assert capsys.readouterr().out.strip() == ""


def test_main_exits_2_on_git_error(repo, capsys):
    code = tb.main(["--base", "no-such-rev", "--head", "HEAD", "--repo", str(repo)])
    assert code == 2
    err = capsys.readouterr().err
    assert err.strip() and "no-such-rev" in err
