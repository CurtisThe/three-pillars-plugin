"""Root QUALIFICATION and WALL classification — `_framework_probe`'s two edges.

Split out at PR #144 round 4. `test_resolve_script_probe_report.py` owns the
`unreadable` tag as the CACHE walk produces it; this module owns the predicate
underneath it — what makes a directory a framework root at all, and which
`OSError` is a wall the operator can fix versus an absence they cannot.

Every case here exists because a MUTANT survived the suite. That is the whole
reason for the module: the three behaviours below were shipped with no test
that dies when they are reverted, and two of them additionally carried a
docstring claiming a parity pin that did not exist anywhere. A claimed pin is
worse than silence — it tells the next reader not to look.

Run with: python -m pytest skills/_shared/test_resolve_script_walls.py -q
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

NAME = "github_pr_author.py"
SHARED_REL = Path("skills") / "_shared"


# --------------------------------------------------------------------------- #
# Fixture builders — real trees only
# --------------------------------------------------------------------------- #
def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _plain_repo(root: Path) -> Path:
    """A git repo that is NOT a framework checkout — probe 1 misses."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(root)], check=True, capture_output=True
    )
    return root


def _framework_root(root: Path) -> Path:
    """A qualifying root: a REGULAR-FILE sentinel plus the module under test."""
    _write(root / SHARED_REL / "first-run.md", "# sentinel\n")
    _write(root / SHARED_REL / NAME, f"# copy at {root.name}\n")
    return root


def _call(tmp_path: Path, *, plugin_root=None, self_root=None):
    """``resolve_shared_script`` with every AMBIENT root denied (design D3).

    cwd is a plain, sentinel-less git repo; the cache root exists but is empty;
    ``self_root=None`` opts out of the dogfood checkout this suite runs inside
    — without it every case here would pass on the LIVE repo copy instead of
    on the tree it built. Both ambient kwargs are spelled out AT the call, not
    filled in by ``setdefault``: ``test_resolve_script_hermeticity.py``'s AST
    sweep reads the call site, and a default folded in behind its back is
    exactly the opt-out-by-accident that sweep exists to reject.
    """
    cache = tmp_path / "empty-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return resolve_shared_script(
        NAME,
        cwd=_plain_repo(tmp_path / "consumer"),
        cache_root=cache,
        plugin_root=plugin_root,
        self_root=self_root,
    )


# --------------------------------------------------------------------------- #
# B1 — the sentinel must be a REGULAR FILE, not merely a name that stats
# --------------------------------------------------------------------------- #
def test_dir_sentinel_is_not_a_root(tmp_path):
    """A tree whose ``first-run.md`` is a DIRECTORY must NOT qualify.

    ``_framework_probe`` descends with ``os.stat``, which succeeds on a
    directory exactly as it does on a file — so ``stat.S_ISREG`` is the ONLY
    thing separating a framework root from a tree that merely has the right
    path spelled out, and it is the ONLY qualification an override root gets.
    ``resolve_root.sh`` requires ``[ -f ]``; without the shape check
    ``resolve_shared_script`` RETURNS A PATH out of the impostor instead of
    raising — a wrong install answering at exit 0, silently.

    Mutant-verified: reverting to ``return True, None`` left the entire suite
    green before this case existed. It now fails here, twice over.
    """
    impostor = tmp_path / "impostor"
    (impostor / SHARED_REL / "first-run.md").mkdir(parents=True)  # a DIRECTORY
    _write(impostor / SHARED_REL / NAME, "# impostor copy\n")

    assert resolve_script._framework_probe(impostor) == (False, None), (
        "a directory-shaped sentinel qualified the root"
    )
    with pytest.raises(SharedScriptNotFound) as exc:
        _call(tmp_path, plugin_root=impostor)
    assert ("plugin-root", str(impostor / SHARED_REL), "miss") in exc.value.probe_report


def test_regular_file_sentinel_control_still_qualifies(tmp_path):
    """CONTROL: the same tree with a FILE sentinel qualifies and answers.

    Without this the case above would pass on a resolver that had stopped
    qualifying override roots at all.
    """
    real = _framework_root(tmp_path / "real")

    assert resolve_script._framework_probe(real) == (True, None)
    assert _call(tmp_path, plugin_root=real) == real / SHARED_REL / NAME


