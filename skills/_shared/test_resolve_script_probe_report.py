"""Tests for resolve_script's fail-loud PROBE REPORT (design: resolve-script-override-roots).

Phase 1 scope — no new roots yet. Two properties are pinned here:

* **Behavior 3 — an unreadable directory is TAGGED, never a traceback.** A
  ``chmod 0o000`` dir anywhere in the cache walk must surface as a
  ``SharedScriptNotFound`` whose message names that dir with ``[cache:
  unreadable]``. Parametrized over all FOUR descent levels (cache root,
  marketplace, plugin, version) because the walk uses different primitives at
  each level and each one has to route through the same guard.
* **Back-compat — ``probed_roots`` stays ``list[str]``.** ``probe_report`` is
  additive; the #129 public attribute is unchanged in type and content, and the
  audit-A3 "populated but non-matching cache enumerates its scanned roots"
  guarantee still holds.

No mocks: real ``tmp_path`` trees, real ``chmod``, real ``git init``. The whole
module is skipped as root, where the permission bits are advisory.

Run with: python -m pytest skills/_shared/test_resolve_script_probe_report.py -q
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

from resolve_script import (  # noqa: E402
    SharedScriptNotFound,
    resolve_shared_script,
)

NAME = "github_pr_author.py"

pytestmark = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses mode bits — chmod 0o000 is not unreadable for uid 0",
)


# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #
def _resolve(name, **kwargs):
    """Call ``resolve_shared_script`` with every AMBIENT root opted out.

    All THREE ambient roots — the process cwd, ``CLAUDE_PLUGIN_ROOT`` and the
    resolver's own install, and on a dogfood checkout each of them really does
    carry ``github_pr_author.py`` — derive from the real machine when the
    keyword is omitted. Every case in this module is about the CACHE walk, so
    all three are withheld here: without the opt-out these tests would resolve
    the live repo copy and pass for the wrong reason on any dev checkout.

    ``cwd`` is DEFAULTED rather than required, and the default is the
    withholding one: ``None`` stops probe 1 running at all (PR #144 R6 — until
    then ``None`` meant "derive the process cwd", so this helper's promise above
    was false and the next case added here would have inherited a live root).
    Pass ``cwd=<dir>`` to name a directory to probe FROM; every case does today,
    which is why the default is pinned by a test of its own rather than by use.

    The opt-out is spelled with literal keywords rather than derived from
    ``inspect.signature`` so ``test_resolve_script_hermeticity.py``'s structural
    sweep can SEE it in the source text.
    """
    return resolve_shared_script(
        name,
        cwd=kwargs.pop("cwd", None),
        plugin_root=None,
        self_root=None,
        **kwargs,
    )


def _plain_repo(root: Path) -> Path:
    """A git repo WITHOUT the framework sentinel — the toplevel probe misses."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(root)], check=True, capture_output=True
    )
    return root


def _populate(cache_root: Path, marketplace: str, sibling: str) -> Path:
    """cache/<mkt>/three-pillars/1.2.0/skills/_shared/<sibling>; return its dir.

    Carries the sentinel, so these installs are REAL ones that simply lack
    ``NAME`` — the miss under test is "the module is not here", not "this was
    never a framework root".
    """
    shared = (
        cache_root / marketplace / "three-pillars" / "1.2.0" / "skills" / "_shared"
    )
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "first-run.md").write_text("# sentinel\n")
    (shared / sibling).write_text(f"# {marketplace} sibling\n")
    return shared


@pytest.fixture
def cache_tree(tmp_path):
    """Two independent marketplace branches, NEITHER carrying ``NAME``.

    ``mkt-a`` is the branch a case makes unreadable; ``mkt-b`` is the readable
    control that proves the walk keeps going.
    """
    cache_root = tmp_path / "cache"
    a_shared = _populate(cache_root, "mkt-a", "some_free_only.py")
    b_shared = _populate(cache_root, "mkt-b", "some_pro_only.py")
    return {
        "root": cache_root,
        "a_shared": a_shared,
        "b_shared": b_shared,
        "cwd": _plain_repo(tmp_path / "consumer"),
    }


#: The TWO permission shapes that wall off a directory, and they are NOT the
#: same failure. ``0o000`` kills the LISTING: ``iterdir()`` raises, the walk
#: reports blind, and the guard around the listing catches it. ``0o444`` is
#: read-but-not-SEARCHABLE: ``iterdir()`` SUCCEEDS (so the listing guard reports
#: NOT blind and the walk keeps going) and the very next child ``stat()`` raises
#: ``EACCES`` instead — straight out of the bare ``Path.is_dir()`` filters that
#: sit BETWEEN the guarded levels. A suite that only ever chmods ``0o000``
#: exercises one of the two and calls the level covered.
_MODES = {"no-read": 0o000, "no-exec": 0o444}


