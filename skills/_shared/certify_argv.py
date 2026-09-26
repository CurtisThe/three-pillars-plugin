"""certify_argv — the pole command, argv, setup and exit-code rules for certifier records.

design: audit-pass-does-not-bind (Task 2.2; detailed-design-certifier.md §1, N3, N15;
amended 2026-09-25 by the PR #162 allowlist ruling [R6]).

Split out of `certify_record` by responsibility: every rule here reads a record's poles
(argv / expect / setup) and yields reasons; `certify_record` lists them in its `RULES`
table.

**Pytest or not is the guard's, never the argv's.** `is_pytest_guard(guard)` is the one
detector: a guard is pytest when it names a node (`path::node`) or a file whose name is a
pytest test module (`test_*.py` / `*_test.py`). Every other guard (a script, a lint, a
`.sh` gate, `framework-check.sh`) is not.

**A pytest pole's command is the certifier's.** `pytest_command` builds it: one fixed
launcher (`sys.executable -m pytest`), then the one target `pytest_target` builds from the
claim's declared guard, then fixed flags (`PYTEST_FLAGS` around the pole's paths:
`--junitxml=<pole dir>/junit.xml`, `--rootdir=<resolved pole tree>`,
`--confcutdir=<resolved pole tree>`, `-p no:cacheprovider`, `-o addopts=`,
`-o junit_family=xunit1`). No claim string reaches pytest raw: `guard_parts` splits the
guard into its path and optional node, the path must be a normalised repo-relative path
(`repo_path_ok`), and the target is `./<path>[::<node>]`. The `./` anchor makes the one
argv element a path to pytest's argparse whatever the path or node spells: never an
option (`-…`), never an argument file (`@…`, read by argparse's `fromfile_prefix_chars`
only as an element's first character), and junit testcase ids stay the un-anchored ones
the declared guard names. A record for a pytest guard carries no `argv` on any pole
(`pytest-argv-supplied`, refused before any run), so no launcher, option, extra target,
`--pyargs` or `@file` ever reaches pytest from a record.

**Nor from the repo's pytest config** (config ruling, 2026-09-25). `-o addopts=` empties
the `addopts` of whichever config file pytest finds (`pytest.ini`, `.pytest.ini`,
`pytest.toml`, `.pytest.toml`, `pyproject.toml`, `tox.ini`, `setup.cfg`, at the tree root
or beside the guard), so a committed config never adds a target, an `@file`, a `-p`
plugin, `--pyargs`, `-k`/`-m`, `--doctest-modules`, a rootdir or a confcutdir; the pole
env has no `PYTEST_*` (`certify_scratch.scrubbed_env`: no `PYTEST_ADDOPTS`, no
`PYTEST_PLUGINS`). Every other ini key stays the repo's, deliberately: none adds a
target or loads a plugin (`testpaths` applies only when no target is given,
`python_files` / `norecursedirs` only when a directory is walked, `required_plugins`
only refuses to start, which fails closed), and guards legitimately need them
(`pythonpath`, `markers`, `filterwarnings`, `usefixtures`, `asyncio_mode`, ...), which
a certifier-owned `-c` ini would drop. `python_classes` / `python_functions` /
`collect_imported_tests` pick tests inside the guard file only. `--confcutdir` pins the
conftest set to the tree's own `conftest.py` files, from the tree root down to the guard
(a stray conftest above the tree never loads). Those conftest files, the modules they
and the guard import, and the `pytest_plugins` a root conftest names are committed code
running in pytest's process: they stay the repo's, like the guard itself (an
Authorship-class residual, protocol §KNOWN BYPASS list). So does any committed module
that shadows an import: `python -m pytest` runs with the tree (its cwd) first on
`sys.path`, so a committed top-level `pytest.py` or `_pytest/`, a package named like an
installed entry-point plugin (`xdist/`, `pytest_cov/`), or a module named like a stdlib
or site module imported lazily loads the repo's code in its place. Installed plugins are
the environment's only where no committed name shadows them. So only the declared node
is collected from the tree's config: a node guard runs as that node, never as its file.
The junit report is xunit1, so each testcase names the file and line that define it
(`certify_junit` matches that file exactly and the guard file's own definition there).
Its exit readings are the certifier's too: RED is a `<failure>` on the declared node
(rc 1), GREEN the node passing (rc 0). A pytest record carrying `expect.exit` on any
pole is `pytest-exit-supplied`, refused before any run, so no record can make a failing
node read as GREEN.

**A non-pytest pole's argv is the record's.** It is required (`argv-missing`), identical on
every pole, names the guard path, names no path a setup op touches (N3 `argv-not-guard`)
and escapes nowhere (`argv-escape`).
"""

