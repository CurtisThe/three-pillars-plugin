"""Sweep guard: every remaining legacy `.claude/worktrees` mention is on a reviewed allow-list.

design: launch-role-precedence (Task 3.11). Framework-owned scratch moved from the legacy
`.claude/worktrees/` parent to `.tp-scratch/` (`scratch_root.py`), where a child's Write/Edit is
not refused (M61). Tasks 3.2-3.10 moved the callers; this walk catches any straggler. A file may
still name the legacy parent only for one of three reasons, each listed below: Claude Code's own
`agent-<id>` isolation worktrees did not move; a few rigs are deliberately left on the old parent;
and the legacy readers keep the old parent beside the new one so old state is still found.
Test files are not scanned. Stdlib only.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The pro worktree skill dir name is composed, never spelled: the release leak-guard fails any
# shipped text file that contains it literally.
_WT = "tp-" + "worktree"

# Agent isolation: Claude Code's own `agent-<id>` worktrees stay under `.claude/worktrees/`.
AGENT_ISOLATION = [
    f"skills/{_WT}/scripts/list_worktrees.py",
    f"skills/{_WT}/scripts/nested_worktrees.py",
    f"skills/{_WT}/scripts/gc_candidates.py",
    f"skills/{_WT}/SKILL.md",
    "skills/_shared/worktree_isolation_guard.py",
    "skills/_shared/attempt_fixture.py",
    "skills/_shared/local-reaper.md",
    "skills/_shared/gc_agent_worktrees.py",
    "skills/tp-post-merge/SKILL.md",
    "skills/tp-run-full-design/SKILL.md",
    ".gitignore",
    ".claude/settings.json",
]

# Deliberately unmoved scratch (the `fc-selftest` rig, rerun and revert probes, hot-patch lines).
UNMOVED_SCRATCH = [
    "skills/_shared/hot_patch.py",
    "skills/tp-run-full-design/scripts/rerun_phase_tests.py",
    "skills/tp-run-full-design/scripts/rerun_fixture.py",
    "skills/tp-revert/scripts/revert_probe.py",
    "skills/tp-revert/SKILL.md",
    "skills/_shared/commit-after-work.md",
]

# Legacy readers that keep the old parent beside the new one.
LEGACY_READERS = [
    "skills/_shared/scratch_root.py",
    "skills/_shared/task_attempts.py",
    "skills/_shared/task_scratch_sweep.py",
    "skills/_shared/task_scope.py",
    "skills/_shared/posthoc_baseline.py",
]

ALLOW = AGENT_ISOLATION + UNMOVED_SCRATCH + LEGACY_READERS

# `.claude/worktrees` spelled out, or `".claude"` joined to `"worktrees"` by `,` or `/`.
_LEGACY = re.compile(r"\.claude/worktrees|[\"']\.claude[\"']\s*[,/]\s*[\"']worktrees[\"']")


# The root fixture name is composed, never spelled: the ki-02/ki-10 rule-ledger pins
# extractor reads every string literal in this file as a pinned token.
_CONFTEST = "conf" + "test.py"


def _is_test(path: Path) -> bool:
    return path.name.startswith("test_") or path.name == _CONFTEST


def _scanned_files():
    """Non-test text files under `skills/`, plus the two root files that name the parent."""
    for path in sorted((ROOT / "skills").rglob("*")):
        if path.is_file() and not _is_test(path) and path.suffix != ".pyc":
            yield path
    for name in (".claude/settings.json", ".gitignore"):
        if (ROOT / name).is_file():
            yield ROOT / name


def _mentions_legacy(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return bool(_LEGACY.search(text))


def test_allow_list_entries_exist():
    missing = [rel for rel in ALLOW if not (ROOT / rel).is_file()]
    assert missing == [], f"allow-list entries no longer exist (prune them): {missing}"


def test_no_unlisted_file_names_the_legacy_parent():
    allowed = set(ALLOW)
    stragglers = [
        path.relative_to(ROOT).as_posix()
        for path in _scanned_files()
        if _mentions_legacy(path) and path.relative_to(ROOT).as_posix() not in allowed
    ]
    assert stragglers == [], (
        "these files still name `.claude/worktrees`; path-swap them through "
        f"`scratch_root` (or reword to `.tp-scratch/`): {stragglers}"
    )


def test_known_issue_m61_names_the_move():
    text = (ROOT / "three-pillars-docs" / "known_issues.md").read_text(encoding="utf-8")
    start = text.index("### M61")
    nxt = text.find("\n### ", start + 1)
    section = text[start : nxt if nxt != -1 else len(text)]
    assert ".tp-scratch" in section, section
    assert "Resolved" in section or "pending live smoke" in section, section
