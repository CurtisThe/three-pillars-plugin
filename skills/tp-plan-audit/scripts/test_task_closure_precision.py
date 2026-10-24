"""Precision tests for task_closure.closure_findings (design: followups-1023 1.7)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_closure  # noqa: E402


def _tree(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def f():\n    return 1\n")
    (pkg / "test_mod.py").write_text("from mod import f\n")
    return ["pkg/test_mod.py"]


def _task(targets="none", raw=""):
    return {"fields": {"File": "`pkg/mod.py`", "Targets": targets}, "raw": raw}


def test_node_only_targets_still_reported(tmp_path):
    tf = _tree(tmp_path)
    t = "`pkg/test_mod.py::test_x`"
    task = _task(targets=t, raw=f"**Targets**: {t}\n")
    out = task_closure.closure_findings(task, tmp_path, tf)
    assert len(out) == 1, out
    assert "pkg/test_mod.py" in out[0], out


def test_whole_file_targets_exempt(tmp_path):
    tf = _tree(tmp_path)
    task = _task(targets="`pkg/test_mod.py`")
    assert task_closure.closure_findings(task, tmp_path, tf) == []


def test_longer_token_does_not_name_test(tmp_path):
    tf = _tree(tmp_path)
    task = _task(raw="pkg/subtest_mod.py is unrelated\n")
    out = task_closure.closure_findings(task, tmp_path, tf)
    assert len(out) == 1, out
    assert "pkg/test_mod.py" in out[0], out


def test_exact_name_in_text_exempts(tmp_path):
    tf = _tree(tmp_path)
    task = _task(raw="pkg/test_mod.py must stay green, untouched.")
    assert task_closure.closure_findings(task, tmp_path, tf) == []


def _deep_tree(tmp_path):
    pkg = tmp_path / "pkg" / "sub"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text("def f():\n    return 1\n")
    (pkg / "test_mod.py").write_text("from mod import f\n")
    return ["pkg/sub/test_mod.py"]


def _deep_task(raw):
    return {"fields": {"File": "`pkg/sub/mod.py`", "Targets": "none"}, "raw": raw}


def test_path_suffix_names_test(tmp_path):
    tf = _deep_tree(tmp_path)
    for named in ("sub/test_mod.py", "test_mod.py", "pkg/sub/test_mod.py"):
        task = _deep_task(f"{named} must stay green, untouched.")
        assert task_closure.closure_findings(task, tmp_path, tf) == [], named


def test_suffix_rule_stays_token_exact(tmp_path):
    tf = _deep_tree(tmp_path)
    for named in ("sub/xtest_mod.py", "sub/test_mod.pyc", "other/sub/test_mod.py"):
        task = _deep_task(f"{named} is unrelated.")
        assert len(task_closure.closure_findings(task, tmp_path, tf)) == 1, named


def test_multiline_targets_not_name_search_text(tmp_path):
    tf = _tree(tmp_path)
    raw = ("**Targets**: `pkg/test_other.py`,\n"
           "  `pkg/test_mod.py::test_x`\n"
           "**Red**: write it\n")
    task = _task(targets="`pkg/test_other.py`, `pkg/test_mod.py::test_x`", raw=raw)
    out = task_closure.closure_findings(task, tmp_path, tf)
    assert len(out) == 1, out
    assert "pkg/test_mod.py" in out[0], out


def test_text_after_multiline_targets_still_names(tmp_path):
    tf = _tree(tmp_path)
    raw = ("**Targets**: `pkg/test_other.py`,\n  `pkg/test_other2.py`\n"
           "**Red**: pkg/test_mod.py must stay green, untouched.\n")
    task = _task(targets="`pkg/test_other.py`", raw=raw)
    assert task_closure.closure_findings(task, tmp_path, tf) == []
