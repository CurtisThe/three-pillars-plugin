"""Each override root resolves IN ISOLATION (design: resolve-script-override-roots).

`resolve_script.py` probes five candidate roots in order:

    toplevel -> plugin-root -> skill-dir -> self -> cache

This module pins each one on its own: in every case exactly ONE root carries
`skills/_shared/first-run.md` + `skills/_shared/<name>`, and every other root is
passed `None` or an empty directory. A case that passes because a NEIGHBOURING
root happened to carry the module proves nothing, so isolation is the whole
point. Precedence between roots lives in `test_resolve_script_precedence.py`.

No mocks anywhere: real `tmp_path` trees, real `git init`, real files.

Run with: python -m pytest skills/_shared/test_resolve_script_roots.py -q
"""
from __future__ import annotations

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

#: The five probe tags, in order. Read by the parametrizations below so a tag
#: rename cannot leave a stale case behind.
SOURCES = ("toplevel", "plugin-root", "skill-dir", "self", "cache")


# --------------------------------------------------------------------------- #
# Fixture builders — real trees only
# --------------------------------------------------------------------------- #
def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True
    )
    return path


def _framework_root(root: Path, *, with_script: bool = True) -> Path:
    """A framework root: carries the sentinel, and optionally ``<NAME>``."""
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    if with_script:
        _write(root / "skills" / "_shared" / NAME, f"# copy at {root.name}\n")
    return root


def _empty_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_copy(cache_root: Path, *, with_script: bool = True) -> Path:
    """cache/<mkt>/three-pillars/1.2.0/skills/_shared/<NAME>; return that file.

    The install carries the sentinel: a cache entry is sentinel-qualified
    exactly like probes 1-4, so a bare dir holding only ``<NAME>`` is not an
    install the resolver may hand back to be executed.
    """
    shared = (
        cache_root / "marketplace" / "three-pillars" / "1.2.0" / "skills" / "_shared"
    )
    shared.mkdir(parents=True, exist_ok=True)
    _write(shared / "first-run.md", "# sentinel\n")
    if with_script:
        return _write(shared / NAME, "# cache copy\n")
    return shared


def _call(
    *, cwd, cache_root, plugin_root=None, skill_dir=None, self_root=None, name=NAME
):
    """The module's single ``resolve_shared_script`` call site.

    Every ambient root is named EXPLICITLY here — `plugin_root` and `self_root`
    default to the real machine, and the live checkout really does carry
    `github_pr_author.py`, so an omission would make these cases pass against a
    path no fixture created. `test_resolve_script_hermeticity.py` enforces the
    `self_root=` half of that structurally.
    """
    return resolve_shared_script(
        name,
        cwd=cwd,
        cache_root=cache_root,
        plugin_root=plugin_root,
        skill_dir=skill_dir,
        self_root=self_root,
    )


def _isolated(tmp_path: Path, source: str) -> tuple[dict, Path]:
    """Build a tree where ONLY ``source`` can resolve; return (kwargs, expected).

    The neighbours are not merely absent — where a root has to exist at all
    (`cwd`, `cache_root`) it exists and is EMPTY, so a case cannot pass by
    accidentally reading a sibling's copy.
    """
    cache_root = _empty_dir(tmp_path / "cache")
    kwargs: dict = {"cwd": None, "cache_root": cache_root}

    if source == "toplevel":
        root = _framework_root(_git_init(tmp_path / "toplevel"))
        kwargs["cwd"] = root
        return kwargs, root / "skills" / "_shared" / NAME

    # Every non-toplevel case runs from a git repo that is NOT a framework
    # checkout, so probe 1 is live but misses.
    kwargs["cwd"] = _git_init(tmp_path / "consumer")

    if source == "plugin-root":
        root = _framework_root(tmp_path / "plugin-root")
        kwargs["plugin_root"] = root
        return kwargs, root / "skills" / "_shared" / NAME

    if source == "skill-dir":
        root = _framework_root(tmp_path / "skill-dir-install")
        skill_dir = _empty_dir(root / "skills" / "tp-fake")
        kwargs["skill_dir"] = skill_dir
        return kwargs, root / "skills" / "_shared" / NAME

    if source == "self":
        root = _framework_root(tmp_path / "self-install")
        kwargs["self_root"] = root
        return kwargs, root / "skills" / "_shared" / NAME

    if source == "cache":
        return kwargs, _cache_copy(cache_root)

    raise AssertionError(f"unknown probe source {source!r}")


