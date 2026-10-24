"""Tests for task_sizing.check_task_sizing (design: local-sized-tasks 2.1)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_closure  # noqa: E402
import task_sizing  # noqa: E402


def _task(file="`pkg/mod.py`", raw="", targets=None, red="x", tid="1.1"):
    fields = {"File": file, "Red": red}
    if targets:
        fields["Targets"] = targets
    return {"id": tid, "name": "n", "fields": fields, "raw": raw}


def _mod(tmp_path, lines):
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n" * lines)


def test_headroom(tmp_path):
    _mod(tmp_path, 265)
    t = _task(raw="**Growth**: +50\n")
    assert task_sizing.check_task_sizing([t], tmp_path) == []
    _mod(tmp_path, 266)
    out = task_sizing.check_task_sizing([t], tmp_path)
    assert len(out) == 1, out
    assert "**Split**" in out[0][2]
    t = _task(raw="**Growth**: +50\n**Split**: pkg/mod_b.py\n")
    assert task_sizing.check_task_sizing([t], tmp_path) == []


def test_production_size(tmp_path):
    f = "`pkg/new.py` (new)"
    over = task_sizing.check_task_sizing(
        [_task(f, "**Growth**: +121\n")], tmp_path)
    assert len(over) == 1, over
    assert task_sizing.check_task_sizing(
        [_task(f, "**Growth**: +120\n")], tmp_path) == []


def test_read_budget(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.md").write_text("a" * 100_000)
    (tmp_path / "pkg" / "test_b.md").write_text("b" * 61_000)
    t = _task("`pkg/a.md`", targets="`pkg/test_b.md`")
    out = task_sizing.check_task_sizing([t], tmp_path)
    assert any("read" in o[2] for o in out), out


def test_warn_shape_seven_clause_red(tmp_path):
    red = "(a) a; (b) b; (c) c; (d) d; (e) e; (f) f; (g) g"
    out = task_sizing.check_task_sizing(
        [_task("`pkg/new.py` (new)", red=red, tid="3.2")], tmp_path)
    assert out, out
    for o in out:
        assert o[0] == "WARN" and o[1] == "Task 3.2: n"
        assert o[2].startswith("sizing: ")


def test_env_helpers(tmp_path):
    t = _task("`pkg/new.py` (new)", red="uses inner_pytest beside tmp git")
    out = task_sizing.check_task_sizing([t], tmp_path)
    assert any("test helper" in o[2] for o in out), out
    t = _task("`pkg/new.py` (new)", red="uses my_fixture beside tmp git")
    cfg = tmp_path / ".three-pillars"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        json.dumps({"plan_audit": {"test_helpers": ["my_fixture"]}}))
    assert task_sizing.check_task_sizing([t], tmp_path) == []


def test_blank_helper_item_names_no_helper(tmp_path):
    t = _task("`pkg/new.py` (new)", red="uses nothing beside tmp git")
    cfg = tmp_path / ".three-pillars"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        json.dumps({"plan_audit": {"test_helpers": ["", "   "]}}))
    out = task_sizing.check_task_sizing([t], tmp_path)
    assert any("test helper" in o[2] for o in out), out


def test_fail_open(tmp_path, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_bytes(b"\xff\xfe\x00bad\n")
    t = _task(red="tmp git")
    cfg = tmp_path / ".three-pillars"
    cfg.mkdir()
    for body in ({"plan_audit": []}, {"plan_audit": {"test_helpers": "x"}}):
        (cfg / "config.json").write_text(json.dumps(body))
        task_sizing.check_task_sizing([t], tmp_path)

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(task_closure, "closure_findings", boom)
    out = task_sizing.check_task_sizing([_task()], tmp_path)
    assert [o[2] for o in out] == ["sizing: check skipped (RuntimeError)"]
