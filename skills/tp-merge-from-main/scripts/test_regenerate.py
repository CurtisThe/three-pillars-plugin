"""`regenerate.py`: regenerate-and-verify for declared generated files.

A generated file is accepted only when regenerating from OURS' committed version and from
THEIRS' gives the same bytes, the run is idempotent, no conflict bracket survives, and the
declared check exits 0. Anything else is a `(None, reason)` refusal. The fake generators are
short scripts written into `tmp_path` and invoked as `[sys.executable, <script>]` in the argv.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from regenerate import Generator, load_generators, regenerate_file  # noqa: E402

GEN_PATH = "generated.json"

# Rebuilds `generated.json`'s "agents" array from the sorted `agents/*.md` names (idempotent).
REBUILD = '''
import json
from pathlib import Path
p = Path("generated.json")
data = json.loads(p.read_text(encoding="utf-8"))
data["agents"] = sorted(x.name.removesuffix(".md") for x in Path("agents").glob("*.md"))
p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
'''
# Appends a line on every run: not idempotent.
APPEND = '''
from pathlib import Path
p = Path("generated.json")
p.write_text(p.read_text(encoding="utf-8") + "more\\n", encoding="utf-8")
'''
# Idempotent, but the output holds a conflict bracket line.
BRACKET = '''
from pathlib import Path
p = Path("generated.json")
p.write_text("a\\n<<<<<<< ours\\nb\\n", encoding="utf-8")
'''
EXIT1 = "import sys\nsys.exit(1)\n"
OK = "print('ok')\n"


def write_script(tmp_path, name, body):
    script = tmp_path / name
    script.write_text(body, encoding="utf-8")
    return str(script)


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "alpha.md").write_text("# alpha\n", encoding="utf-8")
    (repo / "agents" / "beta.md").write_text("# beta\n", encoding="utf-8")
    return repo


def gen(tmp_path, body, check_body=None):
    argv = [sys.executable, write_script(tmp_path, "gen.py", body)]
    check = [sys.executable, write_script(tmp_path, "check.py", check_body)] if check_body else None
    return Generator(path=GEN_PATH, write=argv, check=check)


def seed_pair():
    ours = json.dumps({"agents": ["zzz"], "meta": "x"}, indent=2)
    theirs = json.dumps({"agents": ["aaa"], "meta": "x"}, indent=2)
    return ours, theirs


def expected_rebuild():
    return (json.dumps({"agents": ["alpha", "beta"], "meta": "x"}, indent=2, sort_keys=True)
            + "\n")


def test_array_only_diff_is_accepted_and_left_on_disk(tmp_path):
    """(a) ours and theirs differ only in the generated array: both rebuilds give the same
    bytes, the result is accepted, and the regenerated text is left on disk at `repo/path`."""
    repo = make_repo(tmp_path)
    ours, theirs = seed_pair()
    text, reason = regenerate_file(repo, gen(tmp_path, REBUILD), ours, theirs)
    assert (text, reason) == (expected_rebuild(), "")
    assert (repo / GEN_PATH).read_text(encoding="utf-8") == expected_rebuild()


def test_theirs_changed_another_key_is_rejected(tmp_path):
    """(b) theirs' version changed a non-generated key too: the two rebuilds differ, so the
    refusal names that the outputs differ."""
    repo = make_repo(tmp_path)
    ours, _ = seed_pair()
    theirs = json.dumps({"agents": ["aaa"], "meta": "CHANGED"}, indent=2)
    text, reason = regenerate_file(repo, gen(tmp_path, REBUILD), ours, theirs)
    assert text is None
    assert "differ" in reason


def test_write_command_nonzero_exits(tmp_path):
    """(c) a write command that exits 1 is a refusal, never an acceptance."""
    repo = make_repo(tmp_path)
    text, reason = regenerate_file(repo, gen(tmp_path, EXIT1), "seed\n", "seed\n")
    assert text is None
    assert reason


def test_check_command_nonzero_exits(tmp_path):
    """(d) the rebuilds agree and are idempotent, but a declared check exiting 1 is a refusal."""
    repo = make_repo(tmp_path)
    ours, theirs = seed_pair()
    text, reason = regenerate_file(
        repo, gen(tmp_path, REBUILD, check_body=EXIT1), ours, theirs)
    assert text is None
    assert reason


def test_check_command_zero_is_accepted(tmp_path):
    """A declared check that exits 0 does not block an otherwise clean regeneration."""
    repo = make_repo(tmp_path)
    ours, theirs = seed_pair()
    text, reason = regenerate_file(
        repo, gen(tmp_path, REBUILD, check_body=OK), ours, theirs)
    assert (text, reason) == (expected_rebuild(), "")


def test_non_idempotent_generator_is_rejected(tmp_path):
    """(e) a generator that appends on every run (not idempotent) is a refusal even though the
    first two rebuilds agree."""
    repo = make_repo(tmp_path)
    text, reason = regenerate_file(repo, gen(tmp_path, APPEND), "seed\n", "seed\n")
    assert text is None
    assert reason


def test_conflict_brackets_in_output_are_rejected(tmp_path):
    """(f) output that still holds a line starting `<<<<<<<` is a refusal."""
    repo = make_repo(tmp_path)
    text, reason = regenerate_file(repo, gen(tmp_path, BRACKET), "seed\n", "seed\n")
    assert text is None
    assert reason


def test_load_generators_reads_declared_items(tmp_path):
    script = write_script(tmp_path, "gen.py", REBUILD)
    cscript = write_script(tmp_path, "check.py", OK)
    config = {"merge_from_main": {"generators": [
        {"path": GEN_PATH, "write": [sys.executable, script],
         "check": [sys.executable, cscript]},
        {"path": GEN_PATH, "write": [sys.executable, script]},
    ]}}
    gens = load_generators(config)
    assert [g.path for g in gens] == [GEN_PATH, GEN_PATH]
    assert gens[0].write == [sys.executable, script]
    assert gens[0].check == [sys.executable, cscript]
    assert gens[1].check is None


def test_load_generators_skips_malformed_items(tmp_path):
    script = write_script(tmp_path, "gen.py", REBUILD)
    config = {"merge_from_main": {"generators": [
        "not-a-dict",
        {"write": [sys.executable, script]},                    # no path
        {"path": GEN_PATH},                                      # no write
        {"path": GEN_PATH, "write": "not-a-list"},               # write not an argv
        {"path": GEN_PATH, "write": [1, 2]},                     # non-string argv
        {"path": GEN_PATH, "write": [sys.executable, script],
         "check": "not-a-list"},                                 # malformed optional check
        {"path": 5, "write": [sys.executable, script]},          # non-string path
    ]}}
    assert load_generators(config) == []


def test_load_generators_without_the_key_returns_empty():
    assert load_generators({}) == []
    assert load_generators({"merge_from_main": {}}) == []
    assert load_generators({"merge_from_main": {"other": 1}}) == []