# --------------------------------------------------------------------------- #
# Task 2.3 — each root resolves on its own
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source", SOURCES)
def test_root_resolves_in_isolation(tmp_path, source):
    """Exactly one root carries the module -> that root's copy is returned."""
    kwargs, expected = _isolated(tmp_path, source)

    result = _call(**kwargs)

    assert Path(result).resolve() == expected.resolve(), (
        f"[{source}] isolation: expected {expected}, got {result}"
    )
    assert Path(result).is_file()


# --------------------------------------------------------------------------- #
# Behavior 1 — a FREE-only `--skill-dir` install, with NO usable git toplevel
# --------------------------------------------------------------------------- #
# Two cwd topologies, because they traverse genuinely different branches
# (audit finding 5):
#   no-git             -> `_git_toplevel` itself fails; there is no toplevel
#   non-framework-git  -> `_git_toplevel` SUCCEEDS, then `_is_framework_root`
#                         rejects the answer
# Collapsing them into one case leaves one of those branches unexercised.
def _cwd_topology(tmp_path: Path, topology: str) -> Path:
    if topology == "no-git":
        # A plain directory under tmp_path, outside any git repo.
        return _empty_dir(tmp_path / "nowhere")
    if topology == "non-framework-git":
        # A REAL git repo that lacks skills/_shared/first-run.md.
        return _git_init(tmp_path / "consumer")
    raise AssertionError(f"unknown cwd topology {topology!r}")


@pytest.mark.parametrize("topology", ["no-git", "non-framework-git"])
def test_skill_dir_install_resolves_without_a_framework_toplevel(tmp_path, topology):
    """FREE-only `--skill-dir` install + empty cache -> resolves via skill-dir."""
    cwd = _cwd_topology(tmp_path, topology)
    root = _framework_root(tmp_path / "install")
    skill_dir = _empty_dir(root / "skills" / "tp-fake")
    cache_root = _empty_dir(tmp_path / "cache")

    result = _call(cwd=cwd, cache_root=cache_root, skill_dir=skill_dir)

    assert Path(result).resolve() == (root / "skills" / "_shared" / NAME).resolve()


@pytest.mark.parametrize("topology", ["no-git", "non-framework-git"])
def test_toplevel_probe_is_recorded_as_a_miss(tmp_path, topology):
    """A toplevel that cannot serve is REPORTED `[toplevel: miss]`, never dropped.

    D5: the single most likely operator error this design will meet is a root
    pointing somewhere wrong. Silently omitting the probe from the diagnostic is
    the difference between a two-second fix and a bug report — so the miss has
    to be visible, for BOTH topologies, including the one where there is no git
    toplevel at all (the cwd itself is what was probed).
    """
    cwd = _cwd_topology(tmp_path, topology)
    # The skill-dir install exists but does NOT carry the module, so the walk
    # runs to exhaustion and the probe report becomes observable.
    root = _framework_root(tmp_path / "install", with_script=False)
    skill_dir = _empty_dir(root / "skills" / "tp-fake")
    cache_root = _empty_dir(tmp_path / "cache")

    with pytest.raises(SharedScriptNotFound) as exc:
        _call(cwd=cwd, cache_root=cache_root, skill_dir=skill_dir)

    tagged = [rec for rec in exc.value.probe_report if rec[0] == "toplevel"]
    assert tagged, (
        f"[{topology}] no `toplevel` record in the probe report: "
        f"{exc.value.probe_report}"
    )
    assert all(rec[2] == "miss" for rec in tagged), tagged
    assert "[toplevel: miss]" in str(exc.value)


# --------------------------------------------------------------------------- #
# Behavior 2 (positive half) — a non-cache $CLAUDE_PLUGIN_ROOT install resolves
# --------------------------------------------------------------------------- #
def test_plugin_root_install_outside_the_cache_resolves(tmp_path):
    """An install at an arbitrary path, reachable only via `plugin_root`, resolves.

    The negative half — that a live checkout OUTRANKS it — is a precedence case
    and lives in `test_resolve_script_precedence.py`.
    """
    consumer = _git_init(tmp_path / "consumer")
    install = _framework_root(tmp_path / "opt" / "three-pillars")
    cache_root = _empty_dir(tmp_path / "cache")

    result = _call(cwd=consumer, cache_root=cache_root, plugin_root=install)

    assert Path(result).resolve() == (install / "skills" / "_shared" / NAME).resolve()
    # ...and NOT from the cache, which is empty.
    assert not str(Path(result).resolve()).startswith(str(cache_root.resolve()))


