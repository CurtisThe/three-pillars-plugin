"""CLI-level tests for github_pr_author.py — pr-author-bot-account Task 2.3.

Subprocess-runs the module against a stub `gh` on PATH (the test seam named
in detailed-design §3's CLI section) so these exercise the real argv/exit-code
contract without touching a live gh install.

Run with: pytest skills/_shared/test_github_pr_author_cli.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "github_pr_author.py"

_GH_STUB = """#!/bin/sh
if [ "$1" = "auth" ] && [ "$2" = "token" ]; then
  if [ "${TP_TEST_GH_AUTH_OK:-1}" = "1" ]; then
    echo "gho_stubtoken"
    exit 0
  fi
  echo "error: account not in keyring" >&2
  exit 1
fi
if [ "$1" = "pr" ] && [ "$2" = "create" ]; then
  echo "https://github.com/Acme/widget/pull/1"
  echo "ARGS:$*"
  exit 0
fi
exit 1
"""


def _make_stub_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    gh_path = bin_dir / "gh"
    gh_path.write_text(_GH_STUB, encoding="utf-8")
    gh_path.chmod(0o755)
    return bin_dir


def _env_with_stub(bin_dir: Path, auth_ok: bool = True) -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["TP_TEST_GH_AUTH_OK"] = "1" if auth_ok else "0"
    return env


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _write_config(repo: Path, data: dict) -> None:
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")


def _run_cli(args: list, env: dict, cwd: Path = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )


def _init_git_repo(tmp_path: Path, name: str) -> Path:
    """A real `git init`'d repo — `_default_repo_root` shells out to
    `git rev-parse --show-toplevel`, so tests exercising cwd-relative
    default resolution need an actual git toplevel, not just a directory."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=str(repo), capture_output=True, text=True
    )
    return repo


class TestCliResolve:
    def test_resolve_prints_configured_account(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}},
        )
        env = _env_with_stub(bin_dir)
        result = _run_cli(["resolve", "--context", "manual", "--repo", str(repo)], env)
        assert result.returncode == 0
        assert result.stdout.strip() == "CurtisTheBot"

    def test_resolve_prints_nothing_when_unconfigured(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(["resolve", "--context", "manual", "--repo", str(repo)], env)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_resolve_missing_context_exits_2(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(["resolve", "--repo", str(repo)], env)
        assert result.returncode == 2

    def test_resolve_exits_3_on_corrupt_config(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        cfg_dir = repo / ".three-pillars"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")
        env = _env_with_stub(bin_dir)
        result = _run_cli(["resolve", "--context", "manual", "--repo", str(repo)], env)
        assert result.returncode == 3


class TestCliCreate:
    def test_create_exits_3_on_configured_but_unavailable_account(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}},
        )
        env = _env_with_stub(bin_dir, auth_ok=False)
        result = _run_cli(
            ["create", "--context", "autonomous", "--repo", str(repo), "--", "--base", "master"],
            env,
        )
        assert result.returncode == 3
        assert "CurtisTheBot" in result.stderr
        assert "gh auth login" in result.stderr

    def test_create_exits_3_on_corrupt_config_json(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        cfg_dir = repo / ".three-pillars"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["create", "--context", "manual", "--repo", str(repo), "--", "--base", "master"],
            env,
        )
        assert result.returncode == 3

    def test_create_plain_path_when_config_absent(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["create", "--context", "manual", "--repo", str(repo), "--", "--base", "master"],
            env,
        )
        assert result.returncode == 0
        assert "pull/1" in result.stdout

    def test_create_missing_context_exits_2(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["create", "--repo", str(repo), "--", "--base", "master"], env
        )
        assert result.returncode == 2

    def test_create_exits_3_on_non_utf8_config_no_traceback(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        cfg_dir = repo / ".three-pillars"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_bytes(b"\xff\xfe{")
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["create", "--context", "manual", "--repo", str(repo), "--", "--base", "master"],
            env,
        )
        assert result.returncode == 3
        assert "Traceback" not in result.stderr
        assert "could not be parsed" in result.stderr

    def test_non_string_review_requests_no_crash_no_reviewer(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {
                "schema_version": 1,
                "github": {
                    "pr_author_account": "CurtisTheBot",
                    "used_for": "all-prs",
                    "review_requests": [1, 2, 3],
                },
            },
        )
        env = _env_with_stub(bin_dir, auth_ok=True)
        result = _run_cli(
            ["create", "--context", "manual", "--repo", str(repo), "--", "--base", "master"],
            env,
        )
        assert result.returncode == 0
        assert "Traceback" not in result.stderr
        args_line = next(l for l in result.stdout.splitlines() if l.startswith("ARGS:"))
        assert "--reviewer" not in args_line

    def test_mixed_review_requests_appends_only_valid_strings(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {
                "schema_version": 1,
                "github": {
                    "pr_author_account": "CurtisTheBot",
                    "used_for": "all-prs",
                    "review_requests": ["CurtisThe", 3],
                },
            },
        )
        env = _env_with_stub(bin_dir, auth_ok=True)
        result = _run_cli(
            ["create", "--context", "manual", "--repo", str(repo), "--", "--base", "master"],
            env,
        )
        assert result.returncode == 0
        args_line = next(l for l in result.stdout.splitlines() if l.startswith("ARGS:"))
        assert "--reviewer CurtisThe" in args_line
        assert args_line.count("--reviewer") == 1


class TestCliVerify:
    def test_verify_stamps_verified_at_on_success(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "verified_at": None}},
        )
        env = _env_with_stub(bin_dir, auth_ok=True)
        result = _run_cli(["verify", "--repo", str(repo)], env)
        assert result.returncode == 0
        config_text = (repo / ".three-pillars" / "config.json").read_text(encoding="utf-8")
        assert "gho_stubtoken" not in config_text, "the probed token must never be written to config.json"
        cfg = json.loads(config_text)
        assert cfg["github"]["verified_at"] is not None

    def test_verify_exits_1_on_failure_without_writing(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_repo(tmp_path)
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "verified_at": None}},
        )
        env = _env_with_stub(bin_dir, auth_ok=False)
        result = _run_cli(["verify", "--repo", str(repo)], env)
        assert result.returncode == 1
        cfg = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
        assert cfg["github"]["verified_at"] is None


