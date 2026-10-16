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

Model values are normalised by `model_family`, which delegates to
`model_policy.agent_alias` (the one family normaliser, shared with the fleet
launcher's local-settings pin check), so `opus`, `claude-opus-4-8` and `"opus"` —
each with or without a `[1m]` suffix — all count as Opus.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import effort_pins  # noqa: E402
import model_policy  # noqa: E402  (agent_alias: the one family normaliser)

AGENT_FILES = ("tp-worker.md", "tp-task-worker.md")
AGENTS_REL = ".claude/agents"
_MARKERS = ("tp-local-model", "# tp-local: generated override")
_MODEL_RE = re.compile(r"^model:\s*(.*?)\s*$", re.M)


def model_family(model) -> str | None:
    """The Agent-enum family (``model_policy.agent_alias``: an alias or a
    ``claude-<family>-…`` id, a trailing `[…]` suffix dropped); any other
    non-empty value lower-cased as is; None for empty / non-string."""
    if not isinstance(model, str) or not model.strip():
        return None
    return model_policy.agent_alias(model) or model.strip().lower()


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


def detect(root, env=None) -> str | None:
    """One warning line per offending override under ``root``, then the
    ``CLAUDE_CODE_EFFORT_LEVEL`` pin line (``env=None`` means ``os.environ``); None when
    there are none (fail-open). Settings-file effort pins are not overrides and are
    never reported (``effort_pins``)."""
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
    try:
        env = os.environ if env is None else env
        lines += effort_pins.detect(env)
    except Exception:  # noqa: BLE001 — advisory only
        pass
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
