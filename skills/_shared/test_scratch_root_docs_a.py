"""Doc guard (sweep A): the dispatch/spawn docs name `.tp-scratch/`, not `.claude/worktrees/`.

design: launch-role-precedence (Task 3.9). Framework-owned scratch — child-spawn prompts,
attempt worktrees, `cheap-watch` state and cheap scratch worktrees — moved from the legacy
`.claude/worktrees/` parent to `.tp-scratch/` (`scratch_root.py`). A dispatcher executes this
prose literally, so a stale path there spawns into a dir nothing scans or cleans. The only
`.claude/worktrees/` mention allowed in these four files is one about Claude Code's own
`agent-<id>` isolation worktrees, which did not move — so every line still naming the legacy
parent must also name `agent-`. Stdlib only.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent

FILES = {
    "strata-spawn.md": HERE / "strata-spawn.md",
    "local-dispatch.md": HERE / "local-dispatch.md",
    "cheap-dispatch.md": HERE / "cheap-dispatch.md",
    "tp-pr-fix/SKILL.md": SKILLS / "tp-pr-fix" / "SKILL.md",
}

LEGACY = ".claude/worktrees"


def _text(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def test_no_legacy_scratch_path():
    """Every `.claude/worktrees` line in the four docs is an `agent-<id>` reference."""
    for name, path in FILES.items():
        bad = [ln for ln in _text(name).splitlines() if LEGACY in ln and "agent-" not in ln]
        assert bad == [], (name, bad)


def test_new_scratch_parent_named():
    """Each doc names the current scratch parent at least once."""
    for name in FILES:
        assert ".tp-scratch" in _text(name), name
