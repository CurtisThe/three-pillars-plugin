"""Tests for command_shape_scan.py (design: matchable-commands, Behavior 3) and the rules doc."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import command_shape_scan as scan  # noqa: E402

SHARED = Path(__file__).parent
ROOT = SHARED.parent.parent


@pytest.mark.parametrize("line,shape", [
    ('nohup bash -c "rm -rf x" &', "shell-c-wrapper"),
    ("run `bash -c 'echo hi'`", "shell-c-wrapper"),
    ("sh -c 'git status'", "shell-c-wrapper"),
    ("cd ~/t/master-check && pytest x -q", "cd-then-command"),
    ("cd ~/wt && git log", "cd-then-command"),
    ("S=skills/_shared; python3 $S/x.py", "var-script-path"),
    ("python3 ${SHARED}/y.py --a", "var-script-path"),
    ("export TP_ROOT=$PWD && python3 skills/_shared/x.py", "export-prefix"),
])
def test_flags_unmatchable_shapes(line, shape):
    assert shape in {s for _, s, _ in scan.scan_text(line)}


@pytest.mark.parametrize("line", [
    'python3 "$TP_ROOT"/skills/_shared/x.py',
    "git -C ../wt log -1",
    "python3 -m pytest skills/_shared/test_x.py -q",
    "cd <wt> && claude --model sonnet",
    "bash script.sh",
    "bash -c 'x'  <!-- matchable: ok -->",
    "the `scratch_worktree.py` helper",
])
def test_clean_lines_not_flagged(line):
    assert scan.scan_text(line) == []


def test_scan_tree_lists_and_main_is_advisory(tmp_path, capsys):
    d = tmp_path / "skills" / "tp-x"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("ok\nnohup bash -c 'x' &\n", encoding="utf-8")
    sh = tmp_path / "skills" / "_shared"
    sh.mkdir()
    (sh / "matchable-commands.md").write_text("never bash -c\n", encoding="utf-8")  # the rules doc is exempt
    assert scan.scan_tree(tmp_path) == ["skills/tp-x/SKILL.md:2: [shell-c-wrapper] nohup bash -c 'x' &"]
    assert scan.main(["--root", str(tmp_path)]) == 0  # advisory: exit 0 even with hits
    assert "1 advisory hit" in capsys.readouterr().out


def test_rules_doc_names_each_rule_and_cites_real_scripts():
    doc = (SHARED / "matchable-commands.md").read_text(encoding="utf-8")
    for needle in ("git -C", "bash -c", "nohup", "export TP_ROOT", "scratch_worktree.py",
                   "child_spawn.py start", "run_in_background", "command_shape_scan.py"):
        assert needle in doc, needle
    for script in re.findall(r"skills/_shared/([a-z_]+\.py)", doc):
        if script != "x.py":  # `x.py` is the doc's placeholder script name
            assert (SHARED / script).exists(), script
