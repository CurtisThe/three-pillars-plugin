"""Inline Python extraction for the delete fence (design delete-fence-own-tree 1.5).

`inline_sources(command) -> list[str]` returns the Python source texts a shell
command runs inline: `python -c '…'`, `python3 - <<'EOF' … EOF`, and the same
behind option flags, a later `cd` segment, a nested `bash -c "…"` or an `env`
wrapper. A script file (`python3 x.py`), a non-Python verb (`pytest x`,
`echo python -c`) and an unmodelled command yield nothing. Nothing is executed
and no file is read: the extraction is pure text over the shell layer.
"""
import pytest

from delete_fence_py import inline_sources


def test_dash_c_yields_the_script_text():
    assert inline_sources('python3 -c "import shutil"') == ["import shutil"]


def test_python_dash_c_with_a_quoted_script():
    assert inline_sources("python -c 'import os; os.remove(\"/h/x\")'") == [
        'import os; os.remove("/h/x")']


def test_heredoc_body_is_the_source():
    cmd = "python3 - <<'EOF'\nimport shutil\nshutil.rmtree('/h')\nEOF\n"
    assert inline_sources(cmd) == ["import shutil\nshutil.rmtree('/h')\n"]


def test_option_flags_before_dash_c():
    assert inline_sources("python3 -I -c 'print(1)'") == ["print(1)"]


def test_a_later_segment_after_cd():
    assert inline_sources("cd d && python3 -c 'import sys'") == ["import sys"]


def test_nested_inside_bash_c():
    cmd = '''bash -c "python3 -c 'import json'"'''
    assert inline_sources(cmd) == ["import json"]


def test_env_wrapper():
    assert inline_sources("env PYTHONPATH=x python3 -c 'import x'") == ["import x"]


def test_script_file_is_not_inline_source():
    assert inline_sources("python3 script.py") == []


def test_pytest_is_not_python():
    assert inline_sources("pytest x") == []


def test_echo_mentioning_python_dash_c():
    assert inline_sources("echo python -c") == []


def test_two_inline_scripts_in_one_command():
    cmd = "python3 -c 'import a'; python3 -c 'import b'"
    assert inline_sources(cmd) == ["import a", "import b"]


def test_dash_c_without_an_argument():
    assert inline_sources("python3 -c") == []


def test_quoted_heredoc_with_flags():
    cmd = "python3 -I - <<'PY'\nimport os\nPY\n"
    assert inline_sources(cmd) == ["import os\n"]


def test_python3_versioned_name():
    assert inline_sources("python3.11 -c 'import os'") == ["import os"]


def test_unmodelled_command_yields_nothing():
    assert inline_sources("python3 -c $(bad((") == []


@pytest.mark.parametrize("cmd", [
    "python3 -c 'import a' && python3 - <<'EOF'\nimport b\nEOF\n",
])
def test_mixed_shapes_both_found(cmd):
    assert inline_sources(cmd) == ["import a", "import b\n"]
