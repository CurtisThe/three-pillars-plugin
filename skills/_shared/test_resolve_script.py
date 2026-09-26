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


def _cache_install(cache_root: Path, *parts: str) -> Path:
    """A REAL cache install root: <cache>/<mkt>/<...>/ carrying the sentinel.

    A cache entry is sentinel-qualified exactly like probes 1-4 (and exactly
    like resolve_root.sh's `_check_cache_entry`), so a fixture that lays down
    only `<name>` is not a cache install — it is a bare directory that happens
    to hold a file, and the resolver must refuse to execute it. Every cache
    fixture in this suite goes through here so none of them can drift back into
    testing the unqualified shape.
    """
    root = cache_root.joinpath("marketplace", *parts)
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    return root


def _make_cache_versioned(
    cache_root: Path, plugin: str, version: str, name: str
) -> Path:
    """Lay out cache/<mkt>/<plugin>/<version>/skills/_shared/<name>; return it."""
    root = _cache_install(cache_root, plugin, version)
    return _write(root / "skills" / "_shared" / name, f"# {plugin} {version} copy\n")


def _make_cache_versionless(cache_root: Path, plugin: str, name: str) -> Path:
    """Lay out cache/<mkt>/<plugin>/skills/_shared/<name> (local/versionless)."""
    root = _cache_install(cache_root, plugin)
    return _write(root / "skills" / "_shared" / name, f"# {plugin} versionless copy\n")


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

    result = resolve_shared_script(
        name, cwd=repo, cache_root=empty_cache, self_root=None, plugin_root=None
    )

    assert _same(result, repo / "skills" / "_shared" / name)
    assert result.is_file()


def test_dogfood_wins_even_when_cache_also_has_module(tmp_path):
    """The live repo copy is never lost to a cache that also carries it."""
    name = "github_pr_author.py"
    repo = _make_framework_repo(tmp_path / "repo", name)
    cache_root = tmp_path / "cache"
    _make_cache_versioned(cache_root, "three-pillars", "1.0.0", name)

    result = resolve_shared_script(
        name, cwd=repo, cache_root=cache_root, self_root=None, plugin_root=None
    )

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

    result = resolve_shared_script(
        name, cwd=repo, cache_root=cache_root, self_root=None, plugin_root=None
    )

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
        resolve_shared_script(
            name, cwd=plain, cache_root=empty_cache, self_root=None, plugin_root=None
        )

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
        resolve_shared_script(
            name, cwd=repo, cache_root=empty_cache, self_root=None, plugin_root=None
        )


def test_no_third_party_imports():
    """The module imports pure stdlib only (no third-party deps)."""
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    stdlib_ok = {"os", "stat", "subprocess", "sys", "pathlib", "__future__", "ast"}
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

    result = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

    assert _same(result, cache_copy)
    assert result.is_file()


def test_cache_path_descends_into_version_segment(tmp_path):
    """The winner lands on <plugin>/<version>/..., never the parent <plugin>/."""
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

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

    result = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

    assert _same(result, cache_copy)


def test_resolution_outside_any_git_repo_falls_to_cache(tmp_path):
    """cwd outside any git repo (no toplevel) still resolves via the cache."""
    name = "github_pr_author.py"
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    cache_root = tmp_path / "cache"
    cache_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(
        name, cwd=non_repo, cache_root=cache_root, self_root=None, plugin_root=None
    )

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
    pro = _cache_install(cache_root, "three-pillars-pro", "1.2.0")
    _write(pro / "skills" / "_shared" / "some_pro_only.py", "# pro\n")
    # FREE plugin HAS it.
    free_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)

    result = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

    assert _same(result, free_copy)


# --------------------------------------------------------------------------- #
# Task 1.2 — determinism (lexicographic, not mtime)
# --------------------------------------------------------------------------- #
def test_two_roots_with_module_pick_lexicographic_root_winner(tmp_path):
    """Both FREE and PRO carry the module → deterministic string-first winner.

    The winner is the lexicographically-first ROOT, mirroring resolve_root.sh's
    ``sort | head -n 1`` over its probe-3 matches — NOT the first full script
    path, a different ordering whenever one root prefixes another (pinned by
    the next case). These two roots are versioned, so neither prefixes the
    other and both orderings agree: PRO wins on bytes, ``-`` (0x2D) sorting
    below ``/`` (0x2F). ``expected`` is hard-coded, and the winner is stable
    across runs and independent of mtime order (Behavior 5).
    """
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    free_copy = _make_cache_versioned(cache_root, "three-pillars", "1.2.0", name)
    pro_copy = _make_cache_versioned(cache_root, "three-pillars-pro", "1.2.0", name)

    expected = pro_copy

    # Winner is stable regardless of mtime order (flip them and re-run).
    os.utime(free_copy, (1_000, 1_000))
    os.utime(pro_copy, (9_000_000_000, 9_000_000_000))
    first = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

    os.utime(free_copy, (9_000_000_000, 9_000_000_000))
    os.utime(pro_copy, (1_000, 1_000))
    second = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

    assert _same(first, expected)
    assert _same(second, expected)
    assert _same(first, second)
    assert not _same(first, free_copy)


