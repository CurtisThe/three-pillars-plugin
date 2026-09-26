"""A halted `--local` run's `recover` command is one `task_verify` itself accepts.

design: local-implement-and-review (Task 6.6, design-audit-3 #4; operator rulings on #165)

A `tp-attempt-*` worktree left under `.claude/worktrees/` by a crashed or halted
`--local` run would block the nested-worktree teardown, so `/tp-design-complete`'s
preflight runs `task_verify.py sweep` first; a halted run's operator gets the `recover`
command from the exit-2 JSON instead. This checks code only: the `recover` line the CLI
emits names `task_verify.py` and parses with its own argparse. The SKILL.md prose has no
contract check (known_issues L97).
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "_shared"))

import task_verify  # noqa: E402

TV = "skills/_shared/task_verify.py"


def test_recover_command_parses():
    python, script, *argv = shlex.split(task_verify.recover_command({"attempt_id": "a b"}))
    assert Path(script) == ROOT / TV and python == "python3"
    assert argv == ["discard", "--attempt", "a b"]
    args = task_verify._parser().parse_args(argv)
    assert (args.cmd, args.attempt) == ("discard", "a b")
