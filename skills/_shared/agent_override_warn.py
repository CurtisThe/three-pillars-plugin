#!/usr/bin/env python3
"""agent_override_warn.py — warn about a project-local worker override (Behavior 11).

design: local-implement-and-review

A project-local `.claude/agents/tp-worker.md` or `tp-task-worker.md` replaces the
shipped agent. When it pins a non-Opus model, or carries a `tp-local` marker
(`tp-local-model` / `# tp-local: generated override`), every task it runs uses
that model, which bypasses the per-task eligibility gate. `detect(root)` returns
one warning line per such file, or None.

Fail-open: a missing directory, an unreadable or undecodable file, or any other
error yields no warning. The CLI prints the warning and always exits 0::

    python3 skills/_shared/agent_override_warn.py [--root .]

Model values are normalised by `model_family` (the same rule as the fleet
launcher's local-settings pin check, kept here because `_shared/` ships in the core
build without that skill), so `opus`, `claude-opus-4-8` and `"opus"` all count as Opus.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

AGENT_FILES = ("tp-worker.md", "tp-task-worker.md")
AGENTS_REL = ".claude/agents"
_MARKERS = ("tp-local-model", "# tp-local: generated override")
_MODEL_RE = re.compile(r"^model:\s*(.*?)\s*$", re.M)
_FAMILIES = ("opus", "sonnet", "haiku")


def model_family(model) -> str | None:
    """``opus`` | ``sonnet`` | ``haiku`` for an alias or a ``claude-<family>…`` id;
    any other non-empty value lower-cased as is; None for empty / non-string."""
    if not isinstance(model, str) or not model.strip():
        return None
    m = model.strip().lower()
    return next((f for f in _FAMILIES if m == f or m.startswith(f"claude-{f}")), m)


def _frontmatter(text: str) -> str:
    """The leading ``---`` … ``---`` block, or "" when the file has none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:i])
    return ""


def _warning(rel: str, text: str) -> str | None:
    marker = next((m for m in _MARKERS if m in text), None)
    m = _MODEL_RE.search(_frontmatter(text))
    model = m.group(1).strip("'\"") if m else None
    non_opus = model is not None and model_family(model) != "opus"
    if not (marker or non_opus):
        return None
    why = f"pins model={model}" if non_opus else f"carries the `{marker.lstrip('# ')}` marker"
    return (f"WARNING: project-local agent override {rel} {why}; it bypasses the "
            f"eligibility gate (every task it runs uses that model). Remove it, or pin "
            f"model: opus, and let --local choose per task.")


def detect(root) -> str | None:
    """One warning line per offending override under ``root``, or None (fail-open)."""
    lines = []
    for name in AGENT_FILES:
        rel = f"{AGENTS_REL}/{name}"
        try:
            text = (Path(root) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        line = _warning(rel, text)
        if line:
            lines.append(line)
    return "\n".join(lines) or None


def main(argv=None) -> int:
    try:
        parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        parser.add_argument("--root", default=".")
        args = parser.parse_args(argv)
        message = detect(args.root)
        if message:
            print(message)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — advisory only: never block a run
        print(f"agent_override_warn: skipped ({type(exc).__name__})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