@pytest.fixture(params=sorted(_MODES), ids=sorted(_MODES))
def unreadable(request):
    """chmod a directory unreachable for one test, then restore it.

    Parametrized over ``_MODES``, so every case that takes this fixture runs
    against BOTH permission shapes. Restoration is mandatory: an un-restored
    dir breaks pytest's own tmp_path teardown for every later test in the
    session.
    """
    mode = _MODES[request.param]
    victims: list[tuple[Path, int]] = []

    def _make(path: Path) -> Path:
        victims.append((path, path.stat().st_mode))
        path.chmod(mode)
        return path

    yield _make
    for path, original in reversed(victims):
        path.chmod(original)


# --------------------------------------------------------------------------- #
# Task 1.1 — Behavior 3: each descent level tags `unreadable`, never raises
# --------------------------------------------------------------------------- #
# Every level the cache walk descends through. The first four each take TWO
# steps — list the dir, then is_dir()-filter each child — and the two steps fail
# on DIFFERENT permission shapes (see _MODES). A guard on only the listing leaves
# every filter bare: under 0o444 the listing succeeds, the walk reports NOT
# blind, and the next child stat raises PermissionError out of the resolver.
#
# PR #144 R5/R6 — the list used to STOP at `version`, two levels above the
# deepest dir the walk actually stats. `_SHARED_REL` is two segments deep, and
# both of those levels were broken in their own way:
#   `skills`  — walls off the `_shared` stat, but was reported as the VERSION
#               dir, which is perfectly readable. The operator, told to fix
#               `<version>`, chmods a directory that was never the problem.
#   `_shared` — walls off the sentinel stat, and `_is_framework_root` swallowed
#               that EACCES internally and answered False; `shared_dir.is_dir()`
#               only needs +x on the PARENT, so the dir reported `[cache: miss]`
#               at BOTH 0o000 and 0o444. The `unreadable` tag was DEAD here.
_LEVELS = {
    "cache-root": lambda t: t["root"],
    "marketplace": lambda t: t["root"] / "mkt-a",
    "plugin": lambda t: t["root"] / "mkt-a" / "three-pillars",
    "version": lambda t: t["root"] / "mkt-a" / "three-pillars" / "1.2.0",
    "skills": lambda t: t["a_shared"].parent,
    "shared": lambda t: t["a_shared"],
}


@pytest.mark.parametrize("level", sorted(_LEVELS))
def test_unreadable_cache_dir_is_tagged_not_a_traceback(level, cache_tree, unreadable):
    """An unreadable dir at ANY descent level → SharedScriptNotFound, tagged."""
    victim = unreadable(_LEVELS[level](cache_tree))

    with pytest.raises(SharedScriptNotFound) as exc:
        _resolve(NAME, cwd=cache_tree["cwd"], cache_root=cache_tree["root"])

    msg = str(exc.value)
    assert str(victim) in msg, f"{level}: the unreadable dir must be NAMED"
    assert "[cache: unreadable]" in msg, f"{level}: must carry the unreadable tag"
    # The tag and the path belong to the SAME rendered line, not two coincidences.
    tagged = [
        line
        for line in msg.splitlines()
        if str(victim) in line and "[cache: unreadable]" in line
    ]
    assert tagged, f"{level}: expected one line naming {victim} as unreadable"
    # EXACT-TRIPLE (impl-audit rework). The substring asserts above are a PREFIX
    # match: with the version-level readability guard deleted, _probe's own
    # OSError catch records "<version>/skills/_shared  [cache: unreadable]",
    # which CONTAINS `victim` and satisfies both — so the [version] case was
    # decorative. Pinning the exact triple makes the level name the directory an
    # operator must actually chmod, which is the guarantee the code comment claims.
    assert ("cache", str(victim), "unreadable") in exc.value.probe_report, (
        level,
        exc.value.probe_report,
    )


@pytest.mark.parametrize(
    "level", ["marketplace", "plugin", "version", "skills", "shared"]
)
def test_unreadable_level_degrades_independently(level, cache_tree, unreadable):
    """One unreadable dir must not abort the walk — the sibling branch is still scanned.

    ``cache-root`` is excluded on purpose: making the root itself unreadable
    leaves nothing to keep walking, so there is no independence to assert.
    """
    unreadable(_LEVELS[level](cache_tree))

    with pytest.raises(SharedScriptNotFound) as exc:
        _resolve(NAME, cwd=cache_tree["cwd"], cache_root=cache_tree["root"])

    msg = str(exc.value)
    assert str(cache_tree["b_shared"]) in msg, (
        f"{level}: the readable sibling branch must still be enumerated"
    )


def test_probe_report_is_source_path_status_triples(cache_tree, unreadable):
    """`probe_report` is the structured form of the message: (source, path, status)."""
    victim = unreadable(_LEVELS["plugin"](cache_tree))

    with pytest.raises(SharedScriptNotFound) as exc:
        _resolve(NAME, cwd=cache_tree["cwd"], cache_root=cache_tree["root"])

    report = exc.value.probe_report
    assert isinstance(report, list) and report
    for entry in report:
        assert isinstance(entry, tuple) and len(entry) == 3
        source, path, status = entry
        assert isinstance(source, str) and isinstance(path, str)
        assert status in {"hit", "miss", "unreadable"}
    assert ("cache", str(victim), "unreadable") in report


