"""The project allow rules cover `.tp-scratch/` worktrees (launch-role-precedence 3.4)."""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"

OLD = [
    "Bash(git worktree remove .claude/worktrees/*)",
    "Bash(git worktree remove --force .claude/worktrees/*)",
    "Bash(git worktree add .claude/worktrees/*)",
    "Bash(git worktree add -q --detach .claude/worktrees/*)",
]
NEW = [
    "Bash(git worktree remove .tp-scratch/*)",
    "Bash(git worktree remove --force .tp-scratch/*)",
    "Bash(git worktree add .tp-scratch/*)",
    "Bash(git worktree add -q --detach .tp-scratch/*)",
]


def _allow():
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"]


def test_settings_parses_as_json():
    assert isinstance(_allow(), list)


def test_tp_scratch_worktree_rules_allowed():
    allow = _allow()
    for rule in NEW:
        assert rule in allow


def test_existing_claude_worktree_rules_kept():
    allow = _allow()
    for rule in OLD:
        assert rule in allow
