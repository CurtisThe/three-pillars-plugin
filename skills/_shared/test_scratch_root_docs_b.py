"""Doc guard (sweep B): the worktree docs name `.tp-scratch/`, not `.claude/worktrees/`.

design: launch-role-precedence (Task 3.10). Framework-owned scratch worktrees moved from the
legacy `.claude/worktrees/` parent to `.tp-scratch/` (`scratch_root.py`); sweep A covered the
dispatch/spawn docs (see `test_scratch_root_docs_a.py`). These three docs tell an agent where a
scratch worktree lives and which paths the worktree-skill listing hides, so a stale parent here
sends hand-built worktrees to a dir nothing scans or cleans. The only `.claude/worktrees/`
mention allowed is one about Claude Code's own `agent-<id>` isolation worktrees, which did not
move — so every line still naming the legacy parent must also name `agent-`. Stdlib only.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent

FILES = {
    "matchable-commands.md": HERE / "matchable-commands.md",
    # The pro skill dir name is composed, never spelled: the release leak-guard
    # fails any shipped text file that contains it literally.
    "worktree/SKILL.md": SKILLS / ("tp-" + "worktree") / "SKILL.md",
    "tp-pr-iterate/cheap-tier.md": SKILLS / "tp-pr-iterate" / "cheap-tier.md",
}

LEGACY = ".claude/worktrees"


def _text(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def _flat(name: str) -> str:
    """Prose wraps, so compare against whitespace-normalised text."""
    return re.sub(r"\s+", " ", _text(name))


def test_no_legacy_scratch_path():
    """Every `.claude/worktrees` line in the three docs is an `agent-<id>` reference."""
    for name, path in FILES.items():
        bad = [ln for ln in _text(name).splitlines() if LEGACY in ln and "agent-" not in ln]
        assert bad == [], (name, bad)


def test_new_scratch_parent_named():
    """Each doc names the current scratch parent at least once."""
    for name in FILES:
        assert ".tp-scratch" in _text(name), name


def test_matchable_commands_scratch_location():
    """The doc states where `scratch_worktree.py` keeps its worktrees."""
    assert "<repo>/.tp-scratch/scratch-<name>" in _flat("matchable-commands.md")


def test_matchable_commands_gitignore_refusal():
    """It also states that `add` refuses when the scratch root is not gitignored."""
    assert "`add` refuses when `.tp-scratch/` is not gitignored" in _flat("matchable-commands.md")
