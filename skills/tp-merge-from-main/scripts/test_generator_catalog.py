"""`generator_catalog.py`: the lockfile catalog and the pure detector.

`detect` finds a tracked lockfile whose sibling manifest is tracked, that no declared generator
already covers and that was never offered before; `config_entry` turns a match into a
`merge_from_main.generators` item that `regenerate.load_generators` accepts unchanged;
`offer_record` merges the `generator_offer` block. Everything here is pure - no subprocess, no
config write - so the fixtures are plain lists and dicts, never a repository.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from generator_catalog import (  # noqa: E402
    CATALOG, CatalogEntry, CatalogMatch, config_entry, detect, offer_record, tool_on_path)
from regenerate import load_generators  # noqa: E402

# Behavior 7: no catalog write may run a package's lifecycle scripts. The flag is per tool, so the
# check below stays an allowlist over the catalog's own tools, not a needle list.
SAFETY_FLAG = {"npm": "--ignore-scripts", "uv": "--no-build"}


def _argv_ok(argv) -> bool:
    """`argv` is a concrete argv: a non-empty list of non-empty strings."""
    return isinstance(argv, list) and bool(argv) and all(isinstance(x, str) and x for x in argv)


def test_catalog_entries_hold_their_safety_flag_in_a_concrete_argv():
    """Every catalog entry runs with its tool's no-lifecycle-scripts flag on BOTH runs (Behavior
    7), and states its argv as lists a config can hold."""
    assert len(CATALOG) == 2
    tools = set()
    for entry in CATALOG:
        assert isinstance(entry, CatalogEntry)
        assert _argv_ok(entry.write) and _argv_ok(entry.check)
        assert isinstance(entry.inputs, tuple) and entry.inputs
        flag = SAFETY_FLAG[entry.tool]
        assert flag in entry.write, f"{entry.basename} write runs lifecycle scripts"
        assert flag in entry.check, f"{entry.basename} check runs lifecycle scripts"
        assert entry.timeout > 0
        tools.add(entry.tool)
    assert tools == set(SAFETY_FLAG)


def test_catalog_entry_timeout_defaults_to_five_minutes():
    """An entry that declares no timeout gets the catalog's own default, not regenerate's."""
    bare = CatalogEntry("x.lock", ("x.toml",), "uv", ["uv", "lock", "--no-build"], None)
    assert bare.timeout == 300


def test_detect_matches_tracked_lockfile_beside_tracked_manifest():
    """A tracked `package-lock.json` with a tracked `package.json` beside it is a match; the repo
    root has no `cwd`."""
    matches = detect(["package.json", "package-lock.json", "README.md"], {})
    assert [m.path for m in matches] == ["package-lock.json"]
    m = matches[0]
    assert isinstance(m, CatalogMatch)
    assert m.cwd is None
    assert m.entry.basename == "package-lock.json"


def test_detect_refuses_manifest_missing_declared_and_offered_paths():
    """The three refusals: no sibling manifest tracked, a generator already declares the path,
    and the path was already offered."""
    assert detect(["package-lock.json"], {}) == []
    declared = {"merge_from_main": {"generators": [
        {"path": "package-lock.json", "write": ["npm", "install"], "check": None}]}}
    assert detect(["package.json", "package-lock.json"], declared) == []
    offered = {"merge_from_main": {"generator_offer": {"offered_paths": ["package-lock.json"]}}}
    assert detect(["package.json", "package-lock.json"], offered) == []


def test_detect_only_restricts_the_result():
    """`only` narrows the result to the paths asked about; a path outside it never appears."""
    tracked = ["package.json", "package-lock.json", "web/package.json", "web/package-lock.json"]
    assert [m.path for m in detect(tracked, {}, only=["web/package-lock.json"])] == \
        ["web/package-lock.json"]
    assert detect(tracked, {}, only=["docs/notes.md"]) == []
    assert [m.path for m in detect(tracked, {}, only=[])] == []


def test_detect_nested_lockfile_gets_its_directory_as_cwd():
    """A lockfile in a subdirectory matches with its directory as `cwd`, and its sibling manifest
    is looked up in that same directory."""
    tracked = ["web/package.json", "web/package-lock.json", "package.json"]
    matches = detect(tracked, {})
    assert [m.path for m in matches] == ["web/package-lock.json"]
    assert matches[0].cwd == "web"


def test_detect_sorts_by_path_and_covers_both_catalog_tools():
    """Results are sorted by path regardless of the input order, and `uv.lock` is detected the
    same way as `package-lock.json`."""
    tracked = ["web/uv.lock", "uv.lock", "web/pyproject.toml", "pyproject.toml",
               "web/package.json", "web/package-lock.json", "package.json",
               "package-lock.json"]
    matches = detect(tracked, {})
    assert [m.path for m in matches] == ["package-lock.json", "uv.lock",
                                         "web/package-lock.json", "web/uv.lock"]
    assert [m.cwd for m in matches] == [None, None, "web", "web"]
    assert [m.entry.tool for m in matches] == ["npm", "uv", "npm", "uv"]


def test_config_entry_loads_unchanged_through_load_generators():
    """Round trip: a nested match's `config_entry` is a well-formed generator item - repo-relative
    `inputs`, a `cwd`, concrete argv - that `load_generators` accepts unchanged."""
    m = detect(["web/package.json", "web/package-lock.json"], {})[0]
    entry = config_entry(m)
    assert entry["path"] == "web/package-lock.json"
    assert entry["cwd"] == "web"
    assert entry["inputs"] == ["web/package.json"]
    assert entry["timeout"] == 300
    assert _argv_ok(entry["write"]) and _argv_ok(entry["check"])
    gens = load_generators({"merge_from_main": {"generators": [entry]}})
    assert len(gens) == 1
    gen = gens[0]
    assert gen.path == entry["path"]
    assert gen.write == entry["write"]
    assert gen.check == entry["check"]
    assert gen.timeout == entry["timeout"]
    assert list(gen.inputs) == entry["inputs"]
    assert gen.cwd == "web"


def test_config_entry_root_match_omits_cwd():
    """A repo-root match carries no `cwd` key at all, and an entry with no `check` omits it."""
    entry = config_entry(detect(["package.json", "package-lock.json"], {})[0])
    assert "cwd" not in entry
    no_check = CatalogEntry("plain.lock", ("plain.toml",), "plain",
                            ["plain", "lock", "--no-build"], None)
    bare = config_entry(CatalogMatch("plain.lock", None, no_check))
    assert "check" not in bare
    assert load_generators({"merge_from_main": {"generators": [bare]}})[0].check is None


def test_offer_record_merges_dedupes_and_sorts_offered_paths():
    """The offer block records the timestamp, the answer, and the old paths plus the new ones -
    deduped and sorted."""
    config = {"merge_from_main": {"generator_offer": {"offered_paths": ["b/uv.lock", "uv.lock"]}}}
    rec = offer_record(config, ["b/uv.lock", "a/uv.lock"], accepted=False,
                       now="2026-10-17T09:00:00Z")
    assert rec == {"offered_at": "2026-10-17T09:00:00Z", "declined": True,
                   "offered_paths": ["a/uv.lock", "b/uv.lock", "uv.lock"]}
    fresh = offer_record({}, ["uv.lock"], accepted=True, now="2026-10-17T09:00:00Z")
    assert fresh["declined"] is False
    assert fresh["offered_paths"] == ["uv.lock"]


def test_tool_on_path_uses_the_injected_which():
    """The lookup goes through the injected `which`, so the detector stays testable with no
    npm or uv installed."""
    m = detect(["package.json", "package-lock.json"], {})[0]

    def found(name):
        return "/usr/bin/npm" if name == "npm" else None

    assert tool_on_path(m, which=found) is True
    assert tool_on_path(m, which=lambda name: None) is False