# --------------------------------------------------------------------------- #
# B2 — ONLY a permission error is a WALL; every other OSError is absence
# --------------------------------------------------------------------------- #
def test_looped_skills_is_a_miss_not_a_wall(tmp_path):
    """A root whose ``skills/`` is a symlink LOOP is a MISS, with no wall record.

    The errno split is load-bearing prose, not a stylistic choice. Under the
    round-2 spelling (``except (FileNotFoundError, NotADirectoryError)`` ->
    ``None`` / ``except OSError`` -> ``cursor``), an ELOOP — errno 40, neither
    of the two named classes — falls through to the wall arm: the probe goes
    ``(False, None)`` to ``(False, <root>)``, and ``probe_report`` goes from
    ONE ``'miss'`` to TWO ``'unreadable'`` records naming a directory the
    operator CANNOT chmod their way out of. That is the R5 "name the wrong
    dir" lie, reintroduced silently: the reader is sent to fix permissions on
    a root whose permissions are fine.

    Mutant-verified: restoring the round-2 spelling left the whole suite green
    before this case existed.
    """
    looped = tmp_path / "looped"
    looped.mkdir()
    (looped / "skills").symlink_to(looped / "skills", target_is_directory=True)

    assert resolve_script._framework_probe(looped) == (False, None), (
        "a symlink loop was classified as a wall the operator can chmod"
    )
    with pytest.raises(SharedScriptNotFound) as exc:
        _call(tmp_path, plugin_root=looped)

    report = exc.value.probe_report
    assert ("plugin-root", str(looped / SHARED_REL), "miss") in report, (
        f"the looped root must be RECORDED as a plain miss (D5): {report}"
    )
    assert not [entry for entry in report if entry[2] == "unreadable"], (
        f"an ELOOP root produced a wall record naming a chmod-able dir: {report}"
    )


# --------------------------------------------------------------------------- #
# B3 — the threaded wall must work for the NAMED roots, not just the cache
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses mode bits — chmod 0o000 is not unreadable for uid 0",
)
def test_walled_self_root_is_tagged_unreadable_and_names_the_wall(tmp_path, monkeypatch):
    """A WALLED probe-4 root is reported ``unreadable``, naming the dir to chmod.

    Every ``'unreadable'`` assertion the suite had before this case was
    ``('cache', ...)``, which left TWO mutants alive at once, and this single
    case kills both:

    (a) narrowing ``_probe``'s wall block to ``if wall is not None and source
        == "cache":``. A NAMED root whose ``skills/`` is ``chmod 0o000`` then
        drops from two ``'unreadable'`` records to a single ``'miss'`` — the R5
        lie told about an override root the caller pointed at on purpose.
    (b) reverting ``_self_root``'s ``if qualified or wall is not None:`` to
        ``if qualified:``. A walled ancestor of ``__file__`` then vanishes from
        ``probe_report`` ENTIRELY: the walk climbs straight past the install
        the resolver is sitting in and reports nothing about it.

    ``__file__`` is pointed at a file directly under the install root so that
    the walk's FIRST candidate is that root — anything walled at or above
    ``<root>/skills`` also walls the intermediate ``skills/_shared`` the real
    resolver lives in, which would make the wall belong to a directory that is
    not the one to fix.
    """
    root = _framework_root(tmp_path / "install")
    monkeypatch.setattr(resolve_script, "__file__", str(root / "resolve_script.py"))
    wall = root / "skills"
    wall.chmod(0o000)
    try:
        assert resolve_script._self_root() == root, (
            "a walled ancestor of __file__ is probe 4's root — it did not MISS"
        )
        with pytest.raises(SharedScriptNotFound) as exc:
            _call(tmp_path, self_root=resolve_script._UNSET)
        report = exc.value.probe_report
    finally:
        wall.chmod(0o755)

    assert ("self", str(root / SHARED_REL), "unreadable") in report, (
        f"the walled probe-4 root was not tagged unreadable: {report}"
    )
    assert ("self", str(wall), "unreadable") in report, (
        f"the report does not NAME {wall}, the dir the operator must chmod: {report}"
    )
