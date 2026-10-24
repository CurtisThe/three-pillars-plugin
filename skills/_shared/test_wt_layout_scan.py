"""Tests for wt_layout_scan.py (design: worktrees-under-wt-only, Task 1.4). Tmp trees only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wt_layout_scan as w  # noqa: E402

CL = ".claude"
ISO = 'Dispatch Agent(subagent_type="x", isolation="worktree")\n'
FRONT = 'isolation: "worktree"\n'
PY_LINES = [
    'p = Path("' + CL + '") / "worktrees"\n',
    'p = "' + CL + '/worktrees/x"\n',
    'p = repo / "' + CL + '" / "worktrees"\n',
]
GIT_ADD = "git worktree add " + CL + "/worktrees/z\n"


def _put(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _run(root: Path):
    return w.scan([root / "skills", root / "agents"])


def test_rule_a_skill_md(tmp_path):
    _put(tmp_path, "skills/x/SKILL.md", ISO)
    hits = _run(tmp_path)
    assert len(hits) == 1 and hits[0][2] == "A"


def test_rule_a_agent_md(tmp_path):
    _put(tmp_path, "agents/a.md", FRONT)
    assert len(_run(tmp_path)) == 1


YAML_JSON_LINES = [
    "isolation: worktree\n",
    '"isolation": "worktree",\n',
    "isolation: 'worktree'\n",
    'isolation=\\"worktree\\"\n',
    '\\"isolation\\": \\"worktree\\"\n',
]


def test_rule_a_yaml_json_forms(tmp_path):
    """One testcase: every spelling x every file; a single final assert names every file."""
    missed, extra = [], []
    for i, line in enumerate(YAML_JSON_LINES):
        root = tmp_path / f"t{i}"
        _put(root, "agents/a.md", "---\n" + line + "---\n")
        _put(root, "skills/_shared/c.json", line)
        hits = _run(root)
        for path in ("agents/a.md", "skills/_shared/c.json"):
            if not [h for h in hits if h[0] == path and h[2] == "A"]:
                missed.append((path, line))
        extra += [h for h in hits
                  if h[0] not in ("agents/a.md", "skills/_shared/c.json") or h[2] != "A"]
    assert not missed and not extra, (
        f"rule A missed: {missed}; unexpected hits: {extra}; files checked: "
        "agents/a.md skills/_shared/c.json")


@pytest.mark.parametrize("line", [
    "use isolation worktree here\n",
    "the worktree-isolation guard\n",
    "isolation: none\n",
    "isolation: worktrees are removed\n",
])
def test_rule_a_prose_not_hit(tmp_path, line):
    _put(tmp_path, "skills/y/SKILL.md", line)
    assert _run(tmp_path) == []


@pytest.mark.parametrize("line", PY_LINES)
def test_rule_b_py(tmp_path, line):
    _put(tmp_path, "skills/_shared/m.py", "x = 1\n" + line)
    hits = _run(tmp_path)
    assert len(hits) == 1 and hits[0][1] == 2


def test_rule_c_md(tmp_path):
    _put(tmp_path, "skills/y/SKILL.md", GIT_ADD)
    hits = _run(tmp_path)
    assert len(hits) == 1 and hits[0][2] == "C"


@pytest.mark.parametrize("name", ["test_m.py", "conftest.py"])
def test_tests_exempt(tmp_path, name):
    _put(tmp_path, "skills/_shared/" + name, PY_LINES[0] + ISO)
    assert _run(tmp_path) == []


def test_waiver_map_exempt(tmp_path):
    _put(tmp_path, "skills/_shared/gc_agent_worktrees.py", PY_LINES[1])
    assert _run(tmp_path) == []


def test_prose_md_not_hit(tmp_path):
    _put(tmp_path, "skills/y/SKILL.md", "see " + CL + "/worktrees for harness dirs\n")
    assert _run(tmp_path) == []


def test_outside_roots_ignored(tmp_path):
    _put(tmp_path, "docs/a.md", ISO)
    _put(tmp_path, "skills/ok.md", "fine\n")
    assert _run(tmp_path) == []


def test_main_exit_1_and_line(tmp_path, capsys):
    _put(tmp_path, "skills/x/SKILL.md", ISO)
    (tmp_path / "agents").mkdir()
    rc = w.main([str(tmp_path / "skills"), str(tmp_path / "agents")])
    out = capsys.readouterr().out
    assert rc == 1, "skills/x/SKILL.md carries an Agent dispatch: exit 1 expected, got " + repr(rc)
    assert "skills/x/SKILL.md:1: rule A:" in out
    # roots in the other order still scan skills/
    rc = w.main([str(tmp_path / "agents"), str(tmp_path / "skills")])
    out = capsys.readouterr().out
    assert rc == 1, "skills/x/SKILL.md must be scanned when agents/ comes first"
    assert "skills/x/SKILL.md:1: rule A:" in out
    # an Agent dispatch written across several lines is still a hit
    _put(tmp_path, "skills/x/SKILL.md",
         'Dispatch Agent(\n  subagent_type="x",\n  isolation="worktree",\n)\n')
    rc = w.main([str(tmp_path / "skills"), str(tmp_path / "agents")])
    out = capsys.readouterr().out
    assert rc == 1, "skills/x/SKILL.md: a multi-line Agent dispatch must exit 1"
    assert "skills/x/SKILL.md:3: rule A:" in out


def test_main_exit_0_clean(tmp_path):
    _put(tmp_path, "skills/ok.md", "fine\n")
    (tmp_path / "agents").mkdir()
    assert w.main([str(tmp_path / "skills"), str(tmp_path / "agents")]) == 0


def test_main_exit_2_unreadable_root(tmp_path):
    assert w.main([str(tmp_path / "nope")]) == 2