from __future__ import annotations

import sys
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

SHELLS = {"sh", "bash", "zsh"}
PYTEST_FILES = ("test_*.py", "*_test.py")  # pytest's default `python_files`
GIT_ESCAPES = ("--git-dir", "--work-tree", "--exec-path")
PY_VALUE_OPTS = {"-W", "-X"}
# The config the certifier owns (module docstring): no repo addopts, an xunit1 report.
PYTEST_FLAGS = ("-p", "no:cacheprovider", "-o", "addopts=", "-o", "junit_family=xunit1")


def _base(arg: str) -> str:
    return PurePosixPath(arg).name


def _is_python(arg: str) -> bool:
    return _base(arg).startswith("python")


def is_pytest_guard(guard: str) -> bool:
    """A `path::node` guard, or a path whose file name is a pytest test module."""
    path, sep, _node = guard.partition("::")
    return bool(sep) or any(fnmatchcase(_base(path), pat) for pat in PYTEST_FILES)


def repo_path_ok(path) -> bool:
    """A normalised repo-relative path: no `/` or `~` prefix, no `..`, not under `.git`."""
    if not isinstance(path, str) or not path or path.startswith(("/", "~")):
        return False
    parts = PurePosixPath(path).parts
    return norm(path) == path and ".." not in parts and parts[0] != ".git"


def guard_parts(guard: str) -> tuple[str, str | None]:
    """`(path, node)` of a `path[::node]` guard; `node` is None when the guard names none."""
    path, sep, node = guard.partition("::")
    return path, (node if sep else None)


def pytest_target(guard: str) -> str:
    """The one pytest target of a guard: `./<path>[::<node>]` (module docstring).

    Built, never passed through: a path that is not `repo_path_ok` raises (the claim was
    `invalid:guard` before any run), so a caller that skipped validation fails closed."""
    path, node = guard_parts(guard)
    if not repo_path_ok(path) or node == "":
        raise ValueError(f"not a repo-relative guard: {guard!r}")
    return "./" + path + ("::" + node if node else "")


def pytest_command(guard: str, junit_path, *, rootdir) -> list[str]:
    """The only argv a pytest pole ever runs: launcher, the guard's target, fixed flags."""
    return [sys.executable, "-m", "pytest", pytest_target(guard), f"--junitxml={junit_path}",
            f"--rootdir={rootdir}", f"--confcutdir={rootdir}", *PYTEST_FLAGS]


def norm(path: str) -> str:
    """A setup / guard path in comparable form (`./a/../b` → `b`)."""
    parts = []
    for part in PurePosixPath(path).parts:
        if part == "..":
            parts = parts[:-1] if parts and parts[-1] != ".." else parts + [".."]
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def _values(arg: str) -> list[str]:
    return [arg, arg.split("=", 1)[1]] if "=" in arg else [arg]


def _poles(rec) -> list[dict]:
    return rec["red"] + rec["green"]


def all_argvs(rec) -> list[list[str]]:
    """Every pole's record-supplied argv (a pytest-guard record supplies none)."""
    return [pole["argv"] for pole in _poles(rec) if "argv" in pole]


def setup_paths(rec) -> set[str]:
    return {norm(op["path"]) for pole in _poles(rec) for op in pole["setup"]}


# --- who owns the command -----------------------------------------------------------

def pytest_argv_supplied(rec):
    """A pytest guard's command is the certifier's: a record argv on any pole is refused."""
    if is_pytest_guard(rec["guard"]) and all_argvs(rec):
        yield "pytest-argv-supplied"


def pytest_exit_supplied(rec):
    """A pytest pole's rc is the certifier's to read (RED: a `<failure>` on the declared
    node, rc 1; GREEN: the node passed, rc 0): a record `expect.exit` on any pole is refused."""
    if is_pytest_guard(rec["guard"]) and any("exit" in p.get("expect", {}) for p in _poles(rec)):
        yield "pytest-exit-supplied"


