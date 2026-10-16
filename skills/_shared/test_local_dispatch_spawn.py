#!/usr/bin/env python3
"""test_local_dispatch_spawn.py — `local-dispatch.md` §3 has ONE spawn template, in the background.

design: prompt-cache-aware-dispatch (Task 1.5; Behavior 1). Every rung — `local-*`, `sonnet-*`,
`opus-*` — spawns through the same background `Agent(...)` call; what differs per rung is the wait
path, never the spawn. Parsed structure only (`ast` over the fenced ```python blocks), never doc
wording (operator rule: no prose pins on markdown; `skills/_shared/test-fragility.md`).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DISPATCH = (HERE / "local-dispatch.md").read_text(encoding="utf-8")


def _section3() -> str:
    start = DISPATCH.index("\n## 3.")
    return DISPATCH[start:DISPATCH.index("\n## 4.", start)]


def _agent_calls() -> list[ast.Call]:
    """Every `Agent(...)` call in a ```python block of §3, parsed, never matched as text."""
    calls: list[ast.Call] = []
    for block in re.findall(r"```python\n(.*?)```", _section3(), re.S):
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Agent":
                calls.append(node)
    return calls


def test_one_spawn_template_for_every_rung():
    calls = _agent_calls()
    assert len(calls) == 1, f"§3 must hold exactly one spawn template, found {len(calls)}"


def test_the_template_spawns_in_the_background():
    keywords = {kw.arg: kw.value for kw in _agent_calls()[0].keywords}
    for name in ("run_in_background", "subagent_type", "model"):
        assert name in keywords, name
    bg = keywords["run_in_background"]
    assert isinstance(bg, ast.Constant) and bg.value is True, bg
    assert isinstance(keywords["subagent_type"], ast.Constant)
    assert keywords["subagent_type"].value == "{agent_ref}"
    assert isinstance(keywords["model"], ast.Constant)
    assert keywords["model"].value == "{model}"
