"""Inline Python deletes for the delete fence (design delete-fence-own-tree 1.4).

`check_python(source, roots, cwd, shell_check)` walks the AST of an inline
Python body and returns None when it is clean, or a refusal reason. A delete
call site (`shutil.rmtree`, `os.remove`/`unlink`/`rmdir`/`removedirs`,
`Path(...).unlink()`/`.rmdir()`) is denied when its path argument is a literal
outside the roots, or when the argument is not a literal at all (a delete verb
is present, so the scan fails closed). A `subprocess` argv or an `os.system`
string is handed to the caller's `shell_check`, which is the shell classifier.
Only call sites count, never substrings, so a source that merely mentions
`rmtree` inside a string is clean. Sources are strings; nothing is executed.
"""
import pytest

from delete_fence_py import check_python

STUB_REASON = "outside scratch: /home/x"


def stub_shell_check(text):
    """The Red spec's stand-in for the fence classifier."""
    return STUB_REASON if text == "rm -rf /home/x" else None


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "build").mkdir(parents=True)
    return str(root)


def _r(source, tree, cwd="<R>", shell_check=stub_shell_check):
    root = tree
    return check_python(source.replace("<R>", root), [root],
                        root if cwd else None, shell_check)


DENIED = [
    "shutil.rmtree('/home/x')",
    "import shutil\nshutil.rmtree('<R>/../outside')",
    "p = '<R>/build'\nshutil.rmtree(p)",
    "shutil.rmtree(p)",
    "os.remove(x)",
    'os.unlink(f"{d}/a")',
    "os.removedirs('/h/x')",
    "os.rmdir('/h')",
    "os.remove(os.path.join('/h', 'x'))",
    "from pathlib import Path\nPath('/home/x').unlink()",
    "from pathlib import Path as P\nP('/h/x').unlink()",
    "from pathlib import Path\n(Path('/home') / 'a').rmdir()",
    "import shutil as sh\nsh.rmtree('/h')",
    "from shutil import rmtree as rt\nrt('/h')",
    "import subprocess\nsubprocess.run(['rm', '-rf', '/home/x'])",
    'os.system("rm -rf /home/x")',
    'os.popen("rm -rf /home/x")',
    'subprocess.run("rm -rf /home/x", shell=True)',
    "subprocess.run(cmd)",
]


@pytest.mark.parametrize("source", DENIED)
def test_delete_outside_or_unprovable_denied(source, tree):
    assert _r(source, tree) is not None


ALLOWED = [
    "import shutil\nshutil.rmtree('<R>/build')",
    "os.remove('<R>/x.txt')",
    "os.remove('x.txt')",
    "os.remove(os.path.join('<R>', 'x.txt'))",
    "from pathlib import Path\n(Path('<R>/build') / 'x').rmdir()",
    "from pathlib import Path\nPath('<R>/build').unlink()",
    "print(\"shutil.rmtree('/h')\")",
    'CASES = ["rm -rf /"]',
    "NOTE = 'os.system(\"rm -rf /home/x\")'",
    "os.path.exists('/h')",
    "import shutil\nshutil.copy('<R>/a', '/elsewhere/b')",
    "from pathlib import Path\nPath('/h/x').read_text(encoding='utf-8')",
    "subprocess.run(['ls', '-l'])",
    "import subprocess as sp\nsp.run(['echo', 'rm -rf /'])",
]


@pytest.mark.parametrize("source", ALLOWED)
def test_clean_source_allowed(source, tree):
    assert _r(source, tree) is None


def test_relative_literal_without_cwd_denied(tree):
    assert _r("os.remove('x.txt')", tree, cwd=None) is not None


def test_relative_rmtree_without_cwd_denied(tree):
    assert _r("import shutil\nshutil.rmtree('build')", tree, cwd=None) is not None


def test_shell_check_reason_is_returned(tree):
    assert _r('os.system("rm -rf /home/x")', tree) == STUB_REASON


def test_argv_is_joined_for_shell_check(tree):
    seen = []

    def spy(text):
        seen.append(text)
        return None

    assert _r("subprocess.run(['rm', '-rf', '/home/x'])", tree,
              shell_check=spy) is None
    assert seen == ["rm -rf /home/x"]


def test_string_command_goes_to_shell_check(tree):
    seen = []

    def spy(text):
        seen.append(text)
        return None

    assert _r("subprocess.run('rm -rf <R>/x', shell=True)", tree,
              shell_check=spy) is None
    assert seen == ["rm -rf " + tree + "/x"]


def test_several_delete_sites_all_checked(tree):
    src = "shutil.rmtree('<R>/build')\nos.remove('/home/x')"
    assert _r(src, tree) is not None


def test_clean_multi_statement_source(tree):
    src = "import shutil\nshutil.rmtree('<R>/build')\nprint('done')"
    assert _r(src, tree) is None


def test_several_roots_any_containment_allowed(tree):
    other = tree + "-sibling"
    src = "shutil.rmtree('%s/build')" % other
    assert check_python(src, [tree, other], tree, stub_shell_check) is None


def test_syntax_error_raises_value_error(tree):
    with pytest.raises(ValueError):
        check_python("def (", [tree], tree, stub_shell_check)


def test_no_roots_denies_a_literal_delete(tree):
    assert check_python("shutil.rmtree('" + tree + "/build')", [], tree,
                        stub_shell_check) is not None
