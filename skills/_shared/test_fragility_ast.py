"""test_fragility_ast.py — the shared AST helpers of the fragility lint.

design: fragile-test-prevention (detailed-design-lint §Test-file classification)

Behaviour only: `dotted` names a call's func (or None when it is not a plain
name chain), `is_test_file` classifies from the runner's own `python_files`
globs (pytest.ini, then setup.cfg, then pyproject.toml), `bound_names` maps a
scope's names to their value nodes, and `md_reads` finds the names bound to a
`.md` read in a function and at module level, with one hop through a
module-level helper that returns such a read. Every code sample is a string
fixture parsed here; nothing reads a live source file.
"""
from __future__ import annotations

import ast

import pytest

from fragility_ast import bound_names, dotted, is_md_read, is_test_file, md_reads, runner_globs


def _func_of(src: str) -> ast.expr:
    return ast.parse(src, mode="eval").body.func


@pytest.mark.parametrize("src, expected", [
    ("a.b.c(1)", "a.b.c"),
    ("a(1)", "a"),
    ("a[0](1)", None),
    ("a.b[0].c(1)", None),
    ("a().b(1)", None),
    ("(lambda: 1)()", None),
])
def test_dotted_names_a_plain_chain_and_only_that(src, expected):
    assert dotted(_func_of(src)) == expected


def test_default_globs_classify_the_pytest_convention(tmp_path):
    for name in ("test_x.py", "x_test.py", "conftest.py"):
        assert is_test_file(tmp_path / name), name
    for name in ("x.py", "mytest.py", "test_x.txt", "test_x.pyc", "helper.md"):
        assert not is_test_file(tmp_path / name), name


def test_a_string_path_and_a_path_object_agree(tmp_path):
    assert is_test_file(str(tmp_path / "test_x.py")) is is_test_file(tmp_path / "test_x.py")


