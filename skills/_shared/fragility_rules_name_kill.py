"""fragility_rules_name_kill.py — the `name-kill` gating fragility rule.

design: no-kill-by-name (Task 1.5)

A process kill by name or pattern (`pkill`, `killall`, a kill of PIDs found by
`pgrep`/`psutil`) hits every matching process on the machine, not only the ones
the code started. The visitor maps `name_kill_py.scan_python` call-site hits to
`Finding`s on both test and production files (registry side `any`).
"""
from __future__ import annotations

import ast
from typing import Iterator

from name_kill_py import scan_tree


def name_kill(tree: ast.AST) -> Iterator:
    from fragility_rules_gating import Finding  # deferred: that module imports this one
    for line in sorted({h.where for h in scan_tree(tree) if h.where}):
        yield Finding("name-kill", line, line)
