"""Every ROOT-VALUED INPUT the resolver takes, through ONE normalizer.

`resolve_shared_script` accepts five roots plus an env derivation, and they all
have the same shape — a directory a caller names. The bug class they all share:

* a spelling that names NO directory (`""`, `"."`, `Path("")`, `Path(".")`)
  still makes `Path(root)/skills/_shared` relative to the PROCESS CWD, so an
  unnamed cwd is anchored as an EXPLICIT root and outranks the cache; and
* a RELATIVE root makes the resolver RETURN a relative path, contradicting its
  documented `:returns: an absolute Path`.

The first was closed once for `skill_dir` alone, by a `.parts` guard written at
that one call site. Its SIBLING `plugin_root` — identical in shape, one line
away — kept the bug, and `CLAUDE_PLUGIN_ROOT="."` reached it too. Closing a
class per-parameter is not closing a class, so `resolve_script._named_root` is
now the single chokepoint and `test_every_root_valued_parameter_is_normalized`
is the ENUMERATION: a sixth root parameter added later cannot skip it silently.

Run with: python -m pytest skills/_shared/test_resolve_script_root_inputs.py -q
"""
from __future__ import annotations

import ast
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
MODULE_PATH = HERE / "resolve_script.py"

#: Every spelling that names NO directory. `""` is falsy but `Path("")` IS
#: `PosixPath('.')` and is TRUTHY, so a truthiness guard is TYPE-DEPENDENT and
#: `str()` is no better (`str(Path(""))` is "."). Both types are exercised
#: because in-process callers pass `Path`, the CLI always passes `str`.
DOT_ANCHORS = ("", ".", Path(""), Path("."))

#: The root-valued parameters. `cwd` is deliberately NOT one: it is a directory
#: to probe FROM (git answers with an absolute toplevel), not a root to join
#: `skills/_shared` onto. Asserted against the real signature below.
ROOT_PARAMS = frozenset({"plugin_root", "skill_dir", "self_root", "cache_root"})


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _framework_root(root: Path) -> Path:
    """A qualifying framework root carrying the sentinel AND ``<NAME>``."""
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    _write(root / "skills" / "_shared" / NAME, f"# copy at {root.name}\n")
    return root


def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True
    )
    return path


@pytest.fixture
def bait(tmp_path, monkeypatch):
    """chdir into a REAL framework root that no argument names.

    The whole trap in one fixture: the process cwd carries the sentinel and
    ``<NAME>``, so ANY input that degrades to "." resolves it — and resolves it
    as an EXPLICIT root, ahead of the cache. Nothing here is passed to the
    resolver, so a correct resolver can never reach it.
    """
    root = _framework_root(tmp_path / "process-cwd")
    monkeypatch.chdir(root)
    return root


@pytest.mark.parametrize("spelling", DOT_ANCHORS, ids=repr)
@pytest.mark.parametrize("param", sorted(ROOT_PARAMS))
def test_a_dot_anchor_never_becomes_a_root(bait, tmp_path, param, spelling):
    """No root-valued input may turn "nothing" into the process cwd.

    Coverage note (ground rule: a test that passes both ways is labelled, not
    counted): the `skill_dir` cells were already closed by the earlier
    per-parameter `.parts` guard and pass with or without `_named_root` — they
    are kept as REGRESSION pins for the guard the normalizer absorbed. The
    `plugin_root`, `self_root` and `cache_root` cells are the ones that fail
    without the fix.
    """
    kwargs = {p: None for p in ROOT_PARAMS}
    kwargs[param] = spelling
    if param != "cache_root":
        kwargs["cache_root"] = tmp_path / "empty-cache"
        kwargs["cache_root"].mkdir(exist_ok=True)

    # Spelled out, NOT `**kwargs`: a splat is invisible to the hermeticity
    # sweep, which is the same "bound to another name" class the sweep exists
    # to catch. The dict still drives WHICH param carries the bait.
    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(
            NAME,
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=kwargs["cache_root"],
            plugin_root=kwargs["plugin_root"],
            skill_dir=kwargs["skill_dir"],
            self_root=kwargs["self_root"],
        )

    # The failure must not merely be "not found": the bait must be absent from
    # the probe report entirely. A relative record would mean it WAS searched.
    assert all(
        Path(path).is_absolute() for _s, path, _t in exc.value.probe_report
    ), exc.value.probe_report


def test_a_cache_root_dot_anchor_does_not_walk_the_process_cwd(tmp_path, monkeypatch):
    """The cache spelling has its own bait: a cache-SHAPED tree at the cwd.

    `cache_root=""` walked `.`, and the plugin glob is the only thing between
    the resolver and whatever the operator happened to be standing in.
    """
    cwd_cache = tmp_path / "cache-shaped"
    _framework_root(cwd_cache / "marketplace" / "three-pillars" / "1.2.0")
    monkeypatch.chdir(cwd_cache)

    with pytest.raises(SharedScriptNotFound):
        resolve_shared_script(
            NAME,
            cwd=_git_init(tmp_path / "consumer"),
            cache_root="",
            plugin_root=None,
            skill_dir=None,
            self_root=None,
        )


@pytest.mark.parametrize("spelling", ["", "."])
def test_the_env_derivation_gets_the_same_guard(bait, tmp_path, monkeypatch, spelling):
    """`$CLAUDE_PLUGIN_ROOT="."` is the HOST-set spelling of the same bug.

    The env branch guarded only the FALSY spelling (`if env_root else None`), so
    "." walked straight through to the probe. This is the production path — the
    variable is set by Claude Code, never by an in-repo caller — which is why it
    is exercised through the environment and not through the kwarg.
    """
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", spelling)

    with pytest.raises(SharedScriptNotFound):
        resolve_shared_script(
            NAME,
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=tmp_path / "no-cache",
            skill_dir=None,
            self_root=None,
        )