def argv_missing(rec):
    """A non-pytest guard is run by the record's argv, so every pole needs one."""
    if not is_pytest_guard(rec["guard"]) and any("argv" not in p for p in _poles(rec)):
        yield "argv-missing"


# --- escapes [F7] ----------------------------------------------------------------------

def _path_escapes(value: str) -> bool:
    return value.startswith(("/", "~")) or ".." in PurePosixPath(value).parts


def _interpreter_c(argv: list[str]) -> bool:
    """`sh`/`bash`/`zsh` or `python*` given a `-c` program string."""
    if not (_base(argv[0]) in SHELLS or _is_python(argv[0])):
        return False
    i = 1
    while i < len(argv):
        arg = argv[i]
        if not arg.startswith("-") or arg.startswith(("--", "-m")):
            return False
        if arg[:2] in PY_VALUE_OPTS and _is_python(argv[0]):
            i += 2 if len(arg) == 2 else 1
            continue
        if "c" in arg[1:]:
            return True
        i += 1
    return False


def _argv_escapes(argv: list[str]) -> bool:
    if _interpreter_c(argv):
        return True
    for arg in argv:
        if arg.startswith(GIT_ESCAPES) or (arg.startswith("-C") and not arg.startswith("--")):
            return True
        if any(_path_escapes(v) for v in _values(arg)):
            return True
    return False


def argv_escape(rec):
    paths = [op["path"] for pole in _poles(rec) for op in pole["setup"]]
    if any(map(_argv_escapes, all_argvs(rec))) or any(
            not p or _path_escapes(p) or norm(p).startswith("..") for p in paths):
        yield "argv-escape"


# --- a non-pytest argv bound to the guard (N3) ------------------------------------------

def _is_guard(arg: str, guard: str) -> bool:
    return norm(arg) == norm(guard.partition("::")[0])


def _names_setup_path(argv: list[str], touched: set[str]) -> bool:
    return any(norm(value.split("::")[0]) in touched for arg in argv for value in _values(arg))


def argv_not_guard(rec):
    argvs = all_argvs(rec)
    if is_pytest_guard(rec["guard"]) or not argvs:
        return  # the pytest command is the certifier's; a missing argv is argv-missing
    first = argvs[0]
    if (any(a != first for a in argvs) or not any(_is_guard(a, rec["guard"]) for a in first)
            or _names_setup_path(first, setup_paths(rec))):
        yield "argv-not-guard"


# --- setup ops -------------------------------------------------------------------------

def _ops(poles) -> list[dict]:
    return [op for pole in poles for op in pole["setup"]]


def red_delete(rec):
    if any(op["op"] == "delete" for op in _ops(rec["red"])):
        yield "red-delete"


def _edits_guard(poles, guard) -> bool:
    guard_path = norm(guard.partition("::")[0])
    return any(norm(op["path"]) == guard_path for op in _ops(poles))


def red_edits_guard(rec):
    if _edits_guard(rec["red"], rec["guard"]):
        yield "red-edits-guard"


def green_edits_guard(rec):
    if _edits_guard(rec["green"], rec["guard"]):
        yield "green-edits-guard"


def no_real_green(rec):
    """[F8] at least one GREEN runs the real tree at the SHA."""
    if not any(pole["setup"] == [] for pole in rec["green"]):
        yield "no-real-green"


def no_perturbed_green(rec):
    """[R7] at least one GREEN is a correct near-miss input (non-empty setup)."""
    if not any(pole["setup"] for pole in rec["green"]):
        yield "no-perturbed-green"


# --- exit codes (N15) --------------------------------------------------------------------

def exit_values(poles, default):
    return {pole.get("expect", {}).get("exit", default) for pole in poles}


def exit_shape(rec):
    """GREENs share `H`, REDs share `V`; a non-pytest `H ≠ 0` needs an explicit `V`."""
    greens = exit_values(rec["green"], 0)
    reds = exit_values(rec["red"], None)
    if len(greens) > 1 or len(reds) > 1:
        yield "invalid:shape"
        return
    if not is_pytest_guard(rec["guard"]) and greens != {0} and reds == {None}:
        yield "invalid:shape"
