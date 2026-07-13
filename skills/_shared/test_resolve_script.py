"""Tests for resolve_script.resolve_shared_script — the FREE _shared resolver.

Covers plan Tasks 1.1 (dogfood wins + fail-loud + mtime-independence),
1.2 (consumer versioned-cache fallback + FREE-in-PRO-cache-miss + determinism),
and 1.3 (thin CLI: stdout path / stderr diagnostic / exit-code contract).

Every case injects ``cwd=`` and ``cache_root=`` fixtures — the real machine
cache / cwd is never touched. Fixture git repos are created with ``git init``
(no commit needed: ``rev-parse --show-toplevel`` works on an empty repo).

Run with: python -m pytest skills/_shared/test_resolve_script.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import resolve_script  # noqa: E402
from resolve_script import (  # noqa: E402
    SharedScriptNotFound,
    resolve_shared_script,
)

MODULE_PATH = HERE / "resolve_script.py"


# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #
def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _make_framework_repo(root: Path, name: str, *, with_script: bool = True) -> Path:
    """A git repo whose toplevel carries the framework sentinel (+ optional <name>)."""
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    if with_script:
        _write(root / "skills" / "_shared" / name, "# dogfood copy\n")
    return root


def _make_plain_repo(root: Path) -> Path:
    """A git repo WITHOUT the framework sentinel (a consumer's own project)."""
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    return root


def _make_cache_versioned(
    cache_root: Path, plugin: str, version: str, name: str
) -> Path:
    """Lay out cache/<mkt>/<plugin>/<version>/skills/_shared/<name>; return it."""
    target = (
        cache_root
        / "marketplace"
        / plugin
        / version
        / "skills"
        / "_shared"
        / name
    )
    return _write(target, f"# {plugin} {version} copy\n")


def _make_cache_versionless(cache_root: Path, plugin: str, name: str) -> Path:
    """Lay out cache/<mkt>/<plugin>/skills/_shared/<name> (local/versionless)."""
    target = cache_root / "marketplace" / plugin / "skills" / "_shared" / name
    return _write(target, f"# {plugin} versionless copy\n")


def _same(a, b) -> bool:
    return Path(a).resolve() == Path(b).resolve()


# --------------------------------------------------------------------------- #
# Task 1.1 — dogfood resolution wins
# --------------------------------------------------------------------------- #
def test_dogfood_repo_copy_wins(tmp_path):
    name = "github_pr_author.py"
    repo = _make_framework_repo(tmp_path / "repo", name)
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()

    result = resolve_shared_script(name, cwd=repo, cache_root=empty_cache)

    assert _same(result, repo / "skills" / "_shared" / name)
    assert result.is_file()


def test_dogfood_wins_even_when_cache_also_has_module(tmp_path):
    """The live repo copy is never lost to a cache that also carries it."""
    name = "github_pr_author.py"
    repo = _make_framework_repo(tmp_path / "repo", name)
    cache_root = tmp_path / "cache"
    _make_cache_versioned(cache_root, "three-pillars", "1.0.0", name)

    result = resolve_shared_script(name, cwd=repo, cache_root=cache_root)

    assert _same(result, repo / "skills" / "_shared" / name)


def test_dogfood_wins_regardless_of_mtime_order(tmp_path):
    """Selection is marker+existence based, never mtime (Behavior 5).

    The dogfood copy is made OLDER than the cache copy; it must still win — a
    newest-mtime heuristic would (wrongly) pick the cache.
    """
    name = "github_pr_author.py"
    repo = _make_framework_repo(tmp_path / "repo", name)
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versioned(cache_root, "three-pillars", "1.0.0", name)

    dogfood_copy = repo / "skills" / "_shared" / name
    # Make dogfood copy strictly OLDER than the cache copy.
    os.utime(dogfood_copy, (1_000, 1_000))
    os.utime(cache_copy, (9_000_000_000, 9_000_000_000))

    result = resolve_shared_script(name, cwd=repo, cache_root=cache_root)

    assert _same(result, dogfood_copy)


# --------------------------------------------------------------------------- #
# Task 1.1 — fail loud
# --------------------------------------------------------------------------- #
def test_missing_everywhere_raises_naming_probed_roots(tmp_path):
    """No dogfood, empty cache → loud SharedScriptNotFound naming probed roots."""
    name = "nonexistent_module.py"
    plain = _make_plain_repo(tmp_path / "consumer")
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(name, cwd=plain, cache_root=empty_cache)

    msg = str(exc.value)
    assert name in msg
    # The cache root that was probed is named in the diagnostic.
    assert str(empty_cache) in msg
    assert str(empty_cache) in exc.value.probed_roots


def test_never_returns_nonexistent_path(tmp_path):
    """A framework repo lacking <name> must not fabricate a repo path."""
    name = "absent_here.py"
    repo = _make_framework_repo(tmp_path / "repo", name, with_script=False)
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()

    with pytest.raises(SharedScriptNotFound):
        resolve_shared_script(name, cwd=repo, cache_root=empty_cache)


def test_no_third_party_imports():
    """The module imports pure stdlib only (no third-party deps)."""
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    stdlib_ok = {"os", "subprocess", "sys", "pathlib", "__future__", "ast"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in stdlib_ok
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in stdlib_ok


# --------------------------------------------------------------------------- #
# Task 1.2 — consumer versioned-cache fallback
# --------------------------------------------------------------------------- #
def test_consumer_repo_falls_back_to_versioned_cache(tmp_path):
    """A plain (non-framework) git repo resolves to the versioned cache copy."""
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    assert _same(result, cache_copy)
    assert result.is_file()


def test_cache_path_descends_into_version_segment(tmp_path):
    """The winner lands on <plugin>/<version>/..., never the parent <plugin>/."""
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    parts = result.parts
    # The <version> segment sits directly under the plugin dir and above skills/.
    assert "1.2.0" in parts
    assert parts.index("1.2.0") == parts.index("skills") - 1
    # Never the bare plugin dir (which has no skills/).
    bare_plugin = cache_root / "marketplace" / "three-pillars" / "skills" / "_shared" / name
    assert not _same(result, bare_plugin)


def test_versionless_cache_layout_supported(tmp_path):
    """Local/versionless layout <plugin>/skills/_shared/<name> also resolves."""
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versionless(cache_root, "three-pillars", name)

    result = resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    assert _same(result, cache_copy)


def test_resolution_outside_any_git_repo_falls_to_cache(tmp_path):
    """cwd outside any git repo (no toplevel) still resolves via the cache."""
    name = "github_pr_author.py"
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(name, cwd=non_repo, cache_root=cache_root)

    assert _same(result, cache_copy)


# --------------------------------------------------------------------------- #
# Task 1.2 — FREE-in-PRO-cache miss avoided (the live #126 case)
# --------------------------------------------------------------------------- #
def test_free_module_skips_pro_cache_that_lacks_it(tmp_path):
    """A FREE-only module absent from the PRO cache resolves to the FREE cache."""
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    # PRO plugin present but LACKS the FREE-only module (only a sibling file).
    _write(
        cache_root
        / "marketplace"
        / "three-pillars-pro"
        / "1.2.0"
        / "skills"
        / "_shared"
        / "some_pro_only.py",
        "# pro\n",
    )
    # FREE plugin HAS it.
    free_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    assert _same(result, free_copy)


# --------------------------------------------------------------------------- #
# Task 1.2 — determinism (lexicographic, not mtime)
# --------------------------------------------------------------------------- #
def test_two_roots_with_module_pick_lexicographic_winner(tmp_path):
    """Both FREE and PRO carry the module → deterministic string-first winner.

    The winner is the lexicographically-first FULL PATH, exactly mirroring
    resolve_root.sh's ``sort | head -n 1`` — so the resolver stays byte-identical
    to what ``$TP_ROOT`` produces today for this single-selection. It must be
    stable across runs and independent of mtime order (Behavior 5).
    """
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    free_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)
    pro_copy = _make_cache_versioned(cache_root, "three-pillars-pro", "1.2.0", name)

    expected = sorted([free_copy, pro_copy], key=str)[0]

    # Winner is stable regardless of mtime order (flip them and re-run).
    os.utime(free_copy, (1_000, 1_000))
    os.utime(pro_copy, (9_000_000_000, 9_000_000_000))
    first = resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    os.utime(free_copy, (9_000_000_000, 9_000_000_000))
    os.utime(pro_copy, (1_000, 1_000))
    second = resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    assert _same(first, expected)
    assert _same(second, expected)
    assert _same(first, second)


# --------------------------------------------------------------------------- #
# Audit A2 — framework-root third topology: sentinel present, script absent
# there → fall THROUGH to the cache (not the repo path, not fail-loud)
# --------------------------------------------------------------------------- #
def test_framework_root_missing_script_falls_through_to_cache(tmp_path):
    """git-toplevel IS a framework checkout but LACKS <name> → cache wins.

    Distinct from test_dogfood_repo_copy_wins (dogfood HIT) and
    test_resolution_outside_any_git_repo_falls_to_cache (no framework root at
    all). Here the sentinel is present but the target script is absent in the
    repo, so resolution must fall THROUGH the dogfood branch to the populated
    cache — never fabricate the repo path, never fail loud while a cache copy
    exists.
    """
    name = "github_pr_author.py"
    repo = _make_framework_repo(tmp_path / "repo", name, with_script=False)
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(name, cwd=repo, cache_root=cache_root)

    assert _same(result, cache_copy)
    assert result.is_file()
    # Never the (nonexistent) dogfood repo path.
    assert not _same(result, repo / "skills" / "_shared" / name)


# --------------------------------------------------------------------------- #
# Audit A3 — populated cache with no match enumerates discovered plugin roots
# --------------------------------------------------------------------------- #
def test_populated_cache_no_match_names_scanned_plugin_roots(tmp_path):
    """Both FREE and PRO caches present but NEITHER carries <name>, no dogfood →
    SharedScriptNotFound whose message ENUMERATES the discovered plugin _shared
    roots (not a vacuous "empty cache" diagnostic)."""
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    # Both plugins populated with a SIBLING module, but not the requested one.
    free_sib = _make_cache_versioned(
        cache_root, "three-pillars", "1.2.0", "some_free_only.py"
    )
    pro_sib = _make_cache_versioned(
        cache_root, "three-pillars-pro", "1.2.0", "some_pro_only.py"
    )
    free_shared = free_sib.parent
    pro_shared = pro_sib.parent

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(name, cwd=consumer, cache_root=cache_root)

    msg = str(exc.value)
    # Both discovered-but-non-matching plugin _shared roots are NAMED.
    assert str(free_shared) in msg, "FREE plugin root must be enumerated"
    assert str(pro_shared) in msg, "PRO plugin root must be enumerated"
    assert str(free_shared) in exc.value.probed_roots
    assert str(pro_shared) in exc.value.probed_roots


# --------------------------------------------------------------------------- #
# Audit A5 — git-missing robustness (FileNotFoundError, not just non-zero exit)
# --------------------------------------------------------------------------- #
def test_missing_git_binary_falls_to_cache(tmp_path, monkeypatch):
    """A missing `git` binary (subprocess raises FileNotFoundError) is treated
    as "no git toplevel" → cache branch, never an unhandled traceback."""
    name = "github_pr_author.py"
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    def _boom(*_a, **_k):
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(resolve_script.subprocess, "run", _boom)

    result = resolve_shared_script(name, cwd=tmp_path, cache_root=cache_root)

    assert _same(result, cache_copy)
