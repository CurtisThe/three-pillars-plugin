"""test_resolve_root_sh.py — subprocess-driven tests for resolve_root.sh.

Phase 2, Tasks 2.1 and 2.2.

Task 2.1 tests (probes 1–2, sentinel, failure line):
  test_probe1_claude_plugin_root
  test_probe1_skipped_without_sentinel
  test_probe2_skill_dir_grandparent
  test_all_miss_exit1_exact_line

Task 2.2 tests (probes 3–4, mtime tiebreak, readlink -f):
  test_probe3_cache_glob
  test_probe3_newest_mtime_wins
  test_probe1_beats_probe3
  test_symlink_resolves_to_physical_target
  test_probe4_dev_checkout_fallback
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
_RESOLVE_ROOT = _SHARED_DIR / "resolve_root.sh"
_SENTINEL_REL = "skills/_shared/first-run.md"

# Git identity for tmp repos
_GIT_ID_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


def _base_env(home: Path | None = None) -> dict:
    """Return a clean env dict, optionally overriding HOME.

    Strips CLAUDE_PLUGIN_ROOT so probe 1 doesn't accidentally fire,
    and sets HOME to a fake value when requested.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    if home is not None:
        env["HOME"] = str(home)
    return env


def _run(args: list[str], *, env: dict, cwd: str | None = None):
    """Run resolve_root.sh with given args; return CompletedProcess."""
    return subprocess.run(
        ["bash", str(_RESOLVE_ROOT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _mk_sentinel_tree(base: Path) -> None:
    """Create skills/_shared/first-run.md sentinel under base."""
    sentinel = base / _SENTINEL_REL
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("# First-Run Preflight\n")


def _mk_git_repo(path: Path) -> None:
    """Init a minimal git repo with one commit at path."""
    path.mkdir(parents=True, exist_ok=True)
    git_env = {**os.environ, **_GIT_ID_ENV}
    subprocess.run(["git", "init", "-b", "master", "-q", str(path)],
                   check=True, capture_output=True, env=git_env)
    readme = path / "README.md"
    readme.write_text("# fixture\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"],
                   check=True, capture_output=True, env=git_env)
    subprocess.run(
        ["git", "-C", str(path),
         "-c", "user.email=fixture@test", "-c", "user.name=fixture",
         "commit", "-m", "init"],
        check=True, capture_output=True, env=git_env,
    )


# ---------------------------------------------------------------------------
# Task 2.1 tests
# ---------------------------------------------------------------------------

class TestProbe1ClaudePluginRoot:
    """CLAUDE_PLUGIN_ROOT probe with sentinel-bearing tree wins."""

    def test_probe1_claude_plugin_root(self, tmp_path):
        """CLAUDE_PLUGIN_ROOT pointing at a sentinel tree → that path on stdout, exit 0."""
        framework = tmp_path / "framework"
        _mk_sentinel_tree(framework)

        env = _base_env()
        env["CLAUDE_PLUGIN_ROOT"] = str(framework)
        env["HOME"] = str(tmp_path / "empty_home")

        result = _run([], env=env, cwd=str(tmp_path))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        # readlink -f resolves; real path should equal framework (no symlinks here)
        assert result.stdout.strip() == str(framework.resolve())

    def test_probe1_skipped_without_sentinel(self, tmp_path):
        """CLAUDE_PLUGIN_ROOT set but sentinel missing → probe 1 skipped, falls through."""
        no_sentinel = tmp_path / "no_sentinel"
        no_sentinel.mkdir()

        env = _base_env()
        env["CLAUDE_PLUGIN_ROOT"] = str(no_sentinel)
        # No HOME cache entries either — all probes miss → exit 1
        env["HOME"] = str(tmp_path / "empty_home")

        result = _run([], env=env, cwd=str(tmp_path))
        # Must NOT succeed on the sentinel-less root
        assert result.returncode == 1, (
            f"expected exit 1 (no sentinel), but got exit 0; stdout={result.stdout!r}"
        )


class TestProbe2SkillDirGrandparent:
    """--skill-dir <dir> probe: <dir>/../.. qualifies when sentinel present."""

    def test_probe2_skill_dir_grandparent(self, tmp_path):
        """--skill-dir <dir> → <dir>/../.. wins when sentinel-qualified."""
        # Build framework root with sentinel
        framework = tmp_path / "framework"
        _mk_sentinel_tree(framework)
        # skill-dir is inside framework/skills/some-skill/
        skill_dir = framework / "skills" / "some-skill"
        skill_dir.mkdir(parents=True)
        # grandparent of skill_dir is framework/
        # (skill_dir/../.. = framework/skills/.. = framework/)
        # actually skill_dir/../../ = framework/../ so we need skills/_shared level
        # The design says --skill-dir <dir> → <dir>/../.. so:
        # skill_dir = framework/skills/tp-design → skill_dir/../.. = framework/
        # Let's use the right layout
        skill_dir2 = framework / "skills" / "tp-design"
        skill_dir2.mkdir(parents=True)

        env = _base_env()
        env["HOME"] = str(tmp_path / "empty_home")
        # No CLAUDE_PLUGIN_ROOT so probe 1 skips

        result = _run(["--skill-dir", str(skill_dir2)], env=env, cwd=str(tmp_path))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        assert result.stdout.strip() == str(framework.resolve())


class TestAllMissFailure:
    """All probes miss → exit 1 with exact failure line on stderr."""

    def test_all_miss_exit1_exact_line(self, tmp_path):
        """Scrubbed env + empty HOME + non-repo cwd → exit 1, exact stderr line."""
        empty_home = tmp_path / "empty_home"
        empty_home.mkdir()
        non_repo_cwd = tmp_path / "non_repo"
        non_repo_cwd.mkdir()

        env = _base_env(home=empty_home)
        # No CLAUDE_PLUGIN_ROOT, no --skill-dir, no cache entries, non-repo cwd

        result = _run([], env=env, cwd=str(non_repo_cwd))
        assert result.returncode == 1, f"expected exit 1; got {result.returncode}"
        expected_msg = (
            "three-pillars: cannot locate the framework root — "
            "probed $CLAUDE_PLUGIN_ROOT, the skill directory, "
            "~/.claude/plugins/cache/*/three-pillars*, "
            "and the current repo. "
            "Set CLAUDE_PLUGIN_ROOT to the plugin install root and re-run."
        )
        assert result.stderr.strip() == expected_msg, (
            f"stderr mismatch.\nExpected: {expected_msg!r}\nGot:      {result.stderr.strip()!r}"
        )


# ---------------------------------------------------------------------------
# Task 2.2 tests
# ---------------------------------------------------------------------------

class TestProbe3CacheGlob:
    """Plugin-cache glob probe."""

    def test_probe3_cache_glob(self, tmp_path):
        """Fake HOME with sentinel-bearing cache entry → probe 3 resolves it."""
        fake_home = tmp_path / "home"
        # layout: ~/.claude/plugins/cache/local/three-pillars/
        cache_entry = fake_home / ".claude" / "plugins" / "cache" / "local" / "three-pillars"
        _mk_sentinel_tree(cache_entry)

        env = _base_env(home=fake_home)
        # non-repo cwd so probe 4 misses
        non_repo = tmp_path / "consumer"
        non_repo.mkdir()

        result = _run([], env=env, cwd=str(non_repo))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        assert result.stdout.strip() == str(cache_entry.resolve())

    def test_probe3_newest_mtime_wins(self, tmp_path):
        """Two qualifying cache entries → newest mtime wins (explicit mtime set).

        Alphabetically FIRST entry (aaa) has the NEWER mtime so the test is not
        confounded with glob order — a last-glob-wins or >= bug cannot accidentally
        pass here.
        """
        fake_home = tmp_path / "home"

        # Alphabetically first entry — NEWER mtime (wins by timestamp, not glob order)
        new_entry = fake_home / ".claude" / "plugins" / "cache" / "aaa" / "three-pillars"
        _mk_sentinel_tree(new_entry)
        new_sentinel = new_entry / _SENTINEL_REL

        # Alphabetically second entry — OLDER mtime
        old_entry = fake_home / ".claude" / "plugins" / "cache" / "zzz" / "three-pillars"
        _mk_sentinel_tree(old_entry)
        old_sentinel = old_entry / _SENTINEL_REL

        # Explicitly set mtimes using os.utime so we don't depend on wall-clock
        # resolution: new = epoch + 2000, old = epoch + 1000 (clearly different)
        os.utime(str(new_sentinel), (2000, 2000))
        os.utime(str(old_sentinel), (1000, 1000))

        env = _base_env(home=fake_home)
        non_repo = tmp_path / "consumer"
        non_repo.mkdir()

        result = _run([], env=env, cwd=str(non_repo))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        assert result.stdout.strip() == str(new_entry.resolve()), (
            f"Expected newest entry {new_entry!r}, got {result.stdout.strip()!r}"
        )

    def test_probe1_beats_probe3(self, tmp_path):
        """CLAUDE_PLUGIN_ROOT set → beats probe 3 cache entries."""
        fake_home = tmp_path / "home"
        cache_entry = fake_home / ".claude" / "plugins" / "cache" / "local" / "three-pillars"
        _mk_sentinel_tree(cache_entry)

        # CLAUDE_PLUGIN_ROOT points at a different, sentinel-bearing tree
        plugin_root = tmp_path / "plugin_root"
        _mk_sentinel_tree(plugin_root)

        env = _base_env(home=fake_home)
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

        non_repo = tmp_path / "consumer"
        non_repo.mkdir()

        result = _run([], env=env, cwd=str(non_repo))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        assert result.stdout.strip() == str(plugin_root.resolve()), (
            f"Expected probe 1 winner {plugin_root!r}, got {result.stdout.strip()!r}"
        )

    def test_symlink_resolves_to_physical_target(self, tmp_path):
        """A cache entry that is a symlink → stdout is the physical target (readlink -f)."""
        fake_home = tmp_path / "home"

        # Physical target with sentinel
        physical = tmp_path / "real_framework"
        _mk_sentinel_tree(physical)

        # Symlink in cache pointing at physical target
        cache_dir = fake_home / ".claude" / "plugins" / "cache" / "local"
        cache_dir.mkdir(parents=True)
        symlink = cache_dir / "three-pillars"
        symlink.symlink_to(physical)

        env = _base_env(home=fake_home)
        non_repo = tmp_path / "consumer"
        non_repo.mkdir()

        result = _run([], env=env, cwd=str(non_repo))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        resolved = result.stdout.strip()
        physical_real = str(physical.resolve())
        symlink_path = str(symlink.resolve())
        # readlink -f should resolve the symlink to the physical target
        assert resolved == physical_real, (
            f"Expected physical target {physical_real!r}, got {resolved!r}"
        )
        # The resolved path must not BE the symlink path itself
        # (symlink.resolve() also resolves, so they're the same when there are no
        # further levels — we verify we got physical by checking the path doesn't
        # contain the cache subdir name that holds the symlink)
        assert "cache" not in resolved or "real_framework" in resolved, (
            f"Output should point at physical target: {resolved!r}"
        )


class TestProbe4DevCheckoutFallback:
    """Probe 4: git-toplevel of cwd, sentinel-checked."""

    def test_probe4_dev_checkout_fallback(self, tmp_path):
        """Empty HOME + cwd inside a sentinel-bearing git repo → probe 4 wins."""
        empty_home = tmp_path / "empty_home"
        empty_home.mkdir()

        # Create git repo with sentinel at root
        repo = tmp_path / "dev_checkout"
        _mk_git_repo(repo)
        _mk_sentinel_tree(repo)

        # Commit the sentinel so the repo is valid
        git_env = {**os.environ, **_GIT_ID_ENV}
        subprocess.run(["git", "-C", str(repo), "add", "-A"],
                       check=True, capture_output=True, env=git_env)
        subprocess.run(
            ["git", "-C", str(repo),
             "-c", "user.email=fixture@test", "-c", "user.name=fixture",
             "commit", "-m", "add sentinel"],
            check=True, capture_output=True, env=git_env,
        )

        env = _base_env(home=empty_home)
        # cwd = inside the repo

        result = _run([], env=env, cwd=str(repo))
        assert result.returncode == 0, f"expected exit 0; stderr={result.stderr!r}"
        assert result.stdout.strip() == str(repo.resolve())


# ---------------------------------------------------------------------------
# Task 2.3 tests — doc-pin tests for first-run.md preamble section
# ---------------------------------------------------------------------------

_FIRST_RUN_MD = _SHARED_DIR / "first-run.md"


class TestFirstRunMdPreamble:
    """Pin that first-run.md contains the Resolve-root preamble section."""

    def test_preamble_section_exists(self):
        """first-run.md must contain the '## Resolve-root preamble' heading."""
        content = _FIRST_RUN_MD.read_text()
        assert "## Resolve-root preamble" in content, (
            "first-run.md must contain '## Resolve-root preamble' section heading"
        )

    def test_preamble_bootstrap_snippet(self):
        """first-run.md must contain the bootstrap snippet form."""
        content = _FIRST_RUN_MD.read_text()
        # The canonical snippet: TP_ROOT="$(bash <skill-dir>/../../skills/_shared/resolve_root.sh --skill-dir <skill-dir>)"
        assert "resolve_root.sh --skill-dir" in content, (
            "first-run.md §Resolve-root preamble must contain the bootstrap snippet "
            "with resolve_root.sh --skill-dir"
        )
        assert "TP_ROOT=" in content, (
            "first-run.md §Resolve-root preamble must define TP_ROOT"
        )

    def test_loud_skip_line_format(self):
        """first-run.md must contain the loud-skip line format for fail-open helpers."""
        content = _FIRST_RUN_MD.read_text()
        # Required format: three-pillars: skipping <helper> (framework root not found) — fail-open
        assert "framework root not found" in content, (
            "first-run.md must document the loud-skip format containing "
            "'framework root not found'"
        )
        assert "fail-open" in content, (
            "first-run.md must document the fail-open loud-skip line"
        )
