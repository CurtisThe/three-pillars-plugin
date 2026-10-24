"""Task 2.3: task_closure.discovery_globs honours pytest `python_files`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_closure  # noqa: E402


def _globs(tmp_path, **files):
    for name, body in files.items():
        (tmp_path / name.replace("__", ".")).write_text(body)
    return task_closure.discovery_globs(tmp_path)


def test_pytest_ini_python_files(tmp_path):
    got = _globs(tmp_path, pytest__ini="[pytest]\npython_files = *_test.py check_*.py\n")
    assert got == ("*_test.py", "check_*.py")


def test_no_config_defaults(tmp_path):
    assert _globs(tmp_path) == ("test_*.py",)


def test_tox_ini_when_no_pytest_ini(tmp_path):
    got = _globs(tmp_path, tox__ini="[pytest]\npython_files = *_test.py\n")
    assert got == ("*_test.py",)


def test_setup_cfg_only(tmp_path):
    got = _globs(tmp_path, setup__cfg="[tool:pytest]\npython_files = t_*.py\n")
    assert got == ("t_*.py",)