def test_cache_tie_break_sorts_roots_so_free_beats_pro_on_a_prefix_pair(tmp_path):
    """Unversioned ``three-pillars`` vs ``three-pillars-pro``: FREE wins.

    ``three-pillars`` prefixes ``three-pillars-pro``; sorting the full script
    PATHS would put PRO first (``-`` < ``/``), resolving a FREE module out of the
    PRO cache. The winner is the first ROOT, as in ``resolve_root.sh``.
    """
    name = "github_pr_author.py"
    cache_root = tmp_path / "cache"
    free_copy = _make_cache_versionless(cache_root, "three-pillars", name)
    pro_copy = _make_cache_versionless(cache_root, "three-pillars-pro", name)
    assert sorted([free_copy, pro_copy], key=str)[0] == pro_copy  # discriminating
    got = resolve_shared_script(
        name, cwd=None, cache_root=cache_root, self_root=None, plugin_root=None
    )
    assert _same(got, free_copy)


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

    result = resolve_shared_script(
        name, cwd=repo, cache_root=cache_root, self_root=None, plugin_root=None
    )

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
        resolve_shared_script(
            name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
        )

    msg = str(exc.value)
    # Both discovered-but-non-matching plugin _shared roots are NAMED.
    assert str(free_shared) in msg, "FREE plugin root must be enumerated"
    assert str(pro_shared) in msg, "PRO plugin root must be enumerated"
    assert str(free_shared) in exc.value.probed_roots
    assert str(pro_shared) in exc.value.probed_roots


# --------------------------------------------------------------------------- #
# PR #144 S2 — a cache candidate is SENTINEL-QUALIFIED, like every other probe
# --------------------------------------------------------------------------- #
def test_cache_entry_without_sentinel_is_skipped(tmp_path):
    """A `three-pillars*` cache dir holding <name> but NO sentinel never wins.

    Probes 1-4 all gate on `_is_framework_root`; before this, probe 5 qualified
    a winner on nothing but the file existing. That made the cache the one root
    where a directory REJECTED at probe 2 for a missing sentinel would win —
    and the returned path is fed straight to `python3` by all three call sites.
    `resolve_root.sh` has always required the sentinel here (`_check_cache_entry`
    calls `_has_sentinel`), so this is the two resolvers agreeing again.
    """
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    # Correctly NAMED and correctly SHAPED, carrying <name> — but not a
    # framework root, because the sentinel is absent.
    impostor = cache_root / "marketplace" / "three-pillars" / "1.2.0"
    _write(impostor / "skills" / "_shared" / name, "# unqualified\n")

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(
            name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
        )

    # Skipped as a WINNER, but still enumerated as a miss — never silently dropped.
    shared = str(impostor / "skills" / "_shared")
    assert shared in exc.value.probed_roots
    assert ("cache", shared, "miss") in exc.value.probe_report


def test_cache_sentinel_is_the_only_difference(tmp_path):
    """Positive twin: the SAME tree plus the sentinel resolves.

    Pins that the skip above is caused by the missing sentinel and nothing else
    — layout, glob and name are identical across the two cases.
    """
    name = "github_pr_author.py"
    consumer = _make_plain_repo(tmp_path / "consumer")
    cache_root = tmp_path / "cache"
    install = cache_root / "marketplace" / "three-pillars" / "1.2.0"
    copy = _write(install / "skills" / "_shared" / name, "# qualified\n")
    _write(install / "skills" / "_shared" / "first-run.md", "# sentinel\n")

    result = resolve_shared_script(
        name, cwd=consumer, cache_root=cache_root, self_root=None, plugin_root=None
    )

    assert _same(result, copy)


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

    result = resolve_shared_script(
        name, cwd=tmp_path, cache_root=cache_root, self_root=None, plugin_root=None
    )

    assert _same(result, cache_copy)
