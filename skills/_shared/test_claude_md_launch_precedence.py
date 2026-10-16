"""Token pins: the three CLAUDE templates state the launch precedence (launch-role-precedence 1.9).

Each repo CLAUDE template carries the same four-line precedence as
`skills/_shared/design-run-launch.md`: this launch's flags > the role (backend and Remote
Control only) > `routes.conf` (everything else) > never the parent session's env — plus the
`CLAUDE_LAUNCHER_ROLE=run` token and the link to the launch doc. The paragraph is found by its
`**Launching design runs**` marker. Token pins only — see `skills/_shared/test-fragility.md`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ("CLAUDE.md", "CLAUDE.plugin.md", "CLAUDE.pro.md")
MARKER = "Launching design runs"
# the four items, highest first, in the order design-run-launch.md states them
ITEMS = ("flags passed on this launch",
         "the role (backend and Remote Control only)",
         "routes.conf (everything else)",
         "never the parent session's env")


def _paragraph(name: str) -> str:
    text = re.sub(r"\s+", " ", (ROOT / name).read_text(encoding="utf-8"))
    assert MARKER in text, name
    return text[text.index(MARKER):][:1200]


@pytest.mark.parametrize("name", TEMPLATES)
def test_paragraph_lists_the_four_items_in_order(name):
    body = _paragraph(name)
    pos = -1
    for item in ITEMS:
        at = body.find(item)
        assert at != -1, (name, item)
        assert at > pos, (name, item)
        pos = at


@pytest.mark.parametrize("name", TEMPLATES)
def test_paragraph_names_the_run_role_and_the_launch_doc(name):
    body = _paragraph(name)
    assert "CLAUDE_LAUNCHER_ROLE=run" in body, name
    assert "skills/_shared/design-run-launch.md" in body, name
