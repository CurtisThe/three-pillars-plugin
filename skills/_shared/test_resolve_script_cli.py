"""Tests for resolve_script.py's thin CLI — plan Task 1.3.

The CLI contract MIRRORS resolve_root.sh's: the resolved absolute path on
stdout + exit 0; the fail-loud diagnostic (naming probed roots) on stderr +
exit 1; a wrong-arity call exits 2 with a usage line. The CLI reads ``$HOME``
for the cache root and ``os.getcwd()`` for cwd — so every case drives it via a
subprocess with an injected ``cwd=`` and ``HOME=`` fixture; the real machine
cache is never touched.

Run with: python -m pytest skills/_shared/test_resolve_script_cli.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
MODULE_PATH = HERE / "resolve_script.py"


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _framework_repo(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    _write(root / "skills" / "_shared" / "first-run.md", "# sentinel\n")
    _write(root / "skills" / "_shared" / name, "# dogfood\n")
    return root


def _plain_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    return root


def _neutral_resolver(tmp_path: Path) -> Path:
    """A copy of the resolver that has NO framework-root ancestor.

    Probe 4 (``self``) resolves off the root the RESOLVER ITSELF lives in, and
    the CLI has no ``self_root=None`` opt-out — a kwarg cannot cross a
    subprocess boundary. So a case about a LOWER-precedence root has to get its
    hermeticity from WHERE the script is run: from here, ``_self_root()``
    returns ``None`` and probe 4 drops out, exactly as it does on a consumer
    machine whose install is the cache copy under test.
    """
    target = tmp_path / "install" / "resolve_script.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(MODULE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _anchored_repo(root: Path, name: str, skill: str = "tp-foo") -> Path:
    """A framework install reachable ONLY via --skill-dir; returns the skill dir.

    ``<skill_dir>/../..`` is the framework root, mirroring resolve_root.sh's
    probe 2. The repo is deliberately NOT the cwd and NOT on the cache path, so
    a resolution that lands here can only have come through the flag.
    """
    _framework_repo(root, name)
    skill_dir = root / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir


def _run_cli(args, *, cwd: Path, home: Path, script: Path = None):
    env = dict(os.environ)
    env["HOME"] = str(home)
    # Probe 2 (plugin-root) reads $CLAUDE_PLUGIN_ROOT from the AMBIENT env. If
    # the developer running the suite has it set, it would outrank every root
    # these cases construct — so drop it, the same hermeticity opt-out the
    # in-process tests get from ``plugin_root=None``.
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    return subprocess.run(
        [sys.executable, str(script or MODULE_PATH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


def _same(a, b) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def test_cli_resolvable_prints_abs_path_exit_0(tmp_path):
    """Dogfood-resolvable name → abs path on stdout, nothing on stderr, exit 0."""
    name = "github_pr_author.py"
    repo = _framework_repo(tmp_path / "repo", name)
    home = tmp_path / "home"  # empty — no cache; dogfood resolves
    home.mkdir()

    proc = _run_cli([name], cwd=repo, home=home)

    assert proc.returncode == 0
    printed = proc.stdout.strip()
    assert _same(printed, repo / "skills" / "_shared" / name)
    assert Path(printed).is_absolute()
    assert proc.stderr == ""


def test_cli_reads_home_for_cache_root(tmp_path):
    """A consumer cwd resolves through the CLI's $HOME-derived cache root."""
    name = "github_pr_author.py"
    consumer = _plain_repo(tmp_path / "consumer")
    home = tmp_path / "home"
    # A REAL cache install: the sentinel qualifies it, exactly as probes 1-4 are
    # qualified. Without it the entry is a bare dir the resolver must refuse.
    shared = (
        home / ".claude" / "plugins" / "cache" / "marketplace"
        / "three-pillars" / "1.2.0" / "skills" / "_shared"
    )
    _write(shared / "first-run.md", "# sentinel\n")
    cache_copy = _write(shared / name, "# cache\n")

    proc = _run_cli(
        [name], cwd=consumer, home=home, script=_neutral_resolver(tmp_path)
    )

    assert proc.returncode == 0
    assert _same(proc.stdout.strip(), cache_copy)


def test_cli_unresolvable_prints_diagnostic_exit_1(tmp_path):
    """Unresolvable name → diagnostic naming probed roots on stderr, exit 1."""
    name = "nonexistent_module.py"
    consumer = _plain_repo(tmp_path / "consumer")
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_cli([name], cwd=consumer, home=home)

    assert proc.returncode == 1
    assert proc.stdout.strip() == ""
    assert name in proc.stderr
    # The $HOME-derived cache root is named among the probed roots.
    assert str(home / ".claude" / "plugins" / "cache") in proc.stderr


def test_cli_wrong_arity_exits_2_with_usage(tmp_path):
    """No positional name → exit 2 with a usage line on stderr."""
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    proc = _run_cli([], cwd=cwd, home=home)

    assert proc.returncode == 2
    assert "usage" in proc.stderr.lower()


# --------------------------------------------------------------------------- #
# PR #144 S3 — `name` must be a BARE BASENAME
# --------------------------------------------------------------------------- #
#: Every shape that escapes `<root>/skills/_shared`. `Path.__truediv__` DISCARDS
#: its left operand for an absolute right operand, so `shared / "/etc/hostname"`
#: is `/etc/hostname` — and the CLI takes `name` as an unvalidated positional
#: whose result all three call sites hand to `python3`.
_ESCAPING_NAMES = [
    "/etc/hostname",          # absolute: the _shared root is discarded outright
    "../../SECURITY.md",      # traversal: climbs out of _shared
    "sub/dir/thing.py",       # bare separator: reaches below _shared
    "",                       # empty: `shared / ""` is the _shared dir itself
    # PR #144 R7. `Path("..").name` IS "..", so the basename test ACCEPTED the
    # bare traversal component while rejecting every spelling that contains it.
    # Not exploitable — `(shared / "..").is_file()` is always False — but a
    # check whose contract says BARE BASENAME must not admit `..`, and the
    # accepted set has to be the one the docstring describes.
    "..",                     # traversal component, no separator to catch it
    ".",                      # the _shared dir itself, spelled differently
]


