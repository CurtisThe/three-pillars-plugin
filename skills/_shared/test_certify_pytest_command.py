"""The certifier's pytest command contract, asserted by value, never by position or spelling.

design: audit-pass-does-not-bind (PR #162 r1 operator ruling, 2026-09-25;
detailed-design-certifier.md §1 [R6]). pytest reads its options order-free and in several
spellings (`-o V` / `-oV` / `--override-ini V` / `--override-ini=V`; `--confcutdir=D` /
`--confcutdir D`), so a test of `certify_argv.pytest_command` checks what the command
means (the launcher, `./<guard>` the only target, repo addopts emptied, an xunit1 report,
rootdir / confcutdir at the tree, no cache plugin), and survives any reorder or respelling
of the certifier's fixed flags. `assert_certifier_command` is that check; the command
test in test_certify_record_poles.py applies it, and the tests here pin that it reads
every accepted spelling alike and still refuses a command that breaks the contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from test_certify_record_claims import GUARD

# pytest's value-taking options the certifier sets, by every spelling pytest accepts
# (its argparse has `allow_abbrev` off, so no prefix spellings): canonical name per flag.
VALUE_OPTS = {"-o": "-o", "--override-ini": "-o", "-p": "-p", "--junitxml": "--junitxml",
              "--junit-xml": "--junitxml", "--rootdir": "--rootdir",
              "--confcutdir": "--confcutdir"}


def parse_pytest_args(args):
    """`(options, positionals)` of pytest command-line `args`, order-free: `options` maps
    each canonical option to its values in order (`-o V`, `-oV`, `--override-ini V`,
    `--override-ini=V`, ... all read alike; a flag without a value maps to `None`s, a
    value-taking option at the end of `args` to `""`)."""
    options, positionals, it = {}, [], iter(args)
    for arg in it:
        if arg == "--":
            positionals.extend(it)
        elif arg.startswith("--"):
            flag, eq, value = arg.partition("=")
            took = flag in VALUE_OPTS
            options.setdefault(VALUE_OPTS.get(flag, flag), []).append(
                value if eq else next(it, "") if took else None)
        elif arg.startswith("-") and len(arg) > 1:
            flag, glued = arg[:2], arg[2:]
            took = flag in VALUE_OPTS
            if took and glued.startswith("="):  # `-o=V`: pytest reads it as `-o V`
                glued = glued[1:] or next(it, "")
            options.setdefault(flag, []).append((glued or next(it, "")) if took else None)
        else:
            positionals.append(arg)
    return options, positionals


def assert_certifier_command(argv, guard, junit, rootdir):
    """The certifier's pytest contract, by value: its launcher, `./<guard>` the only
    positional, repo addopts emptied, an xunit1 report at `junit`, rootdir and confcutdir
    at the tree, no cache plugin. Any order, any spelling pytest accepts."""
    assert argv[:3] == [sys.executable, "-m", "pytest"]
    options, positionals = parse_pytest_args(argv[3:])
    assert positionals == ["./" + guard]  # built, anchored, the only target
    ini = dict(v.partition("=")[::2] for v in options.get("-o", []))  # last one wins
    assert ini.get("addopts") == "" and ini.get("junit_family") == "xunit1", ini
    cache = [v for v in options.get("-p", []) if v in ("cacheprovider", "no:cacheprovider")]
    assert cache and cache[-1] == "no:cacheprovider", cache  # a later `-p` could re-enable it
    for flag, where in (("--junitxml", junit), ("--rootdir", rootdir),
                        ("--confcutdir", rootdir)):
        values = options.get(flag, [])
        assert values and all(Path(v) == Path(where) for v in values), (flag, values)


LAUNCH = [sys.executable, "-m", "pytest"]
TARGET = "./" + GUARD


@pytest.mark.parametrize("args", [
    [TARGET, "--junitxml=/p/junit.xml", "--rootdir=/p/tree", "--confcutdir=/p/tree",
     "-p", "no:cacheprovider", "-o", "addopts=", "-o", "junit_family=xunit1"],
    ["-o", "junit_family=xunit1", "--confcutdir", "/p/tree", "-oaddopts=", TARGET,
     "-pno:cacheprovider", "--junit-xml", "/p/junit.xml", "--rootdir", "/p/tree/"],
    ["--override-ini=addopts=", "--override-ini", "junit_family=xunit1", TARGET,
     "--rootdir=/p/tree", "--confcutdir=/p/tree", "--junitxml=/p/junit.xml",
     "-p", "no:cacheprovider"],
    [TARGET, "--junitxml=/p/junit.xml", "--rootdir=/p/tree", "--confcutdir=/p/tree",
     "-p=no:cacheprovider", "-o=addopts=", "-o=junit_family=xunit1"],
], ids=["as-built", "reordered-glued", "long-forms", "short-equals"])
def test_the_command_contract_reads_any_order_and_spelling(args):
    assert_certifier_command(LAUNCH + args, GUARD, "/p/junit.xml", "/p/tree")


BUILT = [TARGET, "--junitxml=/p/junit.xml", "--rootdir=/p/tree", "--confcutdir=/p/tree",
         "-p", "no:cacheprovider", "-o", "addopts=", "-o", "junit_family=xunit1"]


def drop(*pair):
    """`BUILT` without the adjacent elements `pair`."""
    i = next(i for i in range(len(BUILT)) if tuple(BUILT[i:i + len(pair)]) == pair)
    return BUILT[:i] + BUILT[i + len(pair):]


@pytest.mark.parametrize("args", [
    drop("-o", "addopts="),
    BUILT + ["-o", "addopts=-x"],
    BUILT + ["-ojunit_family=xunit2"],
    drop("--confcutdir=/p/tree"),
    BUILT + ["--confcutdir", "/elsewhere"],
    drop("-p", "no:cacheprovider"),
    BUILT + ["tests"],
    [GUARD, *BUILT[1:]],
    BUILT + ["-p", "cacheprovider"],
], ids=["no-addopts", "addopts-refilled", "xunit2", "no-confcutdir", "stray-confcutdir",
        "cache-on", "extra-target", "unanchored", "cache-re-enabled"])
def test_the_command_contract_refuses_a_broken_command(args):
    with pytest.raises(AssertionError):
        assert_certifier_command(LAUNCH + args, GUARD, "/p/junit.xml", "/p/tree")
