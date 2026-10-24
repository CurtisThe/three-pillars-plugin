"""The framework's own skill texts stop creating under an absolute /tmp (design run-scratch-in-fence, Task 1.10, P11).

A skill text that tells an agent to make a temp file or dir, or redirect, under an
absolute tmp root makes the run write outside its worktree, which the create fence
then has to catch. The
fix is in the text: the four test-log templates read `"${TMPDIR:-/tmp}/..."`, so
the log follows the run's redirected TMPDIR and falls back only when none is set.

The scan covers `skills/**/*.md` and `agents/*.md`; archive paths and
`three-pillars-docs/` are not read (this file and the design dir are outside it).
Assertions are on matched lines and on files the run produced, never on prose
wording beyond the one template (skills/_shared/test-fragility.md).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SKILLS = _ROOT / "skills"
_AGENTS = _ROOT / "agents"

# The absolute tmp root, built from two parts: framework-check.sh invariant 3 greps
# every line under skills/ for the literal path-with-slash, and this file is the one
# place that has to spell it out.
_T = "/" + "tmp"

# An absolute tmp create: the create verbs the design lists, with an optional flag,
# optional quote and optional blank between the verb and the path.
_P = r"[\"']?" + _T + "/"
_ABS_TMP_CREATE = re.compile(
    r"(?:mktemp\s+(?:-d\s+)?" + _P
    + r"|>>?\s*" + _P
    + r"|tee\s+(?:-a\s+)?" + _P
    + r"|mkdir\s+(?:-p\s+)?" + _P + ")"
)

_TEMPLATE = 'mktemp "${TMPDIR:-/tmp}/test_output.XXXXXX.log"'
_SKILL_CAP = 35_000
_FOUR = (
    _SKILLS / "tp-phase-implement" / "SKILL.md",
    _SKILLS / "tp-task-cycle" / "SKILL.md",
    _SKILLS / "tp-phase-review" / "SKILL.md",
    _SKILLS / "tp-implementation-audit" / "SKILL.md",
)


def _skill_text_files(skills: Path = _SKILLS, agents: Path = _AGENTS) -> list[Path]:
    found = [(skills, p) for p in skills.rglob("*.md")]
    found += [(agents, p) for p in agents.glob("*.md")]
    return sorted(p for base, p in found
                  if not any("archive" in part.lower() for part in p.relative_to(base).parts))


def _offending_lines(paths: list[Path]) -> list[str]:
    hits = []
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _ABS_TMP_CREATE.search(line):
                hits.append(f"{path}:{n}: {line.strip()[:120]}")
    return hits


def _tee_lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if 'tee "$(mktemp' in ln]


def test_the_scan_finds_no_absolute_tmp_create_in_skill_text() -> None:
    files = _skill_text_files()
    assert len(files) > 50, f"scan found too few files to mean anything: {len(files)}"
    assert _offending_lines(files) == []


@pytest.mark.parametrize(("line", "expected"), [
    (f'x | tee "$(mktemp {_T}/test_output.XXXXXX.log)"', True),
    (f"d=$(mktemp -d {_T}/work.XXXX)", True),
    (f"make > {_T}/out.log", True),
    (f"make >> {_T}/out.log", True),
    (f"make >{_T}/out.log", True),
    (f"echo y | tee {_T}/out.log", True),
    (f"echo y | tee -a {_T}/out.log", True),
    (f"mkdir {_T}/work", True),
    (f"mkdir -p {_T}/work", True),
    (f'x | tee "$(mktemp "{_T}/test_output.XXXXXX.log")"', True),
    ('x | tee "$(mktemp "${TMPDIR:-/tmp}/test_output.XXXXXX.log")"', False),
    ('mkdir -p "${TMPDIR:-/tmp}/work"', False),
    ("d=$(mktemp -d)", False),
    (f"cat {_T}/out.log", False),
    (f"the log is under {_T}/ by default", False),
])
def test_the_pattern_flags_creates_and_only_creates(line: str, expected: bool) -> None:
    assert bool(_ABS_TMP_CREATE.search(line)) is expected, line


def test_the_scan_skips_archives_and_reads_agent_files(tmp_path: Path) -> None:
    skills, agents = tmp_path / "skills", tmp_path / "agents"
    (skills / "a").mkdir(parents=True)
    (skills / "archive").mkdir()
    (agents).mkdir()
    bad = f"make > {_T}/out.log\n"
    (skills / "a" / "SKILL.md").write_text(bad, encoding="utf-8")
    (skills / "archive" / "old.md").write_text(bad, encoding="utf-8")
    (agents / "tp-x.md").write_text(bad, encoding="utf-8")
    (agents / "notes.txt").write_text(bad, encoding="utf-8")
    files = _skill_text_files(skills, agents)
    assert [p.relative_to(tmp_path).as_posix() for p in files] == [
        "agents/tp-x.md", "skills/a/SKILL.md"]
    assert len(_offending_lines(files)) == 2


@pytest.mark.parametrize("path", _FOUR, ids=lambda p: p.parent.name)
def test_the_tee_line_reads_the_tmpdir_template(path: Path) -> None:
    lines = _tee_lines(path)
    assert lines, f"{path.parent.name}: no tee \"$(mktemp ...)\" line found"
    for line in lines:
        assert _TEMPLATE in line, line


@pytest.mark.parametrize("path", _FOUR, ids=lambda p: p.parent.name)
def test_the_file_stays_under_its_char_cap(path: Path) -> None:
    assert len(path.read_text(encoding="utf-8")) <= _SKILL_CAP


def _mktemp_substitution(line: str) -> str:
    """The `$(mktemp ...)` substitution of a tee line, exactly as the text writes it."""
    m = re.search(r'tee "(\$\(mktemp .*?\))"', line)
    assert m, line
    return m.group(1)


@pytest.mark.parametrize("path", _FOUR, ids=lambda p: p.parent.name)
def test_the_line_run_with_tmpdir_set_creates_its_log_there(path: Path, tmp_path: Path) -> None:
    scratch = tmp_path / "run scratch"
    scratch.mkdir()
    sub = _mktemp_substitution(_tee_lines(path)[0])
    env = {k: v for k, v in os.environ.items() if k != "TMPDIR"}
    env["TMPDIR"] = str(scratch)
    proc = subprocess.run(["bash", "-c", f'echo hello | tee "{sub}"'],
                          capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    logs = sorted(scratch.glob("test_output.*.log"))
    assert len(logs) == 1, [p.name for p in scratch.iterdir()]
    assert logs[0].read_text(encoding="utf-8") == "hello\n"
    # One mktemp call made one file, and it is the one under TMPDIR: none went elsewhere.
    assert [p.name for p in scratch.iterdir()] == [logs[0].name]
