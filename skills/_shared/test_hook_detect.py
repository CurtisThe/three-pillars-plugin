"""Tests for hook_detect.detect and its CLI (design red-commit-hook-refusal 1.3).

Each case builds a real `git init` repo under ``tmp_path`` and asserts the
behaviour the Detection contract states: the four hook kinds are found when
their file runs tests, lint-only hooks are not reported, `core.hooksPath` and
linked worktrees resolve, `.sample` files are ignored, a `red_commit_gate`
mention sets `wired`, an empty repo gives `[]`, and an unreadable file is
skipped.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hook_detect import detect  # noqa: E402

MODULE = Path(__file__).resolve().parent / "hook_detect.py"


# --- repo fixtures --------------------------------------------------------


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
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


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def kinds(entries):
    return sorted(e["kind"] for e in entries)


# --- the four kinds -------------------------------------------------------


def test_git_hook_running_pytest_is_reported(tmp_path):
    repo = make_repo(tmp_path)
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\npython3 -m pytest -q\n")
    entries = detect(repo)
    assert kinds(entries) == ["git-hook"]
    assert entries[0]["path"].endswith("pre-commit")
    assert entries[0]["wired"] is False


def test_pre_commit_framework_config_is_reported(tmp_path):
    repo = make_repo(tmp_path)
    write(
        repo / ".pre-commit-config.yaml",
        "repos:\n  - repo: local\n    hooks:\n"
        "      - id: tests\n        name: tests\n        entry: pytest -q\n"
        "        language: system\n",
    )
    entries = detect(repo)
    assert kinds(entries) == ["pre-commit-framework"]
    assert entries[0]["path"].endswith(".pre-commit-config.yaml")


def test_husky_pre_commit_is_reported(tmp_path):
    repo = make_repo(tmp_path)
    write(repo / ".husky" / "pre-commit", "npm test\n")
    entries = detect(repo)
    assert kinds(entries) == ["husky"]


def test_lefthook_yaml_is_reported(tmp_path):
    repo = make_repo(tmp_path)
    write(
        repo / "lefthook.yml",
        "pre-commit:\n  commands:\n    tests:\n      run: go test ./...\n",
    )
    entries = detect(repo)
    assert kinds(entries) == ["lefthook"]


def test_all_four_kinds_together(tmp_path):
    repo = make_repo(tmp_path)
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\npytest\n")
    write(repo / ".pre-commit-config.yaml", "entry: pytest\n")
    write(repo / ".husky" / "pre-commit", "npm test\n")
    write(repo / ".lefthook.yml", "pre-commit:\n  commands:\n    t:\n      run: make test\n")
    assert kinds(detect(repo)) == [
        "git-hook",
        "husky",
        "lefthook",
        "pre-commit-framework",
    ]


# --- lint-only hooks are not test hooks -----------------------------------


def test_lint_only_git_hook_is_not_reported(tmp_path):
    repo = make_repo(tmp_path)
    write(
        hooks_dir(repo) / "pre-commit",
        "#!/bin/sh\nruff check .\nblack --check .\n",
    )
    write(repo / ".pre-commit-config.yaml", "entry: ruff check\n")
    write(repo / ".husky" / "pre-commit", "npx eslint .\n")
    assert detect(repo) == []


# --- hooks path redirection and linked worktrees --------------------------


def test_core_hooks_path_redirects_the_git_hook_lookup(tmp_path):
    repo = make_repo(tmp_path)
    custom = Path(tmp_path) / "my-hooks"
    write(custom / "pre-commit", "#!/bin/sh\npytest -q\n")
    assert git(repo, "config", "core.hooksPath", str(custom)).returncode == 0
    entries = detect(repo)
    assert kinds(entries) == ["git-hook"]
    assert str(custom) in entries[0]["path"]


def test_linked_worktree_finds_the_common_hooks_hook(tmp_path):
    repo = make_repo(tmp_path)
    assert git(repo, "commit", "--allow-empty", "-q", "-m", "seed").returncode == 0
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\npytest -q\n")
    worktree = Path(tmp_path) / "wt"
    assert git(repo, "worktree", "add", "-q", "-b", "wt", str(worktree)).returncode == 0
    entries = detect(worktree)
    assert kinds(entries) == ["git-hook"]
    assert entries[0]["path"].endswith("pre-commit")


# --- samples, wired, empty, unreadable ------------------------------------


def test_sample_hook_is_ignored(tmp_path):
    repo = make_repo(tmp_path)
    write(hooks_dir(repo) / "pre-commit.sample", "#!/bin/sh\npytest\n")
    assert detect(repo) == []


def test_commit_msg_gate_mention_sets_wired_on_every_entry(tmp_path):
    repo = make_repo(tmp_path)
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\npytest\n")
    write(repo / ".husky" / "pre-commit", "npm test\n")
    write(
        hooks_dir(repo) / "commit-msg",
        '#!/bin/sh\npython3 "/x/red_commit_gate_cli.py" commit-msg "$1"\n',
    )
    entries = detect(repo)
    assert kinds(entries) == ["git-hook", "husky"]
    assert all(e["wired"] is True for e in entries)


def test_husky_commit_msg_mention_sets_wired(tmp_path):
    repo = make_repo(tmp_path)
    write(repo / ".husky" / "pre-commit", "npm test\n")
    write(repo / ".husky" / "commit-msg", 'red_commit_gate_cli.py commit-msg "$1"\n')
    entries = detect(repo)
    assert kinds(entries) == ["husky"]
    assert entries[0]["wired"] is True


def test_empty_repo_gives_empty_list(tmp_path):
    repo = make_repo(tmp_path)
    assert detect(repo) == []


def test_unreadable_hook_file_is_skipped(tmp_path):
    repo = make_repo(tmp_path)
    husky = write(repo / ".husky" / "pre-commit", "npm test\n")
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\npytest\n")
    husky.chmod(0o000)
    try:
        entries = detect(repo)
    finally:
        husky.chmod(0o644)
    assert kinds(entries) == ["git-hook"]


# --- the repo's recorded test command counts ------------------------------


def test_recorded_test_command_counts_as_a_test_run(tmp_path):
    repo = make_repo(tmp_path)
    write(
        repo / ".three-pillars" / "config.json",
        json.dumps({"test": {"command": "./ci/run-tests.sh"}}),
    )
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\n./ci/run-tests.sh\n")
    entries = detect(repo)
    assert kinds(entries) == ["git-hook"]


# --- CLI ------------------------------------------------------------------


def test_cli_prints_json_list(tmp_path):
    repo = make_repo(tmp_path)
    write(hooks_dir(repo) / "pre-commit", "#!/bin/sh\npytest -q\n")
    res = subprocess.run(
        [sys.executable, str(MODULE), "--root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    parsed = json.loads(res.stdout)
    assert kinds(parsed) == ["git-hook"]