def test_pytest_ini_python_files_replaces_the_default_globs(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = check_*.py\n")
    assert is_test_file(tmp_path / "check_a.py")
    assert not is_test_file(tmp_path / "test_a.py")
    assert not is_test_file(tmp_path / "a_test.py")
    assert not is_test_file(tmp_path / "x.py")


def test_conftest_stays_a_test_file_under_a_custom_glob(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = check_*.py\n")
    assert is_test_file(tmp_path / "conftest.py")


def test_python_files_takes_several_whitespace_separated_globs(tmp_path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\npython_files =\n    check_*.py\n    *_check.py\n")
    assert is_test_file(tmp_path / "check_a.py")
    assert is_test_file(tmp_path / "a_check.py")
    assert not is_test_file(tmp_path / "test_a.py")


def test_setup_cfg_is_read_when_there_is_no_pytest_ini(tmp_path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\npython_files = check_*.py\n")
    assert is_test_file(tmp_path / "check_a.py")
    assert not is_test_file(tmp_path / "test_a.py")


@pytest.mark.parametrize("value", ['["check_*.py"]', '"check_*.py"'])
def test_pyproject_is_read_when_no_ini_sets_the_globs(tmp_path, value):
    pytest.importorskip("tomllib")
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.pytest.ini_options]\npython_files = {value}\n")
    assert is_test_file(tmp_path / "check_a.py")
    assert not is_test_file(tmp_path / "test_a.py")


def test_the_configs_are_consulted_in_order_ini_then_cfg_then_pyproject(tmp_path):
    pytest.importorskip("tomllib")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npython_files = ["p_*.py"]\n')
    assert runner_globs(tmp_path) == ["p_*.py"]
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\npython_files = s_*.py\n")
    assert runner_globs(tmp_path) == ["s_*.py"]
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = i_*.py\n")
    assert runner_globs(tmp_path) == ["i_*.py"]


def test_a_config_that_does_not_set_python_files_falls_through(tmp_path):
    pytest.importorskip("tomllib")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = x\n")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npython_files = ["c_*.py"]\n')
    assert runner_globs(tmp_path) == ["c_*.py"]


def test_no_config_means_no_runner_globs(tmp_path):
    assert runner_globs(tmp_path) is None


def test_the_config_is_found_from_a_subdirectory(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = check_*.py\n")
    sub = tmp_path / "pkg" / "inner"
    sub.mkdir(parents=True)
    assert is_test_file(sub / "check_a.py")
    assert not is_test_file(sub / "test_a.py")


def test_the_search_stops_at_the_repo_root(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = check_*.py\n")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert is_test_file(repo / "test_a.py")
    assert not is_test_file(repo / "check_a.py")


def test_a_broken_config_falls_back_to_the_default_globs(tmp_path):
    (tmp_path / "pytest.ini").write_text("this is [not an ini\n")
    (tmp_path / "setup.cfg").write_bytes(b"\xff\xfe\x00 not text")
    assert is_test_file(tmp_path / "test_a.py")
    assert not is_test_file(tmp_path / "check_a.py")


def _scope(src: str, index: int | None = None):
    tree = ast.parse(src)
    return tree if index is None else tree.body[index]


def test_bound_names_maps_module_names_to_their_value_nodes():
    bound = bound_names(_scope("X = 1\nY: int = 2\nZ = W = 3\nA, B = 4, 5\nC += 6\n"))
    assert set(bound) == {"X", "Y", "Z", "W"}
    assert [bound[n].value for n in ("X", "Y", "Z", "W")] == [1, 2, 3, 3]


def test_bound_names_covers_compound_statements_but_not_nested_scopes():
    src = (
        "def f():\n"
        "    a = 1\n"
        "    if a:\n"
        "        b = 2\n"
        "    for _ in []:\n"
        "        c = 3\n"
        "    with open('x') as fh:\n"
        "        d = fh.read()\n"
        "    def inner():\n"
        "        hidden = 4\n"
        "    class K:\n"
        "        also_hidden = 5\n"
    )
    bound = bound_names(_scope(src, 0))
    assert set(bound) == {"a", "b", "c", "d", "fh"}
    assert isinstance(bound["fh"], ast.Call) and dotted(bound["fh"].func) == "open"


def test_the_last_binding_of_a_name_wins():
    assert bound_names(_scope("x = 1\nx = 2\n"))["x"].value == 2


def _reads(src: str, with_module: bool = True) -> set:
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "test_a")
    return md_reads(fn, tree if with_module else None)


@pytest.mark.parametrize("read", [
    'Path("x.md").read_text(encoding="utf-8")',
    'pathlib.Path("x.md").read_text(encoding="utf-8")',
    'Path("x.md").read_bytes()',
    'open("x.md").read()',
    'open("x.md", encoding="utf-8").read()',
])
def test_md_reads_finds_a_name_bound_to_a_md_read(read):
    src = f"def test_a():\n    text = {read}\n    assert 'a' in text\n"
    assert _reads(src) == {"text"}


def test_md_reads_traces_a_path_bound_to_a_name_and_a_joined_path():
    src = (
        "def test_a():\n"
        "    p = Path('x.md')\n"
        "    q = Path(__file__).parent / 'docs' / 'y.md'\n"
        "    one = p.read_text(encoding='utf-8')\n"
        "    two = q.read_text(encoding='utf-8')\n"
    )
    assert _reads(src) == {"one", "two"}


def test_md_reads_traces_open_used_as_a_context_manager():
    src = "def test_a():\n    with open('x.md') as fh:\n        text = fh.read()\n"
    assert _reads(src) == {"text"}


def test_md_reads_follows_a_method_chain_off_the_read():
    src = "def test_a():\n    lines = Path('x.md').read_text(encoding='utf-8').lower().splitlines()\n"
    assert _reads(src) == {"lines"}


@pytest.mark.parametrize("value", [
    'Path("x.json").read_text(encoding="utf-8")',
    'Path("x.py").read_text(encoding="utf-8")',
    'open(name).read()',
    'Path("x.md")',
    'Path(__file__).parent / "docs" / "x.md"',
    'json.loads(Path("x.json").read_text(encoding="utf-8"))',
    '"plain.md"',
])
def test_md_reads_ignores_what_is_not_a_md_read(value):
    assert _reads(f"def test_a():\n    text = {value}\n") == set()


def test_md_reads_includes_module_level_bindings():
    src = (
        "TEXT = Path('x.md').read_text(encoding='utf-8')\n"
        "OTHER = Path('x.json').read_text(encoding='utf-8')\n"
        "def test_a():\n"
        "    assert 'a' in TEXT\n"
    )
    assert _reads(src) == {"TEXT"}
    assert _reads(src, with_module=False) == set()


def test_a_local_rebinding_shadows_a_module_level_read():
    src = (
        "TEXT = Path('x.md').read_text(encoding='utf-8')\n"
        "def test_a():\n"
        "    TEXT = 'not a read'\n"
    )
    assert _reads(src) == set()


def test_a_module_scope_can_be_the_scope_itself():
    tree = ast.parse("TEXT = Path('x.md').read_text(encoding='utf-8')\nN = 1\n")
    assert md_reads(tree) == {"TEXT"}


HELPERS = (
    "def _skill_text():\n"
    "    return Path('x.md').read_text(encoding='utf-8')\n"
    "def _via_name():\n"
    "    t = open('y.md').read()\n"
    "    return t\n"
    "def _two_hops():\n"
    "    return _skill_text()\n"
    "def _not_a_read():\n"
    "    return Path('x.json').read_text(encoding='utf-8')\n"
)


def test_md_reads_takes_one_hop_through_a_module_level_helper():
    src = HELPERS + "def test_a():\n    a = _skill_text()\n    b = _via_name()\n    c = _not_a_read()\n"
    assert _reads(src) == {"a", "b", "_skill_text", "_via_name"}


def test_md_reads_takes_only_one_hop():
    reads = _reads(HELPERS + "def test_a():\n    d = _two_hops()\n")
    assert "d" not in reads
    assert "_two_hops" not in reads


def test_is_md_read_judges_an_expression_against_the_reads():
    tree = ast.parse(
        "def _skill_text():\n    return Path('x.md').read_text(encoding='utf-8')\n"
        "def test_a():\n    text = Path('x.md').read_text(encoding='utf-8')\n"
    )
    reads = md_reads(tree.body[1], tree)

    def judge(src: str) -> bool:
        return is_md_read(ast.parse(src, mode="eval").body, reads)

    assert judge("text")
    assert judge("_skill_text()")
    assert judge("Path('z.md').read_text(encoding='utf-8')")
    assert judge("text.lower()")
    assert not judge("other")
    assert not judge("Path('z.json').read_text(encoding='utf-8')")
    assert not judge("parsed_names")
