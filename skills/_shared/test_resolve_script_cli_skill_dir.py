"""The ``--skill-dir`` CLI contract — value handling and anchor resolution.

Split out of ``test_resolve_script_cli.py`` at PR #144 R4, which pushed that
module past the 500-line hard cap. The split is by responsibility, not by size
alone: ``test_resolve_script_cli.py`` owns the CLI's GENERAL contract (path on
stdout, diagnostic on stderr, the exit 0/1/2 codes, arity, unknown flags, and
the bare-basename rule on ``<name>``), while this module owns ONE flag —
``--skill-dir`` — and the question of which root, if any, its value anchors.

That question has its own failure family, and every member of it is a SILENT
WRONG PATH rather than a crash: an empty value anchoring the grandparent of the
process cwd (S8), a following flag swallowed as the value (S8), and two
different symlink-loop shapes, one that raises and one that collapses lexically
PAST the loop (round 1, and R4).

The fixture builders are IMPORTED from the sibling module rather than
duplicated, the same way ``test_resolve_script_parity_contention.py`` imports
from ``test_resolve_script_parity.py``: they are the CLI subprocess harness
itself, and two copies of ``_run_cli`` would be two chances to drift on which
ambient variables a case is hermetic against.

Run with: python -m pytest skills/_shared/test_resolve_script_cli_skill_dir.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_resolve_script_cli import (  # noqa: E402
    MODULE_PATH,
    _anchored_repo,
    _framework_repo,
    _neutral_resolver,
    _plain_repo,
    _run_cli,
    _same,
    _write,
)

NAME = "github_pr_author.py"


# --------------------------------------------------------------------------- #
# Task 3.1 — the --skill-dir CLI contract (parity with resolve_root.sh)
# --------------------------------------------------------------------------- #
def test_skill_dir_happy_path(tmp_path):
    """--skill-dir <dir> <name> → exit 0, the anchored install's copy on stdout.

    Every other root is denied: cwd is a plain (sentinel-less) repo, $HOME has
    no cache, and the resolver runs from a neutral copy so probe 4 (self) is
    None. The only way to reach a path is through the flag.
    """
    name = "github_pr_author.py"
    skill_dir = _anchored_repo(tmp_path / "anchored", name)
    consumer = _plain_repo(tmp_path / "consumer")
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_cli(
        ["--skill-dir", str(skill_dir), name],
        cwd=consumer,
        home=home,
        script=_neutral_resolver(tmp_path),
    )

    assert proc.returncode == 0, proc.stderr
    assert _same(
        proc.stdout.strip(), skill_dir.parent.parent / "skills" / "_shared" / name
    )


def test_skill_dir_missing_value_exits_2(tmp_path):
    """--skill-dir with no value → exit 2, naming the flag (not a bare usage)."""
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    proc = _run_cli(["--skill-dir"], cwd=cwd, home=home)

    assert proc.returncode == 2
    assert proc.stdout.strip() == ""
    # Mirrors resolve_root.sh's "--skill-dir requires a value". The predicate is
    # "requires a value", NOT "--skill-dir": the generic _USAGE string CONTAINS
    # the flag, so asserting on the flag name cannot distinguish this diagnostic
    # from a bare usage dump — two mutants survived it (silently accepting "" as
    # a value, and deleting --skill-dir from _USAGE). Its sibling
    # test_unknown_flag_exits_2 already keys on "unknown" for exactly this reason.
    assert "requires a value" in proc.stderr


# --------------------------------------------------------------------------- #
# PR #144 S8 — an EMPTY --skill-dir is UNSET, and a flag is not a value
# --------------------------------------------------------------------------- #
def test_empty_skill_dir_does_not_outrank_the_cache(tmp_path):
    """The same trap, with NO git toplevel — the cache must win outright.

    Here probe 1 cannot mask the bug: cwd is outside any git repo, so if the
    empty --skill-dir still anchors a root, that root is the only thing that
    can resolve and the cache copy loses.
    """
    name = "github_pr_author.py"
    # A framework repo whose GRANDCHILD is the cwd — the path `Path("")/../..`
    # would resolve to, if the empty value were still treated as real.
    outer = tmp_path / "outer"
    _write(outer / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    trap = _write(outer / "skills" / "_shared" / name, "# TRAP grandparent copy\n")
    cwd = outer / "skills" / "tp-foo"
    cwd.mkdir(parents=True, exist_ok=True)  # NOT a git repo

    home = tmp_path / "home"
    shared = (
        home / ".claude" / "plugins" / "cache" / "marketplace"
        / "three-pillars" / "1.2.0" / "skills" / "_shared"
    )
    _write(shared / "first-run.md", "# sentinel\n")
    cache_copy = _write(shared / name, "# cache\n")

    proc = _run_cli(
        ["--skill-dir", "", name],
        cwd=cwd,
        home=home,
        script=_neutral_resolver(tmp_path),
    )

    assert proc.returncode == 0, proc.stderr
    assert _same(proc.stdout.strip(), cache_copy), (
        f"an empty --skill-dir anchored {trap}'s root and outranked the cache"
    )


def test_skill_dir_value_may_not_be_a_flag(tmp_path):
    """`--skill-dir --bogus x.py` must NOT swallow the flag as the value.

    It used to: `--bogus` became the anchor, so a typo'd flag turned into a
    silent explicit root instead of the exit-2 an unknown flag earns.
    """
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    proc = _run_cli(["--skill-dir", "--bogus", "github_pr_author.py"], cwd=cwd, home=home)

    assert proc.returncode == 2
    assert proc.stdout.strip() == ""
    assert "requires a value" in proc.stderr


def test_symlink_loop_skill_dir_exits_1_not_a_traceback(tmp_path):
    """A self-referential --skill-dir degrades to a recorded miss, not a crash.

    `Path.resolve()` raises RuntimeError on a symlink loop — NOT OSError — so
    an OSError-only guard lets it escape as a bare traceback and the process
    exits 1 with a Python stack on stderr instead of the documented fail-loud
    diagnostic. Exit 1 is right (nothing resolved); the diagnostic is what
    distinguishes "answered loudly" from "died".
    """
    loop = tmp_path / "loop"
    loop.symlink_to(loop)  # self-referential: resolve() cannot terminate
    # The real flag shape is `--skill-dir <root>/skills/<skill>`, so the loop
    # sits MID-PATH in `<skill_dir>/../..`. That matters: a trailing `../..`
    # directly after the loop cancels it lexically and resolve() succeeds, so a
    # bare `--skill-dir <loop>` would not reach the RuntimeError at all.
    skill_dir = loop / "skills" / "tp-foo"
    home = tmp_path / "home"
    home.mkdir()
    cwd = _plain_repo(tmp_path / "consumer")

    proc = _run_cli(
        ["--skill-dir", str(skill_dir), "github_pr_author.py"],
        cwd=cwd,
        home=home,
        script=_neutral_resolver(tmp_path),
    )

    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr, (
        f"the symlink loop escaped as a traceback:\n{proc.stderr}"
    )
    assert "not found in any candidate root" in proc.stderr
    # The unresolvable anchor is still NAMED, not silently dropped.
    assert str(loop) in proc.stderr


# --------------------------------------------------------------------------- #
# PR #144 R4 — the OTHER loop shape: `<dir>/../..` collapses PAST the loop
# --------------------------------------------------------------------------- #
def _loop_trap(tmp_path, name):
    """Return (skill_dir, trap_root, cache_copy) for the collapse-past-loop shape.

    The twin above puts the loop MID-PATH, where `.resolve()` genuinely raises.
    THIS shape is the sibling it left open: with the loop as the LAST component,
    `Path('<loop>/../..').resolve()` collapses the two `..` LEXICALLY on 3.12 and
    returns `trap_root` instead of raising — so an explicit override gets
    anchored on a directory the caller never named. `trap_root` carries the
    sentinel AND `name`, so if the probe anchors there it WINS, at exit 0.
    """
    trap_root = tmp_path / "trap"
    _write(trap_root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    _write(trap_root / "skills" / "_shared" / name, "# TRAP collapsed-anchor copy\n")
    sub = trap_root / "sub"
    sub.mkdir(parents=True, exist_ok=True)
    # A mutual loop, not a self-symlink: `<sub>/loopa` must be the LAST
    # component of the --skill-dir value for the collapse to be reachable.
    (sub / "loopa").symlink_to(sub / "loopb", target_is_directory=True)
    (sub / "loopb").symlink_to(sub / "loopa", target_is_directory=True)

    home = tmp_path / "home"
    shared = (
        home / ".claude" / "plugins" / "cache" / "marketplace"
        / "three-pillars" / "1.2.0" / "skills" / "_shared"
    )
    _write(shared / "first-run.md", "# sentinel\n")
    return sub / "loopa", trap_root, _write(shared / name, "# cache\n")


def test_named_skill_dir_at_that_depth_does_anchor(tmp_path):
    """CONTROL: a REAL dir where the loop sits anchors `trap_root` and wins.

    Without this the case below would pass on a resolver that had simply lost
    the skill-dir probe — the trap has to be reachable to be a trap.
    """
    name = "github_pr_author.py"
    skill_dir, trap_root, _cache = _loop_trap(tmp_path, name)
    real = skill_dir.parent / "real"
    real.mkdir()

    proc = _run_cli(
        ["--skill-dir", str(real), name],
        cwd=_plain_repo(tmp_path / "consumer"),
        home=tmp_path / "home",
        script=_neutral_resolver(tmp_path),
    )

    assert proc.returncode == 0, proc.stderr
    assert _same(proc.stdout.strip(), trap_root / "skills" / "_shared" / name)


def test_symlink_loop_as_last_component_fails_closed(tmp_path):
    """A --skill-dir ending in a loop anchors NOTHING — it does not collapse past it.

    `resolve_root.sh` returns empty for the same input (`cd` fails) and skips
    its probe; this must match. Failing OPEN here is worse than a crash: the
    resolver would hand back `<some-dir>/skills/_shared/<name>` at exit 0, from
    a root the caller never named and never saw.
    """
    name = "github_pr_author.py"
    skill_dir, trap_root, cache_copy = _loop_trap(tmp_path, name)

    proc = _run_cli(
        ["--skill-dir", str(skill_dir), name],
        cwd=_plain_repo(tmp_path / "consumer"),
        home=tmp_path / "home",
        script=_neutral_resolver(tmp_path),
    )

    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert _same(proc.stdout.strip(), cache_copy), (
        f"the loop collapsed past itself and anchored {trap_root}; stdout was "
        f"{proc.stdout.strip()!r}"
    )
    assert str(trap_root / "skills") not in proc.stdout


# --------------------------------------------------------------------------- #
# PR #144 round 4 (A1) — a fail-closed --skill-dir must not EVICT probe 4
# --------------------------------------------------------------------------- #
def _dogfood_loop_install(tmp_path, name):
    """(skill_dir, resolver, correct_copy, decoy_copy) for the eviction shape.

    The shape a real skill passes: ``--skill-dir <install>/skills/<skill>``,
    where ``<install>`` is the very root the resolver was installed into. So
    the fail-closed skill-dir probe and probe 4 (``self``) name ONE physical
    root — and if the first claims the dedupe slot, the second never runs and
    a decoy PRO cache copy wins. ``<skill>`` is a mutual symlink loop, the same
    ``_loop_trap`` shape, because that is what makes the probe fail closed.
    """
    install = tmp_path / "install"
    _write(install / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    correct = _write(install / "skills" / "_shared" / name, "# CORRECT install\n")
    resolver = _write(
        install / "skills" / "_shared" / "resolve_script.py",
        MODULE_PATH.read_text(encoding="utf-8"),
    )
    skills = install / "skills"
    (skills / "loopa").symlink_to(skills / "loopb", target_is_directory=True)
    (skills / "loopb").symlink_to(skills / "loopa", target_is_directory=True)
    # A PRO-flavoured cache: sentinel-qualified, carries the name, WRONG copy.
    decoy = (
        tmp_path / "home" / ".claude" / "plugins" / "cache" / "marketplace"
        / "three-pillars-pro" / "1.2.0" / "skills" / "_shared"
    )
    _write(decoy / "first-run.md", "# sentinel\n")
    return skills / "loopa", resolver, correct, _write(decoy / name, "# DECOY\n")


def test_unresolvable_skill_dir_control_decoy_cache_is_reachable(tmp_path):
    """CONTROL: with the install's own copy gone, the decoy cache DOES win.

    Without this the case below would pass on a resolver that had simply lost
    the cache probe — the decoy has to be reachable to be a decoy.
    """
    skill_dir, resolver, correct, decoy = _dogfood_loop_install(tmp_path, NAME)
    correct.unlink()

    proc = _run_cli(
        ["--skill-dir", str(skill_dir), NAME],
        cwd=_plain_repo(tmp_path / "outside"),
        home=tmp_path / "home",
        script=resolver,
    )

    assert proc.returncode == 0, proc.stderr
    assert _same(proc.stdout.strip(), decoy)


def test_unresolvable_skill_dir_does_not_evict_the_self_probe(tmp_path):
    """A fail-closed --skill-dir must not claim probe 4's dedupe slot.

    ``_probe`` used to ``seen.add`` the root BEFORE the fail-closed
    short-circuit, so an ELOOP ``--skill-dir`` POISONED the dedupe set for the
    same physical root: probe 4 (``self``) never ran, never appeared in
    ``probe_report``, and the decoy PRO cache copy won at exit 0. That is a
    SILENT WRONG PATH — the PR #126 wrong-install class this resolver exists to
    prevent — and it violates "the FIRST EXISTING root wins". The same call
    WITHOUT the flag already returned the right copy, which is the tell.
    """
    skill_dir, resolver, correct, _decoy = _dogfood_loop_install(tmp_path, NAME)

    proc = _run_cli(
        ["--skill-dir", str(skill_dir), NAME],
        cwd=_plain_repo(tmp_path / "outside"),
        home=tmp_path / "home",
        script=resolver,
    )

    assert proc.returncode == 0, proc.stderr
    assert _same(proc.stdout.strip(), correct), (
        "the unresolvable --skill-dir evicted probe 4 and a cache copy won; "
        f"stdout was {proc.stdout.strip()!r}"
    )
    assert "three-pillars-pro" not in proc.stdout


def test_unresolvable_skill_dir_is_still_recorded(tmp_path):
    """D5 is not traded away for A1: the fail-closed probe stays in the report.

    Freeing the dedupe slot must not also free the RECORD — an operator who
    named a --skill-dir that resolved to nothing has to see that they did.
    One line, not two: the skill-dir and self probes name one physical root,
    and ``test_symlinked_duplicate_root_reported_once`` pins that as one entry.
    """
    skill_dir, resolver, _correct, _decoy = _dogfood_loop_install(tmp_path, NAME)
    install_shared = skill_dir.parent / "_shared"

    proc = _run_cli(
        ["--skill-dir", str(skill_dir), "absent_module.py"],
        cwd=_plain_repo(tmp_path / "outside"),
        home=tmp_path / "home",
        script=resolver,
    )

    assert proc.returncode == 1, proc.stdout
    tagged = [
        line for line in proc.stderr.splitlines()
        if str(install_shared) in line and "[skill-dir: miss]" in line
    ]
    assert len(tagged) == 1, (
        f"expected exactly one [skill-dir: miss] line naming {install_shared}, "
        f"got:\n{proc.stderr}"
    )