@pytest.mark.parametrize("name", _ESCAPING_NAMES, ids=lambda n: repr(n))
def test_non_basename_name_exits_2(name, tmp_path):
    """A name that is not a bare basename → exit 2, nothing on stdout.

    Exit 2 (usage), not 1 (not-found): the caller asked a malformed question,
    and answering it with a resolved path would defeat the module's headline
    "never a silent wrong path" contract. Nothing may reach stdout, because
    stdout is what the call sites capture into `$GHPA` and execute.
    """
    home = tmp_path / "home"
    home.mkdir()
    # A framework repo as cwd, so a name that DID resolve would resolve here —
    # the case fails loudly rather than passing because nothing existed anyway.
    cwd = _framework_repo(tmp_path / "repo", "github_pr_author.py")

    proc = _run_cli([name], cwd=cwd, home=home)

    assert proc.returncode == 2, proc.stderr
    assert proc.stdout.strip() == "", (
        f"{name!r} produced a path on stdout — the call sites execute that"
    )
    assert "basename" in proc.stderr.lower()


def test_absolute_name_does_not_resolve_to_itself(tmp_path):
    """The concrete escape: resolve_shared_script('/etc/hostname') is refused.

    Before this, `shared / name` discarded its left operand and the function
    returned `/etc/hostname` — an existing file, so the fail-loud path never
    fired and the caller executed it.
    """
    victim = tmp_path / "outside" / "SECURITY.md"
    victim.parent.mkdir(parents=True)
    victim.write_text("# not a _shared module\n", encoding="utf-8")
    cwd = _framework_repo(tmp_path / "repo", "github_pr_author.py")
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_cli([str(victim)], cwd=cwd, home=home)

    assert proc.returncode == 2
    assert str(victim) not in proc.stdout


def test_unknown_flag_exits_2(tmp_path):
    """An unrecognized flag → exit 2, reported AS unknown (not as bad arity).

    ``--bogus <name>`` is two argv entries, so a purely positional arity check
    would also exit 2 — for the wrong reason, and it would accept ``--bogus``
    as a script name the moment the arity happened to work out. The stderr
    predicate is what distinguishes the two.
    """
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    proc = _run_cli(["--bogus", "github_pr_author.py"], cwd=cwd, home=home)

    assert proc.returncode == 2
    assert "unknown" in proc.stderr.lower()
    assert "--bogus" in proc.stderr


def test_positional_arity_still_one(tmp_path):
    """Exactly ONE positional must survive flag stripping — 0 or 2 exit 2.

    The arity check has to run AFTER ``--skill-dir <dir>`` is removed from
    argv, so the flag pair is not miscounted as positionals. The third case is
    the load-bearing one: a valid one-positional call carrying the flag must
    NOT be rejected as wrong arity.
    """
    name = "github_pr_author.py"
    skill_dir = _anchored_repo(tmp_path / "anchored", name)
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    zero = _run_cli(["--skill-dir", str(skill_dir)], cwd=cwd, home=home)
    assert zero.returncode == 2
    assert "usage" in zero.stderr.lower()

    two = _run_cli(
        ["--skill-dir", str(skill_dir), name, "extra.py"], cwd=cwd, home=home
    )
    assert two.returncode == 2
    assert "usage" in two.stderr.lower()

    one = _run_cli(["--skill-dir", str(skill_dir), name], cwd=cwd, home=home)
    assert one.returncode != 2, (
        "one positional plus --skill-dir <dir> is correct arity, not a usage error"
    )


# --------------------------------------------------------------------------- #
# PR #144 R7 S1 — a probe that RAISES breaks the exit 0/1/2 contract
# --------------------------------------------------------------------------- #
def test_over_long_name_fails_loud_not_with_a_traceback(tmp_path):
    """A `name` longer than NAME_MAX exits 1 with the probe report — no traceback.

    `_probe`'s final `candidate.is_file()` used to carry a comment asserting it
    "cannot raise" because the parent dirs were stat'd above. That is false:
    pathlib's `_ignore_error` swallows only ENOENT/ENOTDIR/EBADF/ELOOP, and the
    BASENAME is not one of the segments `_framework_probe` walked. A 256+ char
    name therefore raised ENAMETOOLONG out of the probe, straight past
    `_main`'s `except (ValueError, SharedScriptNotFound)`, and escaped as a
    bare traceback: exit 1 with NO diagnostic, which is the fail-loud probe
    report contract inverted — the operator learns nothing about where it
    looked. The same escape fires on a legitimate short name when the ROOT is
    deep enough that `<root>/skills/_shared/<name>` crosses PATH_MAX.
    """
    name = "a" * 300 + ".py"
    repo = _framework_repo(tmp_path / "repo", "github_pr_author.py")
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_cli([name], cwd=repo, home=home)

    assert "Traceback" not in proc.stderr, (
        "a probe raised out of the resolver — the exit 0/1/2 contract is broken:\n"
        + proc.stderr
    )
    assert proc.returncode == 1, proc.stderr
    assert proc.stdout.strip() == ""
    # Exit 1 means SharedScriptNotFound: it must NAME the roots it probed.
    assert "not found in any candidate root" in proc.stderr
    assert str(repo / "skills" / "_shared") in proc.stderr