# --------------------------------------------------------------------------- #
# Task 1.3 — `probed_roots` back-compat + the audit-A3 scanned-roots regression
# --------------------------------------------------------------------------- #
def test_probed_roots_is_still_list_of_str(cache_tree):
    """`probe_report` is ADDITIVE — the #129 `probed_roots` attribute is untouched."""
    with pytest.raises(SharedScriptNotFound) as exc:
        _resolve(NAME, cwd=cache_tree["cwd"], cache_root=cache_tree["root"])

    roots = exc.value.probed_roots
    assert isinstance(roots, list)
    assert roots and all(isinstance(r, str) for r in roots)
    assert str(cache_tree["root"]) in roots


def test_populated_non_matching_cache_enumerates_scanned_roots(cache_tree):
    """A cache that is populated but lacks <name> names every root it scanned."""
    with pytest.raises(SharedScriptNotFound) as exc:
        _resolve(NAME, cwd=cache_tree["cwd"], cache_root=cache_tree["root"])

    msg = str(exc.value)
    for shared in (cache_tree["a_shared"], cache_tree["b_shared"]):
        assert str(shared) in msg, "discovered-but-non-matching root must be NAMED"
        assert str(shared) in exc.value.probed_roots


# --------------------------------------------------------------------------- #
# PR #144 R8 — `_probe_records`' per-path dedupe, across the two report STAGES
# --------------------------------------------------------------------------- #
def test_root_probed_and_scanned_is_reported_once(cache_tree):
    """A root reached by probes 1-4 AND by the cache walk is reported ONCE.

    `_probe_records` folds TWO independently-built lists into the report: the
    ordered probes 1-4, and the `scanned` _shared dirs the cache walk
    discovered. `_probe`'s own `os.path.realpath` dedupe only covers the FIRST
    list — it never sees `scanned` at all, which is appended after the walk
    returns. So the cross-stage duplicate routes through `_probe_records`'
    `if path in seen: continue` and NOTHING ELSE.

    That guard shipped untested: deleting it left the whole suite green, because
    the only de-duplication case on the books
    (`test_symlinked_duplicate_root_reported_once*`) is probes-1-4 only.

    Reachable in the real world, not just in principle: `self_root` IS a cache
    plugin dir whenever the resolver is executed FROM the plugin cache — the
    ordinary consumer install. The operator then reads the same directory twice
    and cannot tell whether two installs are broken or one.
    """
    duplicated = cache_tree["a_shared"]
    # The version dir holding a_shared — a real framework root (it carries the
    # sentinel) that simply lacks NAME, so probe 4 records a miss rather than
    # resolving and short-circuiting the cache walk.
    self_root = duplicated.parent.parent

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(
            NAME,
            cwd=cache_tree["cwd"],
            cache_root=cache_tree["root"],
            plugin_root=None,
            self_root=self_root,
        )

    paths = [path for _source, path, _status in exc.value.probe_report]
    assert paths.count(str(duplicated)) == 1, (
        f"{duplicated} was reached as `self` AND scanned by the cache walk; it "
        f"must be reported once, got {paths.count(str(duplicated))}: "
        f"{exc.value.probe_report}"
    )
    # The surviving record keeps the FIRST source that reached it — the probe
    # stage — so the tag still tells the operator how the resolver got there.
    assert ("self", str(duplicated), "miss") in exc.value.probe_report
    # ... and the rendered message inherits the dedupe (one line, not two).
    lines = [ln for ln in str(exc.value).splitlines() if str(duplicated) in ln]
    assert len(lines) == 1, lines


def test_the_helper_default_withholds_probe_1_rather_than_supplying_it(tmp_path):
    """`_resolve`'s `cwd` default must not hand probe 1 the PROCESS cwd.

    Every case in this module passes `cwd=` explicitly, so the default is inert
    today — which is exactly why it needs a test of its own: the trap springs on
    the NEXT case added here, not on any case already written. Under pytest the
    process cwd is the dogfood repo, which really does carry `NAME`, so a
    default that derived it would resolve the live worktree copy against an
    EMPTY cache and pass for the wrong reason, with the helper's own docstring
    promising the opposite.

    WITHHELD is asserted, not merely "not found": probe 1 must contribute no
    record at all, the same as a `None` `plugin_root` or `self_root`.
    """
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()

    with pytest.raises(SharedScriptNotFound) as exc:
        _resolve(NAME, cache_root=empty_cache)

    assert [rec for rec in exc.value.probe_report if rec[0] == "toplevel"] == [], (
        exc.value.probe_report
    )
