"""Probe ORDER, dedupe and misses (design: resolve-script-override-roots).

`test_resolve_script_roots.py` pins each root in isolation. This module pins
what happens when more than one of them can answer:

    toplevel(1) > plugin-root(2) > skill-dir(3) > self(4) > cache(5)

Split out of `test_resolve_script_roots.py` at Task 2.4 per the plan's cap
check — that module is already at ~240 lines against a 300-line soft-warn, and
"isolation" and "contention" are two different questions anyway.

The fixture builders are duplicated rather than imported from the sibling
module: cross-module test imports were retired as brittle when `conftest.py`
was introduced, and these three helpers are not worth a repo-wide fixture.

Run with: python -m pytest skills/_shared/test_resolve_script_precedence.py -q
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
SHARED_REL = Path("skills") / "_shared"


# --------------------------------------------------------------------------- #
# Fixture builders — real trees only
# --------------------------------------------------------------------------- #
def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True
    )
    return path


def _framework_root(root: Path, *, sentinel: bool = True, script: bool = True) -> Path:
    """A candidate root. Either half can be withheld to build a miss."""
    (root / SHARED_REL).mkdir(parents=True, exist_ok=True)
    if sentinel:
        (root / SHARED_REL / "first-run.md").write_text("# sentinel\n", encoding="utf-8")
    if script:
        (root / SHARED_REL / NAME).write_text(f"# copy at {root.name}\n", encoding="utf-8")
    return root


def _cache_root(tmp_path: Path, *, script: bool = True) -> Path:
    shared = tmp_path / "cache" / "marketplace" / "three-pillars" / "1.2.0" / SHARED_REL
    shared.mkdir(parents=True, exist_ok=True)
    # A cache entry is sentinel-qualified exactly like probes 1-4, so a REAL
    # install carries first-run.md. Without it the cache could never win, and a
    # precedence case would pass because the loser was disqualified rather than
    # because the winner outranked it.
    (shared / "first-run.md").write_text("# sentinel\n", encoding="utf-8")
    if script:
        (shared / NAME).write_text("# cache copy\n", encoding="utf-8")
    return tmp_path / "cache"


def _call(*, cwd, cache_root, plugin_root=None, skill_dir=None, self_root=None):
    """The module's single ``resolve_shared_script`` call site — all roots explicit.

    `self_root=` is spelled out on every path through here; the ambient default
    is the live checkout, which really does carry `github_pr_author.py`, so an
    omission would let a contention case resolve a copy no fixture built.
    """
    return resolve_shared_script(
        NAME,
        cwd=cwd,
        cache_root=cache_root,
        plugin_root=plugin_root,
        skill_dir=skill_dir,
        self_root=self_root,
    )


def _all_five(tmp_path: Path) -> dict:
    """Every one of the five roots present AND carrying the module."""
    install = _framework_root(tmp_path / "skill-dir-install")
    (install / "skills" / "tp-fake").mkdir(parents=True, exist_ok=True)
    return {
        "cwd": _framework_root(_git_init(tmp_path / "toplevel")),
        "plugin_root": _framework_root(tmp_path / "plugin-root"),
        "skill_dir": install / "skills" / "tp-fake",
        "self_root": _framework_root(tmp_path / "self-install"),
        "cache_root": _cache_root(tmp_path),
    }


def _expected(kwargs: dict, source: str) -> Path:
    if source == "toplevel":
        return kwargs["cwd"] / SHARED_REL / NAME
    if source == "plugin-root":
        return kwargs["plugin_root"] / SHARED_REL / NAME
    if source == "skill-dir":
        return Path(kwargs["skill_dir"]).parent.parent / SHARED_REL / NAME
    if source == "self":
        return kwargs["self_root"] / SHARED_REL / NAME
    raise AssertionError(f"no expected path for {source!r}")


#: (label, winner, loser) — the four adjacent pairs of the probe order.
PAIRS = [
    ("1>2", "toplevel", "plugin-root"),
    ("2>3", "plugin-root", "skill-dir"),
    ("3>4", "skill-dir", "self"),
    ("4>5", "self", "cache"),
]


# --------------------------------------------------------------------------- #
# Task 2.4 — pairwise precedence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "label,winner,loser", PAIRS, ids=[p[0] for p in PAIRS]
)
def test_precedence_pairwise(tmp_path, label, winner, loser):
    """Both roots of an adjacent pair carry the module -> the higher one wins."""
    full = _all_five(tmp_path)
    keep = {"toplevel": "cwd", "plugin-root": "plugin_root",
            "skill-dir": "skill_dir", "self": "self_root", "cache": "cache_root"}
    kwargs = {
        "cwd": _git_init(tmp_path / "consumer"),
        "cache_root": _cache_root(tmp_path / "empty", script=False),
        "plugin_root": None,
        "skill_dir": None,
        "self_root": None,
    }
    for source in (winner, loser):
        kwargs[keep[source]] = full[keep[source]]

    result = _call(**kwargs)

    assert Path(result).resolve() == _expected(kwargs, winner).resolve(), (
        f"[{label}] expected the {winner} copy to beat {loser}; got {result}"
    )


def test_all_five_set_yields_toplevel(tmp_path):
    """All five roots carry the module -> the live checkout wins (Behavior 2).

    This is the load-bearing half of D1's divergence from `resolve_root.sh`:
    the anchored install can LAG (#126), so the dogfood copy is the answer to
    "where is the CURRENT copy of this FREE module".
    """
    kwargs = _all_five(tmp_path)

    result = _call(**kwargs)

    assert Path(result).resolve() == _expected(kwargs, "toplevel").resolve()


# --------------------------------------------------------------------------- #
# Task 2.4 — realpath dedupe
# --------------------------------------------------------------------------- #
def test_symlinked_duplicate_root_reported_once(tmp_path):
    """One PHYSICAL root reached through two roots is probed and reported ONCE.

    `plugin_root` gets the real path and `skill_dir` a symlink into the same
    tree. Without an `os.path.realpath` dedupe the operator reads the same
    directory twice in the diagnostic and cannot tell whether two installs are
    broken or one.

    NOTE (impl-audit rework): in THIS spelling the dedupe is never reached — the
    skill-dir grandparent is `.resolve()`d before the probe, so both probe path
    strings are already byte-identical and `_probe_records` de-duplicates on the
    raw string. This case still pins report de-duplication, but the load-bearing
    twin is `test_symlinked_duplicate_root_reported_once_link_as_plugin_root`
    below, which reaches `os.path.realpath` because `plugin_root` is NOT
    `.resolve()`d by the resolver.
    """
    physical = _framework_root(tmp_path / "physical", script=False)
    (physical / "skills" / "tp-fake").mkdir(parents=True, exist_ok=True)
    link = tmp_path / "linked"
    link.symlink_to(physical, target_is_directory=True)

    with pytest.raises(SharedScriptNotFound) as exc:
        _call(
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=_cache_root(tmp_path / "empty", script=False),
            plugin_root=physical,
            skill_dir=link / "skills" / "tp-fake",
        )

    real = os.path.realpath(physical / SHARED_REL)
    seen = [os.path.realpath(path) for _tag, path, _status in exc.value.probe_report]
    assert seen.count(real) == 1, (
        f"{physical / SHARED_REL} should be reported once, got {seen.count(real)}: "
        f"{exc.value.probe_report}"
    )


def test_symlinked_duplicate_root_reported_once_link_as_plugin_root(tmp_path):
    """The spelling that actually exercises the `os.path.realpath` dedupe.

    The twin above passes `plugin_root=physical` + `skill_dir=link/...`, but the
    skill-dir grandparent is `.resolve()`d before probing, so both probe strings
    match textually and the raw-string `seen` set already de-duplicates them —
    deleting the realpath dedupe leaves that test green.

    `plugin_root` is NOT `.resolve()`d, so handing IT the symlink and `skill_dir`
    the physical path produces two DIFFERENT probe strings naming one physical
    directory. Only `os.path.realpath` collapses them. Mutant-verified: this
    goes 1 -> 2 entries when the dedupe is removed.
    """
    physical = _framework_root(tmp_path / "physical", script=False)
    (physical / "skills" / "tp-fake").mkdir(parents=True, exist_ok=True)
    link = tmp_path / "linked"
    link.symlink_to(physical, target_is_directory=True)

    with pytest.raises(SharedScriptNotFound) as exc:
        _call(
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=_cache_root(tmp_path / "empty", script=False),
            plugin_root=link,
            skill_dir=physical / "skills" / "tp-fake",
        )

    real = os.path.realpath(physical / SHARED_REL)
    seen = [os.path.realpath(path) for _tag, path, _status in exc.value.probe_report]
    assert seen.count(real) == 1, (
        f"{physical / SHARED_REL} reached via symlinked plugin_root should be "
        f"reported once, got {seen.count(real)}: {exc.value.probe_report}"
    )


# --------------------------------------------------------------------------- #
# Task 2.4 — a root that exists but is not a framework root (D5)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tag", ["plugin-root", "skill-dir", "self"])
def test_sentinel_less_root_recorded_miss(tmp_path, tag):
    """A root carrying <NAME> but NOT the sentinel is reported `miss`, never used.

    D5: a root pointing somewhere wrong is the likeliest operator error this
    design will meet. Dropping it from the diagnostic turns a two-second fix
    into a bug report, and USING it would resolve a copy from a tree that is not
    a framework install at all.
    """
    root = _framework_root(tmp_path / "wrong", sentinel=False, script=True)
    (root / "skills" / "tp-fake").mkdir(parents=True, exist_ok=True)
    kwargs = {
        "cwd": _git_init(tmp_path / "consumer"),
        "cache_root": _cache_root(tmp_path / "empty", script=False),
    }
    if tag == "plugin-root":
        kwargs["plugin_root"] = root
    elif tag == "skill-dir":
        kwargs["skill_dir"] = root / "skills" / "tp-fake"
    else:
        kwargs["self_root"] = root

    with pytest.raises(SharedScriptNotFound) as exc:
        _call(**kwargs)

    tagged = [rec for rec in exc.value.probe_report if rec[0] == tag]
    assert tagged, f"no `{tag}` record in the report: {exc.value.probe_report}"
    assert all(rec[2] == "miss" for rec in tagged), tagged
    assert all(rec[1].startswith(str(root)) for rec in tagged), tagged
    assert f"[{tag}: miss]" in str(exc.value)


# --------------------------------------------------------------------------- #
# PR #144 R2 — "no skill dir" must mean the same thing in EVERY spelling
# --------------------------------------------------------------------------- #
#: Every value that means "the caller did not name a skill dir". The str/Path
#: split is the whole point: `""` is falsy, but `Path("")` IS `PosixPath('.')`
#: and is TRUTHY, so a truthiness guard on the RAW value closes one spelling and
#: leaves the other wide open — and `Path` is what every in-process caller
#: passes, so the still-open type was the NORMAL one. Only the CLI, whose values
#: are always `str`, was actually covered.
#:
#: `.` and `./` are here because Python CANNOT tell `Path(".")` from `Path("")`
#: — the empty spelling is gone by the time a Path exists, and `str(Path(""))`
#: is ".". The two must therefore agree, and "names nothing" = UNSET is the side
#: that cannot invent a root. Deliberate divergence from resolve_root.sh, which
#: honours a literal `--skill-dir .` because `[ -n "." ]` is true.
_UNSET_SKILL_DIRS = {
    # NOTE: `empty-str` passes with the round-1 truthiness guard too — `""` is
    # falsy. It is kept as an in-process REGRESSION guard for that fix (which
    # had CLI coverage only), and is NOT presented as coverage of this one.
    "empty-str": "",
    "empty-Path": Path(""),
    "blank-str": "   ",
    "blank-Path": Path("   "),
    "dot-str": ".",
    "dot-Path": Path("."),
    "dotslash-str": "./",
}


def _grandparent_trap(tmp_path: Path):
    """Return (inside, cache_root, trap_copy, cache_copy) for the empty-anchor trap.

    `inside` is a NON-git dir two levels under a framework root that carries
    NAME. Made the process cwd, it is exactly the directory `Path("")/../..`
    resolves THROUGH — so if an empty skill_dir is still treated as a real
    value, the grandparent becomes an explicit root and outranks the cache.
    """
    trap_root = _framework_root(tmp_path / "outer")
    inside = trap_root / "skills" / "tp-foo"
    inside.mkdir(parents=True, exist_ok=True)  # deliberately NOT a git repo
    cache_root = _cache_root(tmp_path / "consumer")
    cache_copy = (
        cache_root / "marketplace" / "three-pillars" / "1.2.0" / SHARED_REL / NAME
    )
    return inside, cache_root, trap_root / SHARED_REL / NAME, cache_copy


def test_a_named_skill_dir_really_does_anchor_its_grandparent(tmp_path, monkeypatch):
    """CONTROL: the trap is REACHABLE, so the cases below are not vacuous.

    Without this, they would pass on a resolver that had simply lost the
    skill-dir probe altogether.
    """
    inside, cache_root, trap_copy, cache_copy = _grandparent_trap(tmp_path)
    monkeypatch.chdir(inside)
    assert trap_copy.exists() and cache_copy.exists()

    result = _call(cwd=inside, cache_root=cache_root, skill_dir=inside)

    assert Path(result).resolve() == trap_copy.resolve(), (
        "a NAMED skill_dir must anchor its grandparent and outrank the cache"
    )


@pytest.mark.parametrize("label", sorted(_UNSET_SKILL_DIRS))
def test_empty_skill_dir_anchors_no_root_at_all(tmp_path, monkeypatch, label):
    """An unset `skill_dir` anchors NO root — the probe is SKIPPED, not missed.

    This is the CONTRACT, observed directly. The end-to-end case below only
    fires when the anchored root happens to carry NAME, which depends on where
    the trap sits relative to the cwd; a whitespace-only value anchors a
    different directory than `""`/`"."` do, so no single trap catches every
    spelling. `_probe` records a visit BEFORE qualifying the root (D5), so the
    ABSENCE of a `skill-dir` record is exactly "no root was anchored".
    """
    base = tmp_path / "a" / "b" / "c"
    base.mkdir(parents=True)  # a plain tree: no sentinel anywhere above it
    monkeypatch.chdir(base)
    empty_cache = tmp_path / "empty"
    empty_cache.mkdir()

    with pytest.raises(SharedScriptNotFound) as exc:
        _call(
            cwd=base, cache_root=empty_cache, skill_dir=_UNSET_SKILL_DIRS[label]
        )

    anchored = [rec for rec in exc.value.probe_report if rec[0] == "skill-dir"]
    assert not anchored, (
        f"skill_dir={_UNSET_SKILL_DIRS[label]!r} ({label}) anchored a root the "
        f"caller never named: {anchored}"
    )


@pytest.mark.parametrize("label", sorted(_UNSET_SKILL_DIRS))
def test_empty_skill_dir_does_not_outrank_the_cache(tmp_path, monkeypatch, label):
    """...and the consequence: the CACHE copy still wins, at exit 0.

    Reproduced live before the fix: `skill_dir=""` returned the cache copy while
    `skill_dir=Path("")` returned the TRAP copy. Same call, same intent, two
    answers, and the wrong one arrives silently — the failure mode this module's
    headline contract ("never a wrong path") exists to prevent.
    """
    inside, cache_root, trap_copy, cache_copy = _grandparent_trap(tmp_path)
    monkeypatch.chdir(inside)

    result = _call(
        cwd=inside, cache_root=cache_root, skill_dir=_UNSET_SKILL_DIRS[label]
    )

    assert Path(result).resolve() == cache_copy.resolve(), (
        f"skill_dir={_UNSET_SKILL_DIRS[label]!r} ({label}) anchored "
        f"{trap_copy.parent.parent} as an explicit root the caller never named"
    )
