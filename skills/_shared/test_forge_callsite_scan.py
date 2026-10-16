"""Tests for forge_callsite_scan.py (design: forge-interface, Task 2.4; invariant 49)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forge_callsite_scan as fcs  # noqa: E402


def _w(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _check(root, baseline=None, paths=None):
    return fcs.check([str(root)] if paths is None else paths, baseline or {}, str(root))


def test_py_argv_literal_outside_baseline_warns(tmp_path):
    _w(tmp_path, "x.py", 'import subprocess\nsubprocess.run(["gh", "pr", "comment", "5"])\n')
    assert _check(tmp_path) == ["x.py: 1 direct gh call(s) outside forge.py and the baseline"]


def test_py_tuple_argv_literal_counts(tmp_path):
    _w(tmp_path, "x.py", 'cmd = ("gh", "api", "x")\n')
    assert fcs.scan([str(tmp_path)], str(tmp_path)) == {"x.py": 1}


def test_markdown_line_warns(tmp_path):
    _w(tmp_path, "SKILL.md", "run\ngh pr comment 5 --body x\n")
    assert _check(tmp_path) == ["SKILL.md: 1 direct gh call(s) outside forge.py and the baseline"]


def test_prose_without_subcommand_is_not_a_call(tmp_path):
    _w(tmp_path, "a.md", "the gh tool, ghost pr, and git pr are fine\n")
    assert fcs.scan([str(tmp_path)], str(tmp_path)) == {}


def test_baselined_at_count_is_silent(tmp_path):
    _w(tmp_path, "y.sh", "gh api a\ngh api b\n")
    assert _check(tmp_path, {"y.sh": 2}) == []


def test_growth_warns(tmp_path):
    _w(tmp_path, "y.sh", "gh api a\ngh api b\ngh api c\n")
    out = _check(tmp_path, {"y.sh": 2})
    assert len(out) == 1 and "growth" in out[0] and "3" in out[0] and "baseline 2" in out[0]


def test_shrunk_is_stale(tmp_path):
    _w(tmp_path, "y.sh", "gh api a\n")
    out = _check(tmp_path, {"y.sh": 2})
    assert len(out) == 1 and "stale" in out[0]


def test_baselined_file_now_zero_is_stale(tmp_path):
    _w(tmp_path, "y.sh", "echo hi\n")
    out = _check(tmp_path, {"y.sh": 2})
    assert len(out) == 1 and out[0].startswith("y.sh: 0") and "stale" in out[0]


def test_forge_and_test_files_exempt(tmp_path):
    _w(tmp_path, "forge_github.py", 'x = ["gh", "pr", "create"]\n')
    _w(tmp_path, "test_x.py", 'x = ["gh", "pr", "create"]\n')
    assert _check(tmp_path) == []


def test_one_line_counts_once_and_skips_dirs(tmp_path):
    _w(tmp_path, "a.sh", "gh pr list; gh pr view\n")
    _w(tmp_path, ".git/b.sh", "gh pr list\n")
    _w(tmp_path, "node_modules/c.sh", "gh pr list\n")
    assert fcs.scan([str(tmp_path)], str(tmp_path)) == {"a.sh": 1}


def test_emit_baseline_round_trips_silent(tmp_path):
    _w(tmp_path, "b.sh", "gh api a\n")
    _w(tmp_path, "a/z.md", "gh pr list\ngh issue view 1\n")
    out = tmp_path / "base.txt"
    paths = [str(tmp_path / "b.sh"), str(tmp_path / "a")]
    assert fcs.emit_baseline(paths, str(out), str(tmp_path)) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#")
    body = [ln for ln in lines if not ln.startswith("#")]
    assert body == ["a/z.md 2", "b.sh 1"]
    base = fcs.read_baseline(str(out))
    assert _check(tmp_path, base, paths) == []


def test_cli_rc0_on_hits_and_prints(tmp_path, capsys):
    _w(tmp_path, "x.sh", "gh pr comment 5\n")
    base = _w(tmp_path, "base.txt", "# c\n")
    rc = fcs.main(["check", "--baseline", str(base), "--root", str(tmp_path), str(tmp_path / "x.sh")])
    assert rc == 0
    assert "x.sh: 1 direct gh call(s) outside forge.py and the baseline" in capsys.readouterr().out


def test_cli_missing_baseline_rc2(tmp_path, capsys):
    rc = fcs.main(["check", "--baseline", str(tmp_path / "nope.txt"), "--root", str(tmp_path), str(tmp_path)])
    assert rc == 2
    assert capsys.readouterr().err.strip()


def test_cli_emit_baseline(tmp_path):
    _w(tmp_path, "x.sh", "gh pr comment 5\n")
    out = tmp_path / "o.txt"
    assert fcs.main(["emit-baseline", "--out", str(out), "--root", str(tmp_path), str(tmp_path / "x.sh")]) == 0
    assert "x.sh 1" in out.read_text(encoding="utf-8")
