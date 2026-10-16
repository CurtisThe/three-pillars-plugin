"""Tests for the red-commit gate CLI (design red-commit-hook-refusal 1.2).

Every case drives a real `git init` / `git add` / `git commit` in a throwaway
repo under ``tmp_path`` with the generated ``commit-msg`` hook installed and a
stub test command — the behaviour the plan's Test line specifies, never the
implementation's internals.
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent / "red_commit_gate_cli.py"


# --- helpers --------------------------------------------------------------


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def make_repo(tmp_path):
    repo = Path(tmp_path) / "repo"
    repo.mkdir(parents=True)
    assert git(repo, "init", "-q").returncode == 0
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@test")
    return repo


def hooks_dir(repo):
    out = git(repo, "rev-parse", "--git-path", "hooks").stdout.strip()
    path = Path(out)
    return path if path.is_absolute() else Path(repo) / path


def install_hook(repo, body):
    hook = hooks_dir(repo) / "commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(body, encoding="utf-8")
    hook.chmod(0o755)


def gate_hook(test_cmd):
    """Hook body invoking the CLI's commit-msg subcommand with a test command."""
    return '#!/bin/sh\npython3 "%s" commit-msg "$1" --test-cmd %s\n' % (
        CLI,
        shlex.quote(test_cmd),
    )


def write_stub(tmp_path, name, body):
    stub = Path(tmp_path) / name
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return 'sh "%s"' % stub


def failing_stub(tmp_path, path, name="stub_fail.sh"):
    """Stub that exits 1 naming `path` in a pytest-style FAILED line."""
    return write_stub(
        tmp_path,
        name,
        'echo "FAILED %s::test_a - AssertionError"\nexit 1\n' % path,
    )


def passing_stub(tmp_path, name="stub_pass.sh"):
    return write_stub(tmp_path, name, "echo '1 passed'\nexit 0\n")


def stage(repo, rel, content="def test_a():\n    assert False\n"):
    target = Path(repo) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    assert git(repo, "add", rel).returncode == 0


def cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True
    )


# --- commit-msg subcommand in a real repo ---------------------------------


def test_red_commit_accepted_when_stub_fails_on_staged_test(tmp_path):
    repo = make_repo(tmp_path)
    install_hook(repo, gate_hook(failing_stub(tmp_path, "tests/test_x.py")))
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: red-commit-hook-refusal 1.2 — x")
    assert res.returncode == 0, res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode == 0


def test_red_commit_refused_when_tests_pass(tmp_path):
    repo = make_repo(tmp_path)
    install_hook(repo, gate_hook(passing_stub(tmp_path)))
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode != 0
    assert "red-not-red" in res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode != 0


def test_red_commit_refused_when_failure_is_outside_staged(tmp_path):
    repo = make_repo(tmp_path)
    install_hook(repo, gate_hook(failing_stub(tmp_path, "tests/other.py")))
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode != 0
    assert "tests/other.py" in res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode != 0


def test_red_commit_with_non_test_staging_follows_exit_code(tmp_path):
    repo = make_repo(tmp_path)
    install_hook(repo, gate_hook(failing_stub(tmp_path, "tests/test_x.py")))
    stage(repo, "tests/test_x.py")
    stage(repo, "src/helper.py", "X = 1\n")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode != 0
    assert "tests failed" in res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode != 0


def test_non_red_commit_follows_stub_exit_code(tmp_path):
    repo = make_repo(tmp_path)
    install_hook(repo, gate_hook(failing_stub(tmp_path, "tests/test_x.py")))
    stage(repo, "README.md", "# hi\n")
    res = git(repo, "commit", "-m", "Implement: thing")
    assert res.returncode != 0
    assert "tests failed" in res.stderr

    ok = make_repo(Path(tmp_path) / "ok")
    install_hook(ok, gate_hook(passing_stub(tmp_path, "stub_pass2.sh")))
    stage(ok, "README.md", "# hi\n")
    res2 = git(ok, "commit", "-m", "Implement: thing")
    assert res2.returncode == 0, res2.stderr


