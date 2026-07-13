"""Tests for resolve_script.py's thin CLI — plan Task 1.3.

The CLI contract MIRRORS resolve_root.sh's: the resolved absolute path on
stdout + exit 0; the fail-loud diagnostic (naming probed roots) on stderr +
exit 1; a wrong-arity call exits 2 with a usage line. The CLI reads ``$HOME``
for the cache root and ``os.getcwd()`` for cwd — so every case drives it via a
subprocess with an injected ``cwd=`` and ``HOME=`` fixture; the real machine
cache is never touched.

Run with: python -m pytest skills/_shared/test_resolve_script_cli.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
MODULE_PATH = HERE / "resolve_script.py"


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _framework_repo(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    _write(root / "skills" / "_shared" / name, "# dogfood\n")
    return root


def _plain_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    return root


def _run_cli(args, *, cwd: Path, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


def _same(a, b) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def test_cli_resolvable_prints_abs_path_exit_0(tmp_path):
    """Dogfood-resolvable name → abs path on stdout, nothing on stderr, exit 0."""
    name = "github_pr_author.py"
    repo = _framework_repo(tmp_path / "repo", name)
    home = tmp_path / "home"  # empty — no cache; dogfood resolves
    home.mkdir()

    proc = _run_cli([name], cwd=repo, home=home)

    assert proc.returncode == 0
    printed = proc.stdout.strip()
    assert _same(printed, repo / "skills" / "_shared" / name)
    assert Path(printed).is_absolute()
    assert proc.stderr == ""


def test_cli_reads_home_for_cache_root(tmp_path):
    """A consumer cwd resolves through the CLI's $HOME-derived cache root."""
    name = "github_pr_author.py"
    consumer = _plain_repo(tmp_path / "consumer")
    home = tmp_path / "home"
    cache_copy = _write(
        home
        / ".claude"
        / "plugins"
        / "cache"
        / "marketplace"
        / "three-pillars"
        / "1.2.0"
        / "skills"
        / "_shared"
        / name,
        "# cache\n",
    )

    proc = _run_cli([name], cwd=consumer, home=home)

    assert proc.returncode == 0
    assert _same(proc.stdout.strip(), cache_copy)


def test_cli_unresolvable_prints_diagnostic_exit_1(tmp_path):
    """Unresolvable name → diagnostic naming probed roots on stderr, exit 1."""
    name = "nonexistent_module.py"
    consumer = _plain_repo(tmp_path / "consumer")
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_cli([name], cwd=consumer, home=home)

    assert proc.returncode == 1
    assert proc.stdout.strip() == ""
    assert name in proc.stderr
    # The $HOME-derived cache root is named among the probed roots.
    assert str(home / ".claude" / "plugins" / "cache") in proc.stderr


def test_cli_wrong_arity_exits_2_with_usage(tmp_path):
    """No positional name → exit 2 with a usage line on stderr."""
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    proc = _run_cli([], cwd=cwd, home=home)

    assert proc.returncode == 2
    assert "usage" in proc.stderr.lower()
