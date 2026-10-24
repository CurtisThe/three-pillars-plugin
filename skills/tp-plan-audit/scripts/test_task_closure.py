"""Tests for task_closure.closure_findings (design: local-sized-tasks 1.3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_closure  # noqa: E402


def _tree(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def f():\n    return 1\n")
    (pkg / "test_mod.py").write_text("from mod import f\n")
    (pkg / "test_other.py").write_text("def test_x():\n    pass\n")
    return ["pkg/test_mod.py", "pkg/test_other.py"]


def _task(file="`pkg/mod.py`", targets="none", raw=""):
    return {"fields": {"File": file, "Targets": targets}, "raw": raw}


def test_importer_named_not_unrelated(tmp_path):
    tf = _tree(tmp_path)
    out = task_closure.closure_findings(_task(), tmp_path, tf)
    assert len(out) == 1, out
    assert "pkg/test_mod.py" in out[0], out
    assert "test_other.py" not in out[0], out


def test_listed_or_named_gives_empty(tmp_path):
    tf = _tree(tmp_path)
    listed = _task(targets="`pkg/test_mod.py`")
    assert task_closure.closure_findings(listed, tmp_path, tf) == []
    named = _task(raw="pkg/test_mod.py must stay green, untouched\n")
    assert task_closure.closure_findings(named, tmp_path, tf) == []


def test_new_and_md_files_not_scanned(tmp_path):
    tf = _tree(tmp_path)
    (tmp_path / "notes.md").write_text("mod\n")
    assert task_closure.closure_findings(
        _task(file="`pkg/mod.py` (new)"), tmp_path, tf) == []
    assert task_closure.closure_findings(
        _task(file="`notes.md`"), tmp_path, tf) == []


def test_no_git_repo_gives_empty(tmp_path):
    _tree(tmp_path)
    assert task_closure.closure_findings(_task(), tmp_path, None) == []


def test_script_run_and_importorskip_named(tmp_path):
    tf = _tree(tmp_path)
    (tmp_path / "pkg" / "test_cli.py").write_text('RUN = ["python", "mod.py"]\n')
    (tmp_path / "pkg" / "test_skip.py").write_text(
        'import pytest\npytest.importorskip("mod")\n')
    tf += ["pkg/test_cli.py", "pkg/test_skip.py"]
    out = task_closure.closure_findings(_task(), tmp_path, tf)
    assert len(out) == 1
    assert "pkg/test_cli.py" in out[0] and "pkg/test_skip.py" in out[0], out


def test_dotted_import_named(tmp_path):
    tf = _tree(tmp_path)
    (tmp_path / "pkg" / "test_dotted.py").write_text("from pkg.mod import f\n")
    tf.append("pkg/test_dotted.py")
    out = task_closure.closure_findings(_task(), tmp_path, tf)
    assert "pkg/test_dotted.py" in out[0], out
