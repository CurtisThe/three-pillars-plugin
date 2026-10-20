"""Combined interpreter flags and unprovable `.unlink()` receivers.

design: delete-fence-own-tree (Task 2.5)

Two gaps in the inline-Python scan:

- `python3 -Ic "import shutil"` puts the script text on the word after a
  short-flag cluster, so an extractor that matches only a bare `-c` reads the
  cluster as a script-file argument and returns nothing - the body is never
  scanned. A short-flag cluster whose last letter is `c` names the same thing.
- `check_python` read `.unlink()` / `.rmdir()` only when the receiver was
  literally `Path(...)`; a name bound to a path (`p = Path('/h/f')`) or a name
  it cannot see at all (`p.unlink()` on a parameter) fell through as clean. A
  delete verb is present, so an unresolvable receiver refuses.

Nothing here is executed; every source is a string.
"""
import pytest

from delete_fence_py import check_python, inline_sources


def stub_shell_check(text):
    return None


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "build").mkdir(parents=True)
    return str(root)


def _r(source, tree):
    root = tree
    return check_python(source.replace("<R>", root), [root], root, stub_shell_check)


# --- extraction: a short-flag cluster ending in `c` is `-c` -------------------


@pytest.mark.parametrize("flags", ["-Ic", "-uc", "-sc", "-Bc"])
def test_cluster_ending_in_c_takes_the_next_word(flags):
    assert inline_sources('python3 %s "import shutil"' % flags) == ["import shutil"]


def test_separate_options_before_dash_c_still_work():
    assert inline_sources("python3 -I -c 'x'") == ["x"]


def test_cluster_ending_in_c_without_an_argument():
    assert inline_sources("python3 -Ic") == []


def test_cluster_not_ending_in_c_is_not_a_script():
    assert inline_sources("python3 -IB script.py") == []


def test_script_file_is_still_not_inline_source():
    assert inline_sources("python3 script.py") == []


def test_pytest_with_a_c_flag_is_not_python():
    assert inline_sources("pytest -c x") == []


# --- receivers: `.unlink()` / `.rmdir()` through name tracking ---------------


DENIED_RECEIVERS = [
    # a name bound to a literal outside the roots
    "from pathlib import Path\np = Path('/home/x/f')\np.unlink()",
    "p = '/home/x/f'\np.unlink()",
    # a name bound to a literal inside the roots, then re-bound outside
    "p = '<R>/build'\np = '/home/x/f'\np.unlink()",
    # a parameter: this scan cannot see its value
    "def f(p):\n    p.unlink()",
    "def f(p):\n    p.rmdir()",
    # an unknown name
    "p.unlink()",
    "p.rmdir()",
    # a name bound to something this scan cannot read
    "p = os.environ['X']\np.unlink()",
    "import pathlib\np = pathlib.Path('/home/x')\np.unlink()",
]


@pytest.mark.parametrize("source", DENIED_RECEIVERS)
def test_unresolvable_or_outside_receiver_denied(source, tree):
    assert _r(source, tree) is not None


ALLOWED_RECEIVERS = [
    "from pathlib import Path\nPath('<R>/f').unlink()",
    "from pathlib import Path\np = Path('<R>/f')\np.unlink()",
    "p = '<R>/f'\np.unlink()",
    "from pathlib import Path\np = Path('<R>') / 'f'\np.unlink()",
    "from pathlib import Path\np = Path('<R>/build')\np.rmdir()",
    # not a delete verb at all
    "from pathlib import Path\np = Path('/home/x')\np.read_text(encoding='utf-8')",
    "open('/home/x', 'w')",
]


@pytest.mark.parametrize("source", ALLOWED_RECEIVERS)
def test_resolvable_receiver_inside_roots_allowed(source, tree):
    assert _r(source, tree) is None


def test_receiver_refusal_names_the_verb(tree):
    why = _r("p.unlink()", tree)
    assert why is not None and "unlink" in why
