"""Hermeticity of the resolve_script suite (design: resolve-script-override-roots).

Two complementary properties, and they only mean something together:

* **The convention is HELD** — ``test_every_call_site_declares_self_root``
  reads the shipped test sources and asserts every ``resolve_shared_script(``
  call names ALL THREE ambient opt-outs — ``cwd=``, ``self_root=`` and
  ``plugin_root=`` (``AMBIENT_KWARGS``). A structural meta-test: no mocks, no
  monkeypatching, no transcription of the call sites into this file.
* **The convention is NECESSARY** — ``test_canary_without_self_root_resolves_
  real_repo`` is the negative control. A meta-test alone proves only that
  everybody follows a rule; the canary proves what breaks when they stop.

The ``plugin_root`` half has a third leg: unlike ``self_root`` it also has a
repo-wide safety net, conftest.py's autouse ``_strip_ambient_plugin_root``. A
net nothing tests is a net nobody notices tearing, so
``test_autouse_fixture_strips_the_ambient_plugin_root`` pins it directly —
with a negative control, because the positive case is vacuous on a machine
that never had ``$CLAUDE_PLUGIN_ROOT`` set in the first place.

Run with: python -m pytest skills/_shared/test_resolve_script_hermeticity.py -q
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from resolve_script import _self_root, resolve_shared_script  # noqa: E402

NAME = "github_pr_author.py"

#: Modules the meta-test scans. Globbed, never listed by hand, so a test module
#: added later cannot quietly escape the sweep.
SCAN_GLOB = "test_resolve_script*.py"

#: THIS module is the one deliberate exception, and it must stay one.
#: ``test_canary_without_self_root_resolves_real_repo`` OMITS ``self_root=`` on
#: purpose — that omission IS the negative control. A naive whole-glob scan
#: would therefore fail on its own canary. Do NOT "fix" that by adding
#: ``self_root=`` to the canary; you would delete the only evidence that the
#: convention is load-bearing rather than decorative.
EXCLUDED = frozenset({Path(__file__).name})

#: The AST predicates this sweep is BUILT ON live in
#: ``test_resolve_script_sweep.py``, together with their own unit tests (a
#: positive case, a negative control and a mutant-verified evader each). They
#: are imported rather than duplicated so this meta-test judges the same rule
#: those tests judge — a transcribed copy is how a guard and its own tests
#: drift into agreeing about the wrong thing.
from test_resolve_script_sweep import (  # noqa: E402
    AMBIENT_ENV_ALLOWLIST,
    EXEMPT_CALL_BUDGET,
    PLUGIN_ROOT_ENV,
    SYMBOL,
    _bare_references,
    _calls,
    _enclosing_functions,
    _offenders,
)

_DEV_ROOT = Path(__file__).resolve().parents[2]
_needs_conftest = pytest.mark.skipif(
    not (_DEV_ROOT / "skills/_shared/conftest.py").exists(),
    reason="copies the dev-only conftest.py (dev-repo only)")


def _scanned_sources() -> list[tuple[Path, str]]:
    """Every in-scope test module as ``(path, source text)`` — read, not imported."""
    return [
        (path, path.read_text(encoding="utf-8"))
        for path in sorted(HERE.glob(SCAN_GLOB))
        if path.name not in EXCLUDED
    ]


# --------------------------------------------------------------------------- #
# Task 2.1 — the structural meta-test
# --------------------------------------------------------------------------- #
def test_every_call_site_declares_self_root():
    """Every scanned ``resolve_shared_script(`` call names every ``AMBIENT_KWARGS``.

    Scope note (audit finding 1): the scan is the whole
    ``test_resolve_script*.py`` glob MINUS this module — see ``EXCLUDED``.

    Predicate note (audit finding 6): the assertion is PRESENCE of the keyword,
    never the VALUE bound to it. A value check ("must be ``None`` or an
    allowlisted self-probe expression") would reject
    ``test_resolve_script_roots.py``'s ``[self]`` isolation case, which
    legitimately passes a real ``tmp_path`` root.

    PR #144 R6 — what presence-only COSTS, and why it is still right. Presence
    is sound exactly while ``None`` WITHHOLDS every ambient root. ``cwd`` broke
    that for one round: its default was ``None`` and ``None`` meant "derive the
    process cwd", so ``cwd=None`` satisfied this predicate while handing probe 1
    the dogfood repo. The fix was in the RESOLVER (``cwd`` takes ``_UNSET`` like
    its two siblings), not a value check here, so the finding-6 latitude above
    survives intact. Pinned end to end in ``test_resolve_script_roots.py`` by
    ``test_cwd_none_withholds_probe_1_like_every_other_ambient_root``.

    Aliasing note (impl-audit rework): the textual-occurrence watchdog that
    used to back this pass was evadable by a one-line alias, so it was replaced
    by ``_bare_references`` — every AST reference to the symbol must sit in a
    ``Call.func`` position.

    No call-site COUNT is asserted (audit finding 5): a literal count is a
    maintenance trap and would become a false acceptance gate. This test is the
    acceptance criterion, and it is count-agnostic.
    """
    sources = _scanned_sources()
    assert sources, f"no test modules matched {SCAN_GLOB!r} — the sweep is vacuous"

    offenders: list[str] = []
    total = 0
    for path, source in sources:
        tree = ast.parse(source)
        calls = _calls(tree)
        # Aliasing guard (impl-audit rework). The AST pass is the predicate; a
        # reference to the symbol OUTSIDE a Call.func slot means it was bound to
        # another name and escaped the sweep. This replaced a textual-occurrence
        # watchdog that agreed with the AST pass at zero on exactly the aliased
        # call it was meant to catch.
        aliased = _bare_references(tree)
        assert not aliased, (
            f"{path.name}: {SYMBOL} referenced outside a call at line(s) "
            f"{aliased} — binding the resolver to another name (alias, "
            f"functools.partial, a dict/list of callables) escapes the "
            f"self_root= sweep. Call it directly."
        )
        total += len(calls)
        offenders.extend(_offenders(path.name, tree))

    assert total, "scanned modules contain no resolve_shared_script() call at all"
    assert not offenders, (
        "resolve_shared_script() call sites without an explicit ambient opt-out: "
        + ", ".join(offenders)
        + " — `cwd`, `self_root` and `plugin_root` ALL derive from the real "
          "machine when OMITTED, and it really does carry github_pr_author.py, "
          "so omitting ANY OF THE THREE makes a case pass for the wrong reason. "
          "Naming one `None` withholds that root: same meaning for all three"
    )


def test_the_ambient_env_exemption_is_spent_exactly_where_declared():
    """The allowlist grants EXACTLY the declared exemptions, no more, no fewer.

    The allowlist keys on ``(module, function)``, which nothing can satisfy by
    WRITING the environment — that is the class closure. What a per-function
    key alone cannot see is an extra un-opted-out call added INSIDE one of the
    named functions (evader E1's shape, moved indoors), so the SPEND is counted
    here against ``EXEMPT_CALL_BUDGET``.

    The same walk catches a STALE entry from the other side: a renamed or
    deleted allowlisted test spends nothing, so the declared set and the
    observed set stop matching and this fails rather than leaving a dead
    exemption on the books.
    """
    spent: dict[tuple[str, str], int] = {}
    for path, source in _scanned_sources():
        tree = ast.parse(source)
        functions = _enclosing_functions(tree)
        for call in _calls(tree):
            key = (path.name, functions.get(id(call)))
            if key in AMBIENT_ENV_ALLOWLIST:
                spent[key] = spent.get(key, 0) + 1

    assert set(spent) == set(AMBIENT_ENV_ALLOWLIST), (
        "AMBIENT_ENV_ALLOWLIST entries that exempt NOTHING (renamed or deleted "
        f"tests): {sorted(set(AMBIENT_ENV_ALLOWLIST) - set(spent))}"
    )
    assert sum(spent.values()) == EXEMPT_CALL_BUDGET, (
        "the ambient-env exemption is spent on more calls than declared — an "
        "un-opted-out call was added inside an allowlisted function: "
        f"{sorted(spent.items())} vs budget {EXEMPT_CALL_BUDGET}"
    )


# --------------------------------------------------------------------------- #
# PR #144 S5 — the autouse fixture is LOAD-BEARING, so pin that it works
# --------------------------------------------------------------------------- #
#: The inner probe. Run under a copy of the real conftest.py with
#: $CLAUDE_PLUGIN_ROOT SET in the environment: if the autouse fixture strips it,
#: this passes; if the fixture is gone, it fails. That asymmetry is the test.
_ENV_PROBE = (
    "import os\n"
    "def test_ambient_var_is_stripped():\n"
    f"    assert {PLUGIN_ROOT_ENV!r} not in os.environ\n"
)


def _run_probe(directory: Path) -> subprocess.CompletedProcess:
    """Run the inner probe in ``directory`` with ``$CLAUDE_PLUGIN_ROOT`` SET."""
    (directory / "test_env_probe.py").write_text(_ENV_PROBE, encoding="utf-8")
    env = dict(os.environ)
    env[PLUGIN_ROOT_ENV] = str(directory / "ambient-install")
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(directory), "-q", "-p", "no:randomly",
         "-p", "no:xdist", "-p", "no:cacheprovider"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(directory),
    )


@_needs_conftest
def test_autouse_fixture_strips_the_ambient_plugin_root(tmp_path):
    """conftest.py's `_strip_ambient_plugin_root` really does remove the var.

    15 call sites in test_resolve_script.py used to lean ENTIRELY on this
    fixture for their `plugin-root` hermeticity, and nothing tested the fixture
    itself. Deleting it on a machine with $CLAUDE_PLUGIN_ROOT set (which Claude
    Code sets inside a plugin session) silently handed those cases a real,
    populated framework install — the D3 failure, on the other ambient root.
    """
    with_conftest = tmp_path / "with_conftest"
    with_conftest.mkdir()
    shutil.copy(HERE / "conftest.py", with_conftest / "conftest.py")
    # conftest.py imports its sibling git_env (hook-inherited-git-env).
    shutil.copy(HERE / "git_env.py", with_conftest / "git_env.py")

    proc = _run_probe(with_conftest)

    assert proc.returncode == 0, (
        "the autouse fixture did NOT strip $CLAUDE_PLUGIN_ROOT:\n" + proc.stdout
    )


def test_env_probe_fails_without_the_conftest(tmp_path):
    """Negative control — WITHOUT conftest.py the same probe must FAIL.

    Without this, the test above would pass on a machine that simply never had
    $CLAUDE_PLUGIN_ROOT set, proving nothing. This half proves the variable was
    genuinely present and that the fixture is what removed it.
    """
    bare = tmp_path / "bare"
    bare.mkdir()

    proc = _run_probe(bare)

    assert proc.returncode != 0, (
        "the probe passed with NO conftest.py — $CLAUDE_PLUGIN_ROOT was never "
        "set, so the positive case above is vacuous:\n" + proc.stdout
    )
    # A non-zero exit alone is too weak: a collection error or a missing pytest
    # would satisfy it while proving nothing. Pin that the PROBE ITSELF failed.
    assert "1 failed" in proc.stdout, proc.stdout
    assert "test_ambient_var_is_stripped" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------- #
# Task 2.2 — the negative control
# --------------------------------------------------------------------------- #
def _plain_repo(root: Path) -> Path:
    """A git repo WITHOUT the framework sentinel — the ``toplevel`` probe misses."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(root)], check=True, capture_output=True
    )
    return root


def test_canary_without_self_root_resolves_real_repo(tmp_path):
    """OMITTING ``self_root=`` silently resolves the REAL repo copy.

    THIS IS THE FAILURE MODE ``self_root=None`` PREVENTS, and it is the reason
    this module is excluded from its own meta-test's scan (see ``EXCLUDED``).

    The scenario is the one ~10 existing cases exercise: an empty cache and a
    cwd that is a plain git repo, not a framework checkout. Every root is
    explicitly absent EXCEPT ``self_root``, which is left to its ambient
    default. On any dogfood machine that default is the live checkout — which
    really does carry ``github_pr_author.py`` — so the call succeeds against a
    path no fixture created. A cache-fallback assertion written that way passes
    for entirely the wrong reason, and would keep passing with the cache walk
    deleted.

    The meta-test proves the convention is HELD. This proves it is NECESSARY.
    """
    if _self_root() is None:
        pytest.skip("this resolver install has no framework-root ancestor")

    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()
    consumer = _plain_repo(tmp_path / "consumer")

    # NOTE: no `self_root=` — deliberately. Do not "fix" this call.
    result = resolve_shared_script(
        NAME, cwd=consumer, cache_root=empty_cache, plugin_root=None, skill_dir=None
    )

    assert Path(result).resolve() == (HERE / NAME).resolve(), (
        "the ambient `self` root should have resolved the live repo copy; got "
        f"{result}"
    )
