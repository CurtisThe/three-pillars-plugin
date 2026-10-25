"""task_closure.discovery_globs tolerates TOML-valid but non-table shapes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_closure  # noqa: E402

pytest.importorskip("tomllib")

DEFAULT = ("test_*.py",)


def _globs(tmp_path, text):
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    return task_closure.discovery_globs(tmp_path)


def test_tool_not_a_table_gives_default(tmp_path):
    assert _globs(tmp_path, 'tool = "x"\n') == DEFAULT


def test_tool_pytest_not_a_table_gives_default(tmp_path):
    assert _globs(tmp_path, "[tool]\npytest = 1\n") == DEFAULT


def test_ini_options_not_a_table_gives_default(tmp_path):
    assert _globs(tmp_path, '[tool.pytest]\nini_options = "x"\n') == DEFAULT


def test_python_files_table_still_read(tmp_path):
    text = '[tool.pytest.ini_options]\npython_files = ["*_test.py"]\n'
    assert _globs(tmp_path, text) == ("*_test.py",)
