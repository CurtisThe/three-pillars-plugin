"""test_foreign_repo_fixture.py — self-tests for the foreign-consumer-repo fixture.

Covers `skills/_shared/fixtures/foreign_repo.py` (plugin-mode-parity Phase 2):
  TestConsumerRepo — git repo shape, committed config carrying
                     github.pr_author_account, with_config=False variant
  TestCacheRoot    — fake plugin cache populated from `git archive HEAD`
                     (committed content only, exactly one cache entry)
  TestGhShim       — PATH shim intercepts gh, canned JSON per subcommand,
                     every argv line appended to bin_dir/gh-calls.log
  TestEnvFor       — env assembly: HOME, PATH prepend, CLAUDE_PLUGIN_ROOT
                     set (plugin_mode=True) / stripped (plugin_mode=False)

The fixture is standalone (does NOT import base_sync_repo); only the gh-shim
*pattern* from fixtures/embedded_framework.py is reused. Stdlib + pytest only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _SHARED_DIR / "fixtures"
for _p in (_SHARED_DIR, _FIXTURES_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from foreign_repo import build_foreign_repo, env_for  # noqa: E402

# The framework checkout this test runs from (skills/_shared/ -> repo root).
FRAMEWORK_SRC = _SHARED_DIR.parent.parent


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def _run_gh(fx, *args: str, extra_env: dict | None = None):
    """Invoke the fixture's gh shim directly (never the real gh)."""
    env = env_for(fx, plugin_mode=True)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(fx.bin_dir / "gh"), *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    """Configured fixture: committed config carries github.pr_author_account."""
    return build_foreign_repo(
        tmp_path_factory.mktemp("foreign"),
        framework_src=FRAMEWORK_SRC,
        pr_author_account="parity-bot",
    )


@pytest.fixture(scope="module")
def fx_noconfig(tmp_path_factory):
    """with_config=False variant: no .three-pillars/config.json at all."""
    return build_foreign_repo(
        tmp_path_factory.mktemp("foreign-nc"),
        framework_src=FRAMEWORK_SRC,
        with_config=False,
    )


class TestConsumerRepo:
    def test_root_is_git_repo_with_one_commit(self, fx):
        count = _git(fx.root, "rev-list", "--count", "HEAD").strip()
        assert count == "1", f"expected exactly one commit, got {count}"

    def test_config_committed_with_pr_author_account(self, fx):
        # Read from HEAD, not the working tree: the config must be COMMITTED
        # (land/gate paths read committed config, not loose files).
        raw = _git(fx.root, "show", "HEAD:.three-pillars/config.json")
        cfg = json.loads(raw)
        assert cfg["github"]["pr_author_account"] == "parity-bot"

    def test_working_tree_clean(self, fx):
        porcelain = _git(fx.root, "status", "--porcelain")
        assert porcelain == "", f"fixture repo dirty after build:\n{porcelain}"

    def test_no_config_variant_omits_config(self, fx_noconfig):
        assert not (fx_noconfig.root / ".three-pillars" / "config.json").exists()
        count = _git(fx_noconfig.root, "rev-list", "--count", "HEAD").strip()
        assert count == "1"


class TestCacheRoot:
    def test_cache_under_fake_home_plugins_cache(self, fx):
        assert fx.cache_root.is_dir()
        rel = fx.cache_root.relative_to(fx.home)
        assert str(rel).startswith(".claude/plugins/cache/")

    def test_exactly_one_cache_entry(self, fx):
        # Probe-3's multi-match path must never be exercised by this fixture:
        # exactly ONE versioned install (cache/<mkt>/<plugin>/<version>/) whose
        # sentinel resolves. Descend all three segments — the sentinel lives
        # under <version>, mirroring the real Claude Code layout.
        cache = fx.home / ".claude" / "plugins" / "cache"
        entries = [
            version
            for marketplace in cache.iterdir() if marketplace.is_dir()
            for plugin in marketplace.iterdir() if plugin.is_dir()
            for version in plugin.iterdir() if version.is_dir()
        ]
        assert entries == [fx.cache_root]
        assert (fx.cache_root / "skills" / "_shared" / "first-run.md").is_file()

    def test_cache_is_committed_content_only(self, fx):
        # git archive HEAD: tracked content present, no .git dir leaks in.
        assert (fx.cache_root / "skills" / "_shared" / "first-run.md").is_file(), (
            "resolve_root.sh sentinel missing from the fake cache"
        )
        assert (fx.cache_root / "skills" / "_shared" / "resolve_root.sh").is_file()
        assert not (fx.cache_root / ".git").exists(), (
            "cache must mirror a released install (committed content only)"
        )