class TestCliDefaultRepoRootFromSubdir:
    """Invoked with no --repo, the CLI must anchor to the git toplevel, not
    raw cwd — a subdirectory of a configured repo must still resolve the
    configured account instead of silently taking the plain/ambient path."""

    def test_resolve_from_subdir_of_configured_repo_finds_account(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_git_repo(tmp_path, "repo")
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}},
        )
        subdir = repo / "some" / "nested" / "dir"
        subdir.mkdir(parents=True)
        env = _env_with_stub(bin_dir)
        result = _run_cli(["resolve", "--context", "manual"], env, cwd=subdir)
        assert result.returncode == 0
        assert result.stdout.strip() == "CurtisTheBot"

    def test_create_from_subdir_engages_bot_auth(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_git_repo(tmp_path, "repo")
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}},
        )
        subdir = repo / "skills" / "_shared"
        subdir.mkdir(parents=True)
        env = _env_with_stub(bin_dir, auth_ok=True)
        result = _run_cli(
            ["create", "--context", "manual", "--", "--base", "master"], env, cwd=subdir
        )
        assert result.returncode == 0
        assert "Traceback" not in result.stderr
        args_line = next(l for l in result.stdout.splitlines() if l.startswith("ARGS:"))
        assert "--base master" in args_line
        # bot-auth engagement itself is confirmed by the paired test below
        # (auth_ok=False on this identical shape must hard-fail).

    def test_create_from_subdir_fails_loud_when_bot_unavailable(self, tmp_path):
        """The discriminating half of the pair above: if default-repo-root
        resolution silently fell back to cwd (missing config -> plain path),
        this would exit 0 via ambient gh instead of exit 3 with the
        BotAuthUnavailable message — proving the subdir call really did
        load the configured account and probe its token."""
        bin_dir = _make_stub_gh(tmp_path)
        repo = _init_git_repo(tmp_path, "repo")
        _write_config(
            repo,
            {"schema_version": 1, "github": {"pr_author_account": "CurtisTheBot", "used_for": "all-prs"}},
        )
        subdir = repo / "skills" / "_shared"
        subdir.mkdir(parents=True)
        env = _env_with_stub(bin_dir, auth_ok=False)
        result = _run_cli(
            ["create", "--context", "manual", "--", "--base", "master"], env, cwd=subdir
        )
        assert result.returncode == 3
        assert "CurtisTheBot" in result.stderr

    def test_explicit_repo_wins_over_subdir_default(self, tmp_path):
        cwd_repo = _init_git_repo(tmp_path, "cwd-repo")
        _write_config(
            cwd_repo,
            {"schema_version": 1, "github": {"pr_author_account": "WrongAccount", "used_for": "all-prs"}},
        )
        target_repo = _init_repo(tmp_path)  # plain dir, not the cwd's git repo
        _write_config(
            target_repo,
            {"schema_version": 1, "github": {"pr_author_account": "RightAccount", "used_for": "all-prs"}},
        )
        subdir = cwd_repo / "nested"
        subdir.mkdir()
        bin_dir = _make_stub_gh(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["resolve", "--context", "manual", "--repo", str(target_repo)], env, cwd=subdir
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "RightAccount"

    def test_resolve_non_git_cwd_falls_back_to_plain_path(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        plain_dir = tmp_path / "not-a-repo"
        plain_dir.mkdir()
        env = _env_with_stub(bin_dir)
        result = _run_cli(["resolve", "--context", "manual"], env, cwd=plain_dir)
        assert result.returncode == 0
        assert result.stdout.strip() == ""
