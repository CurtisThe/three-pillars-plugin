"""The three order inversions between resolve_root.sh and resolve_script.py.

Split out of ``test_resolve_script_parity.py`` (plan Task 4.2's refactor step)
when that module crossed the 300-line test soft-warn. The fixture builders stay
there — one definition of "a qualifying framework root" serves both the
agreement cases and these disagreement cases, and duplicating them is how the
two halves would quietly stop testing the same thing.

Run with: python -m pytest skills/_shared/test_resolve_script_parity_contention.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from resolve_script import resolve_shared_script  # noqa: E402
from test_resolve_script_parity import (  # noqa: E402
    NAME,
    _cache_root,
    _cached_framework,
    _framework_root,
    _real,
    _resolve_root_sh,
    _root_of,
)


# --------------------------------------------------------------------------- #
# Task 4.2 — the three order inversions, pinned two-sided
# --------------------------------------------------------------------------- #
# resolve_root.sh probes  plugin-root(1) > skill-dir(2) > cache(3) > toplevel(4)
# resolve_script.py probes toplevel(1) > plugin-root(2) > skill-dir(3) > self(4)
#                          > cache(5)
#
# Moving `toplevel` from LAST to FIRST inverts it against EVERY root that used
# to outrank it — three pairs, not one. Each case below stands up `toplevel`
# and one other root, both fully qualifying, and asserts BOTH sides: the shell
# resolver takes the non-toplevel root AND the python resolver takes toplevel.
# A one-sided assertion would still pass if the loser silently reordered, which
# is exactly the regression this pin exists to catch.
@pytest.mark.parametrize(
    "other", ["toplevel-vs-plugin-root", "toplevel-vs-skill-dir", "toplevel-vs-cache"]
)
def test_intentional_divergence(tmp_path, other):
    """Under contention, the two resolvers disagree — deliberately (design D1)."""
    home = tmp_path / "home"
    _cache_root(home).mkdir(parents=True)
    toplevel = _framework_root(tmp_path / "checkout", git=True)
    plugin_root = skill_dir = None

    if other == "toplevel-vs-plugin-root":
        expected_sh = plugin_root = _framework_root(tmp_path / "plugin-install")
    elif other == "toplevel-vs-skill-dir":
        expected_sh = _framework_root(tmp_path / "anchored")
        skill_dir = expected_sh / "skills" / "tp-foo"
        skill_dir.mkdir(parents=True)
    else:  # toplevel-vs-cache
        expected_sh = _cached_framework(home)

    sh = _resolve_root_sh(
        cwd=toplevel, home=home, plugin_root=plugin_root, skill_dir=skill_dir
    )
    assert sh.returncode == 0, sh.stderr
    assert _real(sh.stdout.strip()) == _real(expected_sh), (
        f"resolve_root.sh must still prefer {other.split('-vs-')[1]} over the "
        "git toplevel — its probe order is NOT edited by this design"
    )

    hit = resolve_shared_script(
        NAME,
        cwd=toplevel,
        cache_root=_cache_root(home),
        plugin_root=plugin_root,
        skill_dir=skill_dir,
        self_root=None,
    )
    assert _root_of(hit) == _real(toplevel), (
        "resolve_script.py must prefer the git toplevel — the live checkout is "
        "the CURRENT copy of a FREE module, which an anchored install can lag"
    )

    # The inversion itself: same inputs, different answers, on purpose.
    assert _root_of(hit) != _real(sh.stdout.strip())
