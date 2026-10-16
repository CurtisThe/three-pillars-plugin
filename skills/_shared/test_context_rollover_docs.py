"""test_context_rollover_docs.py — prose pins for the ~300k context-hygiene docs.

design: strata-spend-leaks (Task 4.2). The rollover itself is pinned by the driver
and read-side tests; what is at risk here is the **prose a session obeys** — the
`Context window hygiene` paragraph that still tells every session "recommend at
200k", the shared doc the pointer lines lead to, and the two pointers (the launch
watcher step, the run skill) that make the seat's driver discoverable.

Per `skills/_shared/test-fragility.md` these are name-checks scoped to the one
region each reader acts on, not open-ended regexes over free prose: the hygiene
block is sliced between its own bold marker and the next paragraph, the watcher
step between its list marker and the next heading, and every comparison flattens
whitespace first so line wrapping is irrelevant. The count pin on the run skill is
a real measurement (a grandfathered file takes a pointer, not a section).
"""
from __future__ import annotations

import re
from pathlib import Path

import skill_text

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"
PLUGIN_CLAUDE_MD = ROOT / "CLAUDE.plugin.md"
SHARED_DOC = ROOT / "skills" / "_shared" / "context-rollover.md"
LAUNCH_DOC = ROOT / "skills" / "_shared" / "design-run-launch.md"
RUN_SKILL = ROOT / "skills" / "tp-run-full-design" / "SKILL.md"

HYGIENE_START = "**Context window hygiene**"
HYGIENE_END = "**After `/clear`**"
WATCHER_START = "5. **Watcher.**"
POINTER = "context-rollover.md"
HANDOFF_HEADING = "## Handoff protocol"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace flattened, so a substring check survives line wrapping."""
    return " ".join(text.split())


def _hygiene_block(path: Path) -> str:
    """The hygiene paragraph alone: its bold marker to the next paragraph's marker."""
    text = _read(path)
    start = text.index(HYGIENE_START)
    end = text.index(HYGIENE_END, start)
    return _flat(text[start:end])


def _watcher_step(text: str) -> str:
    """Step 5 of the launch defaults, from its marker to the next heading."""
    start = text.index(WATCHER_START)
    match = re.search(r"(?m)^#{2,3} ", text[start:])
    end = start + match.start() if match else len(text)
    return _flat(text[start:end])


def _assert_hygiene(name: str, path: Path) -> None:
    block = _hygiene_block(path)
    assert "~300k" in block, f"{name}: the hygiene text must state the ~300k threshold"
    assert "skills/_shared/context-rollover.md" in block, (
        f"{name}: the hygiene text must point at the shared doc")
    assert "seat" in block, (
        f"{name}: the hygiene text must say the seat drives a design run's rollover")
    assert "advisory" in block, (
        f"{name}: the hygiene text must keep the seat/interactive advice advisory")
    assert "recommend at 200k" not in block, (
        f"{name}: the 200k recommendation is what this task replaces")
    assert "200k" not in _flat(_read(path)), (
        f"{name}: no 200k context threshold survives in this doc")


def test_claude_md_states_300k_rollover():
    _assert_hygiene("CLAUDE.md", CLAUDE_MD)


def test_plugin_claude_md_states_300k_rollover():
    _assert_hygiene("CLAUDE.plugin.md", PLUGIN_CLAUDE_MD)


def test_shared_doc_excludes_the_seat():
    doc = _flat(_read(SHARED_DOC))
    for name in ("context_rollover_drive.py", "/tp-session-save", "/clear",
                 "/tp-session-restore"):
        assert name in doc, f"context-rollover.md must name {name!r}"
    assert "seat is never rolled over" in doc, (
        "context-rollover.md must say the seat is never rolled over")


def test_watcher_step_names_driver():
    step = _watcher_step(_read(LAUNCH_DOC))
    assert "context_rollover_drive.py <slug>" in step, (
        "design-run-launch.md step 5 must name the driver invocation")
    assert "idle" in step, (
        "design-run-launch.md step 5 must tie the driver to an `idle` event")


def test_run_full_design_has_pointer_only():
    """The run skill points at the shared rollover doc on 1-2 lines, all inside its
    Handoff protocol section (which stays in the core SKILL.md), and no `## ` heading
    anywhere in the skill text is a rollover section of its own."""
    lines = skill_text.read_skill_text("tp-run-full-design").splitlines()
    hits = [i for i, line in enumerate(lines) if POINTER in line]
    assert 1 <= len(hits) <= 2, (
        f"the run skill text must carry a pointer to {POINTER} on 1-2 lines, found {len(hits)}")

    start = next(i for i, line in enumerate(lines) if line.startswith(HANDOFF_HEADING))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    outside = [lines[i] for i in hits if not start < i < end]
    assert not outside, f"the {POINTER} pointer sits outside the Handoff protocol section: {outside}"

    core = skill_text.skill_paths("tp-run-full-design")[0].read_text(encoding="utf-8")
    assert "\n".join(lines[start:end + 1]) in core, (
        "the Handoff protocol section and the heading that ends it must both stay in the core SKILL.md")

    headings = [line for line in lines if line.startswith("## ") and "rollover" in line.lower()]
    assert not headings, f"a rollover section grew back in the run skill: {headings}"