@pytest.mark.parametrize("param", ["plugin_root", "cache_root"])
def test_a_relative_root_still_resolves_and_returns_an_absolute_path(
    tmp_path, monkeypatch, param
):
    """A RELATIVE root names a real directory — and must answer absolutely.

    Anchoring is unchanged (the process cwd, exactly where `Path(root)/x` landed
    at stat time); what changes is that the ANSWER is absolute, as documented.
    """
    monkeypatch.chdir(tmp_path)
    if param == "plugin_root":
        install = _framework_root(tmp_path / "rel-install")
        kwargs = {"plugin_root": "rel-install", "cache_root": tmp_path / "no-cache"}
    else:
        install = _framework_root(
            tmp_path / "rel-cache" / "marketplace" / "three-pillars" / "1.2.0"
        )
        kwargs = {"plugin_root": None, "cache_root": "rel-cache"}

    # Spelled out for the same reason as above — no splat at a resolver call.
    result = resolve_shared_script(
        NAME,
        cwd=_git_init(tmp_path / "consumer"),
        cache_root=kwargs["cache_root"],
        plugin_root=kwargs["plugin_root"],
        skill_dir=None,
        self_root=None,
    )

    assert result.is_absolute(), f"{param}: relative answer {result}"
    assert result == install / "skills" / "_shared" / NAME


def test_every_root_valued_parameter_is_normalized():
    """STRUCTURAL: no root parameter may reach a probe unnormalized.

    This is the enumeration the per-parameter guard lacked. It fails two ways —
    a NEW root-valued parameter added to the signature (the first assertion),
    and an existing one that stops going through `_named_root` (the second) —
    so the sibling that kept the bug last time cannot appear unnoticed.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_shared_script"
    )
    declared = {arg.arg for arg in func.args.kwonlyargs}
    normalized = {
        arg.id
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_named_root"
        for arg in node.args
        if isinstance(arg, ast.Name)
    }

    assert declared == ROOT_PARAMS | {"cwd"}, (
        "the resolver grew or lost a keyword root — every root-valued one must "
        f"be listed in ROOT_PARAMS and normalized; got {sorted(declared)}"
    )
    assert ROOT_PARAMS <= normalized, (
        "root-valued parameters reaching a probe WITHOUT `_named_root`: "
        f"{sorted(ROOT_PARAMS - normalized)}"
    )


# --------------------------------------------------------------------------- #
# PR #144 R6 F2 — the normalizer must not REWRITE the path the caller named
# --------------------------------------------------------------------------- #
def test_a_trailing_space_names_its_own_root_not_the_sibling_without_one(tmp_path):
    """`<b>/ws ` and `<b>/ws` are DIFFERENT directories, and both may exist.

    `_named_root` used to `.strip()` every root-valued input before reading it
    as a path, which does not merely normalize whitespace — it REWRITES the
    basename. With both siblings present and qualifying, `plugin_root="<b>/ws "`
    returned the module out of `<b>/ws`: not a fail-closed miss, a silently
    DIFFERENT existing root. The resolver's headline contract is "never a wrong
    path", and a wrong path is exactly what came back.

    A trailing space is a legal POSIX basename, so the caller named a real
    directory and must get that one or nothing. Whitespace-ONLY inputs still
    collapse to "names no directory" — see the companion test below; that is
    what the strip was load-bearing for, and it is kept.
    """
    spaced = _framework_root(tmp_path / "ws ")  # trailing space IS the name
    plain = _framework_root(tmp_path / "ws")
    (spaced / "skills" / "_shared" / NAME).write_text("SPACE\n", encoding="utf-8")
    (plain / "skills" / "_shared" / NAME).write_text("NOSPACE\n", encoding="utf-8")

    result = resolve_shared_script(
        NAME,
        cwd=_git_init(tmp_path / "consumer"),
        cache_root=tmp_path / "no-cache",
        plugin_root=str(spaced),
        self_root=None,
    )

    assert Path(result).read_text(encoding="utf-8").strip() == "SPACE", (
        f"plugin_root={str(spaced)!r} resolved {result} — the normalizer "
        "rewrote the caller's basename and answered from a sibling root"
    )


@pytest.mark.parametrize("blank", ("   ", "\t", Path("   ")), ids=repr)
def test_a_whitespace_only_root_still_names_no_directory(bait, tmp_path, blank):
    """The half the strip WAS load-bearing for, kept and pinned on its own.

    `"   "` has non-empty `.parts`, so bullet 1's `.parts` guard alone cannot
    see it — without a whitespace check it becomes a RELATIVE root anchored on
    the process cwd, which `bait` makes a real framework root carrying `NAME`.
    That is the dot-anchor bug in another spelling, and `_named_root` must keep
    closing it now that it no longer strips the value it returns.
    """
    empty_cache = tmp_path / "empty-cache"
    empty_cache.mkdir()

    with pytest.raises(SharedScriptNotFound) as exc:
        resolve_shared_script(
            NAME,
            cwd=_git_init(tmp_path / "consumer"),
            cache_root=empty_cache,
            plugin_root=blank,
            self_root=None,
        )

    anchored = [rec for rec in exc.value.probe_report if rec[0] == "plugin-root"]
    assert not anchored, (
        f"plugin_root={blank!r} anchored a root the caller never named: {anchored}"
    )