# --------------------------------------------------------------------------- #
# Behavior 2 — the AMBIENT env read (impl-audit rework)
#
# THESE TWO TESTS ARE THE ONLY COVERAGE OF THE `$CLAUDE_PLUGIN_ROOT` ENV READ.
# Do NOT "tidy" them into `plugin_root=` kwarg form — that is precisely what
# left this unpinned. Every other plugin-root case in the suite injects the
# kwarg, but `resolve_script.py`'s own docstring states the variable is set by
# the HOST (Claude Code) and never passed by an in-repo caller, so the kwarg is
# NOT the production path. Renaming the env key in the resolver left the entire
# suite green, which is how the gap was found.
#
# The repo-wide autouse `_strip_ambient_plugin_root` fixture in conftest.py does
# not defeat these: it runs BEFORE the test body, so `monkeypatch.setenv` wins.
# --------------------------------------------------------------------------- #
def test_ambient_env_plugin_root_resolves(tmp_path, monkeypatch):
    """A non-cache `$CLAUDE_PLUGIN_ROOT` install resolves via the ENV read."""
    root = _framework_root(tmp_path / "plugin-install")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))

    # NOTE: `resolve_shared_script` is called DIRECTLY, omitting `plugin_root`
    # entirely — the helper `_call` passes `plugin_root=None`, and the resolver
    # consults the environment only when that parameter is `_UNSET`. An explicit
    # `None` therefore SUPPRESSES the ambient read, which is the whole path
    # under test. `self_root=None` is still passed (hermeticity sweep).
    result = resolve_shared_script(
        NAME,
        cwd=_git_init(tmp_path / "consumer"),
        cache_root=_empty_dir(tmp_path / "emptycache"),
        self_root=None,
    )

    assert Path(result).resolve() == (root / "skills" / "_shared" / NAME).resolve()


