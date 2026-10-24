"""sizing_limits.py — the one home of every task-sizing threshold.

design: local-sized-tasks §Entities. TEST_HELPERS names framework-internal
helpers and applies only in the framework tree.
"""
import re

SOFT_HEADROOM = 0.10
MAX_RED_CLAUSES = 6
MAX_GROWTH = 120
MAX_READ_TOKENS = 40_000
BYTES_PER_TOKEN = 4
MAX_ENTRY_POINTS = 1
ENV_PATTERN = re.compile(r"real pytest|tmp git|worktree|subprocess", re.I)
TEST_HELPERS = ("inner_pytest", "clean_git_env", "commit_pair",
                "attempt_fixture", "make_seat", "agent_worktree")
