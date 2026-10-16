"""Charters of the four hand-written agents match `model_policy.agent_spec`.

design: run-throughput (Task 3.3).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_implement_config  # noqa: E402
import model_policy  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

AGENTS = Path(__file__).resolve().parent.parent.parent / "agents"
TOOLS = {
    "tp-generator": None,
    "tp-runbook": None,
    "tp-impl-auditor": ["Read", "Grep", "Glob", "Bash"],
    "tp-review-confirmer": ["Read", "Grep", "Glob", "Bash"],  # delivers via `put` (Bash)
    "tp-spawn-host": ["Agent"],
}


def _load(name: str) -> tuple[dict, str]:
    path = AGENTS / f"{name}.md"
    assert path.is_file(), path
    text = path.read_text(encoding="utf-8")
    return parse_frontmatter(text), text


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_charter_matches_spec(name):
    fm, text = _load(name)
    spec = model_policy.agent_spec(name, None, local_implement_config.DEFAULTS)
    assert fm["name"] == name
    assert fm["model"] == spec["model"]
    assert fm["effort"] == spec["effort"]
    if TOOLS[name] is None:
        assert "tools" not in fm
    else:
        assert json.loads(fm["tools"]) == TOOLS[name]
    assert "agents/_shared/project-scope.md" in text


def test_runbook_stops_on_block():
    _, text = _load("tp-runbook")
    low = text.lower()
    assert "stop and report" in low
    for word in ("refusal", "permission denial", "classifier block"):
        assert word in low
    assert "never retry another way" in low
    assert "never use `--no-verify`" in text
    assert "never use `--force`" in text


def test_impl_auditor_is_read_only():
    _, text = _load("tp-impl-auditor")
    assert "never** edit, write, or commit" in text


def test_confirmer_bash_is_read_only_except_put():
    """review-proof-out-of-tree 1.5: no Write tool; the one write is `put` via Bash."""
    _, text = _load("tp-review-confirmer")
    line = next(ln for ln in text.splitlines() if "Bash is for read-only execution only" in ln)
    assert "round_scratch.py put" in line


def test_spawn_host_spec():
    """strata-session-isolation 1.4: the spawn host is a fixed-Sonnet shell."""
    assert model_policy.agent_spec("tp-spawn-host", None,
                                   local_implement_config.DEFAULTS) == {
        "role": "spawn-host", "model": "sonnet", "effort": "low"}