def test_ambient_env_plugin_root_without_sentinel_is_recorded_as_a_miss(
    tmp_path, monkeypatch
):
    """The negative twin: `<NAME>` present but the sentinel absent → not a root.

    Pins that the env read is *qualified*, not merely consulted — otherwise the
    positive test above would pass for a resolver that trusted any directory.
    """
    impostor = tmp_path / "impostor"
    _write(impostor / "skills" / "_shared" / NAME, "# not a framework root\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(impostor))

    with pytest.raises(SharedScriptNotFound) as exc:
        # Direct call, `plugin_root` omitted — see the note above.
        resolve_shared_script(
            NAME,
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=_empty_dir(tmp_path / "emptycache"),
            self_root=None,
        )

    assert any(tag == "plugin-root" for tag, _p, _s in exc.value.probe_report), (
        exc.value.probe_report
    )


# --------------------------------------------------------------------------- #
# PR #144 S6 — `_PLUGIN_GLOB` is the only thing between the resolver and an
#              UNRELATED VENDOR's module. Nothing tested it: mutating it to "*"
#              left the entire suite green.
# --------------------------------------------------------------------------- #
def _vendor_install(cache_root: Path, plugin: str) -> Path:
    """A complete, VALID framework install under a non-`three-pillars*` name.

    Everything about it qualifies except the plugin-dir NAME: correct cache
    depth, the sentinel, and `<NAME>` itself. So the glob is the ONLY thing that
    can reject it — which is exactly what makes this case load-bearing.
    """
    root = cache_root / "marketplace" / plugin / "1.0.0"
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    _write(root / "skills" / "_shared" / NAME, "# UNRELATED VENDOR copy\n")
    return root


def test_non_three_pillars_cache_plugin_is_skipped(tmp_path):
    """A cache plugin dir outside `three-pillars*` never resolves.

    The cache walk executes whatever it returns, so a plugin from an unrelated
    vendor sitting in the same marketplace cache must not be reachable at all —
    not "outranked", not "deduped", skipped.
    """
    cache_root = tmp_path / "cache"
    evil = _vendor_install(cache_root, "evil-vendor-plugin")

    with pytest.raises(SharedScriptNotFound) as exc:
        _call(
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=cache_root,
        )

    # Not merely "did not win" — never even scanned.
    assert str(evil) not in " ".join(exc.value.probed_roots), exc.value.probed_roots


def test_non_three_pillars_plugin_loses_to_the_real_one_lexicographically(tmp_path):
    """The tie-break would pick the impostor, so only the glob can save this.

    `evil-vendor-plugin` sorts BEFORE `three-pillars`, and the cache winner is
    the lexicographically-first ROOT (mirroring resolve_root.sh's
    `sort | head -n 1`). Widen the glob to "*" and the unrelated vendor's copy
    wins outright over the real one — this case is what makes the glob's value
    concrete rather than theoretical.
    """
    cache_root = tmp_path / "cache"
    evil = _vendor_install(cache_root, "evil-vendor-plugin")
    real = _cache_copy(cache_root)

    assert str(evil) < str(real.parent.parent.parent), (
        "fixture precondition: the impostor must sort FIRST, or the glob is "
        "not what decides this case"
    )

    result = _call(cwd=_git_init(tmp_path / "consumer"), cache_root=cache_root)

    assert Path(result).resolve() == real.resolve()


# --------------------------------------------------------------------------- #
# PR #144 R3 — NO HOME AT ALL: the cache root must not kill the whole call
# --------------------------------------------------------------------------- #
@pytest.fixture()
def no_home(monkeypatch):
    """Simulate a container / unmapped uid: ``$HOME`` unset, no passwd entry.

    Not a mock of the resolver — a simulation of the ENVIRONMENT, which is the
    only way to reach this branch on a developer box that has both. Both
    spellings of "where is home" bottom out in exactly this lookup, so the
    fixture is fair to the code under test either way: ``os.path.expanduser``
    returns the path UNEXPANDED, while ``Path.home()`` raises ``RuntimeError``
    — and RuntimeError is NOT OSError, so nothing in `_main` catches it.
    """
    import pwd

    monkeypatch.delenv("HOME", raising=False)

    def _no_passwd_entry(_uid):
        raise KeyError("no passwd entry for this uid")

    monkeypatch.setattr(pwd, "getpwuid", _no_passwd_entry)


def test_no_home_still_resolves_through_probe_1(tmp_path, no_home):
    """With no home at all, the DOGFOOD probe still answers — at exit 0.

    This is the half that eagerness broke. `cache_root` defaulted at the TOP of
    the function, before a single probe ran, so a machine with no home lost even
    the calls that never needed a cache: probe 1 had the answer and never got
    asked. `cache_root` is deliberately NOT passed here — that default IS the
    code under test.
    """
    repo = _framework_root(_git_init(tmp_path / "dogfood"))

    result = resolve_shared_script(
        NAME, cwd=repo, plugin_root=None, self_root=None
    )

    assert Path(result).resolve() == (repo / "skills" / "_shared" / NAME).resolve()


def test_no_home_fails_loud_not_with_a_traceback(tmp_path, no_home):
    """With no home AND nothing resolvable, the failure is still the DOCUMENTED one.

    `SharedScriptNotFound` (exit 1, a diagnostic naming every probed root), not
    a bare `RuntimeError` traceback. The module's headline contract is that it
    either answers or says exactly where it looked; dying is neither.
    """
    consumer = _git_init(tmp_path / "consumer")  # plain repo: no sentinel

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(
            NAME, cwd=consumer, plugin_root=None, self_root=None
        )

    # The unresolvable cache root is still NAMED, unexpanded, rather than
    # vanishing — an operator sees that `~` could not be resolved.
    assert any("plugins" in path for _tag, path, _st in exc.value.probe_report), (
        exc.value.probe_report
    )


def test_cwd_none_withholds_probe_1_like_every_other_ambient_root(tmp_path):
    """`cwd=None` WITHHOLDS the toplevel probe — it must not SUPPLY it.

    `cwd` defaulted to `None` until PR #144 R6, and `None` meant "derive the
    PROCESS cwd" — under pytest the dogfood repo, which really does carry
    `NAME`. So the one spelling every hermetic call site uses to opt OUT of an
    ambient root handed probe 1 that root instead, and the presence-only check
    in `test_resolve_script_sweep._offenders` read it as an opt-out. `_UNSET`
    owns the derivation now, so `None` means for `cwd` exactly what it already
    meant for `self_root` and `plugin_root`.

    The END-TO-END mutant: restore `cwd=None` as the resolver's default and this
    resolves the live worktree copy of `github_pr_author.py` and passes for the
    wrong reason — with the whole sweep still green.
    """
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(
            NAME, cwd=None, cache_root=empty_cache, plugin_root=None, self_root=None
        )

    # WITHHELD, not merely missed: probe 1 contributes no record at all, exactly
    # as a `None` plugin_root or self_root does.
    assert [t for t, _p, _s in exc.value.probe_report if t == "toplevel"] == [], (
        exc.value.probe_report
    )