class TestGhShim:
    def test_shim_exists_and_executable(self, fx):
        shim = fx.bin_dir / "gh"
        assert shim.is_file()
        assert os.access(shim, os.X_OK), "gh shim must be executable"

    def test_auth_status_canned_json(self, fx):
        result = _run_gh(fx, "auth", "status")
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["login"] == "fixture-bot"

    def test_api_user_canned_json(self, fx):
        result = _run_gh(fx, "api", "user")
        assert result.returncode == 0
        assert json.loads(result.stdout)["login"] == "fixture-bot"

    def test_pr_view_canned_json(self, fx):
        result = _run_gh(fx, "pr", "view", "--json", "state")
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["state"] == "OPEN"

    def test_pr_create_prints_url(self, fx):
        result = _run_gh(fx, "pr", "create", "--title", "t", "--body", "b")
        assert result.returncode == 0
        assert result.stdout.strip().startswith("https://github.com/")

    def test_auth_token_returns_token(self, fx):
        # github_pr_author.bot_token needs a non-empty stdout from
        # `gh auth token --user <account>` — the shim must satisfy it offline.
        result = _run_gh(fx, "auth", "token", "--user", "parity-bot")
        assert result.returncode == 0
        assert result.stdout.strip() != ""

    def test_pr_create_logs_gh_token_marker(self, fx):
        # The A2 smoke assertion proves the bot token (not ambient auth)
        # reached the create call via this marker.
        _run_gh(fx, "pr", "create", "--title", "m", extra_env={"GH_TOKEN": "x"})
        log = (fx.bin_dir / "gh-calls.log").read_text(encoding="utf-8")
        assert any(
            "pr create" in line and "[GH_TOKEN=set]" in line
            for line in log.splitlines()
        )

    def test_every_invocation_logged(self, fx):
        # Self-contained: drive each subcommand shape ourselves so this assertion
        # never depends on sibling tests (or their worker placement under xdist
        # `-n auto`, which distributes a module's items across workers) having
        # populated the module-shared gh-calls.log first. The shim appends every
        # argv to gh-calls.log; here we prove it does so for each subcommand shape.
        for argv in (
            ("auth", "status"),
            ("api", "user"),
            ("pr", "view", "--json", "state"),
            ("pr", "create", "--title", "t", "--body", "b"),
        ):
            _run_gh(fx, *argv)
        log = (fx.bin_dir / "gh-calls.log").read_text(encoding="utf-8")
        for expected in ("auth status", "api user", "pr view", "pr create"):
            assert any(line.startswith(expected) for line in log.splitlines()), (
                f"gh-calls.log missing a {expected!r} line:\n{log}"
            )

    def test_unknown_subcommand_fails_loud_and_is_logged(self, fx):
        result = _run_gh(fx, "frobnicate")
        assert result.returncode == 1, "unhandled gh subcommand must fail loud"
        log = (fx.bin_dir / "gh-calls.log").read_text(encoding="utf-8")
        assert any(line.startswith("frobnicate") for line in log.splitlines())


class TestEnvFor:
    def test_plugin_mode_sets_claude_plugin_root(self, fx):
        env = env_for(fx, plugin_mode=True)
        assert env["CLAUDE_PLUGIN_ROOT"] == str(fx.cache_root)

    def test_plugin_mode_sets_home_and_prepends_path(self, fx):
        env = env_for(fx, plugin_mode=True)
        assert env["HOME"] == str(fx.home)
        assert env["PATH"].startswith(str(fx.bin_dir) + os.pathsep)

    def test_non_plugin_mode_strips_claude_plugin_root(self, fx, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/somewhere/ambient")
        env = env_for(fx, plugin_mode=False)
        assert "CLAUDE_PLUGIN_ROOT" not in env
        # HOME/PATH shaping still applies in cache-mode (probe-3 lane).
        assert env["HOME"] == str(fx.home)
        assert env["PATH"].startswith(str(fx.bin_dir) + os.pathsep)

    def test_env_for_does_not_mutate_os_environ(self, fx, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/somewhere/ambient")
        before = dict(os.environ)
        env_for(fx, plugin_mode=False)
        env_for(fx, plugin_mode=True)
        assert dict(os.environ) == before