def test_no_test_command_anywhere_skips_with_message(tmp_path):
    repo = make_repo(tmp_path)
    install_hook(repo, '#!/bin/sh\npython3 "%s" commit-msg "$1"\n' % CLI)
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode == 0, res.stderr
    assert "red-commit-gate: no test command, skipped" in res.stderr


def test_default_test_command_comes_from_repo_config(tmp_path):
    repo = make_repo(tmp_path)
    config = repo / ".three-pillars" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"test": {"command": failing_stub(tmp_path, "tests/test_x.py")}}),
        encoding="utf-8",
    )
    install_hook(repo, '#!/bin/sh\npython3 "%s" commit-msg "$1"\n' % CLI)
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode == 0, res.stderr


def test_refusal_prints_tail_of_test_output(tmp_path):
    repo = make_repo(tmp_path)
    stub = write_stub(
        tmp_path,
        "stub_tail.sh",
        "echo 'first line'\necho 'FAILED tests/other.py::test_a'\nexit 1\n",
    )
    install_hook(repo, gate_hook(stub))
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode != 0
    assert "first line" in res.stderr
    assert "FAILED tests/other.py::test_a" in res.stderr


# --- snippet subcommand ---------------------------------------------------


def test_snippet_is_one_appendable_line():
    res = cli("snippet", "--test-cmd", "python3 -m pytest")
    assert res.returncode == 0, res.stderr
    lines = res.stdout.strip().splitlines()
    assert len(lines) == 1
    line = lines[0]
    assert str(CLI) in line
    assert "'python3 -m pytest'" in line or '"python3 -m pytest"' in line
    assert "#!" not in line
    assert "exec" not in line


def test_snippet_without_command_exits_2():
    res = cli("snippet")
    assert res.returncode == 2
    assert res.stderr.strip()

    res_empty = cli("snippet", "--test-cmd", "")
    assert res_empty.returncode == 2


def test_snippet_as_last_hook_line_allows_commit_when_cli_missing(tmp_path):
    """The appended line is the hook's last command, so a missing CLI must not
    decide the hook's exit status — every commit would be refused silently."""
    repo = make_repo(tmp_path)
    snippet = cli("snippet", "--test-cmd", passing_stub(tmp_path)).stdout.strip()
    missing = str(Path(tmp_path) / "nope" / "red_commit_gate_cli.py")
    assert str(CLI) in snippet
    line = snippet.replace(str(CLI), missing)
    assert missing in line and str(CLI) not in line
    install_hook(repo, '#!/bin/sh\n%s\n' % line)
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode == 0, res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode == 0
    # Loud, not silent: a commit that skipped the gate says so on stderr.
    assert "red-commit-gate:" in res.stderr, res.stderr
    assert "tests NOT run" in res.stderr, res.stderr


def test_snippet_as_last_hook_line_refuses_when_gate_refuses(tmp_path):
    repo = make_repo(tmp_path)
    snippet = cli(
        "snippet", "--test-cmd", passing_stub(tmp_path, "stub_pass_b.sh")
    ).stdout.strip()
    install_hook(repo, '#!/bin/sh\n%s\n' % snippet)
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert res.returncode != 0
    assert "red-not-red" in res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode != 0


def test_snippet_appended_to_existing_hook_runs_both(tmp_path):
    repo = make_repo(tmp_path)
    marker = tmp_path / "marker"
    snippet = cli("snippet", "--test-cmd", passing_stub(tmp_path)).stdout.strip()
    install_hook(repo, '#!/bin/sh\ntouch "%s"\n%s\n' % (marker, snippet))
    stage(repo, "tests/test_x.py")
    res = git(repo, "commit", "-m", "Red: thing")
    assert marker.exists()
    assert res.returncode != 0
    assert "red-not-red" in res.stderr
    assert git(repo, "rev-parse", "HEAD").returncode != 0
