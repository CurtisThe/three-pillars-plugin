"""test_settings_shipped.py — G4 pin test (plugin-mode-parity, Task 3.5).

Catalog G4: shipped `settings.json`'s `statusLine.command` hard-references
`~/.claude/statusline.sh`, a `$HOME` install the plugin never performs (the
plugin ships `statusline.sh` to the cache root, not into `~/.claude/`; a
one-time operator copy is required — see `tp-docs-init/SKILL.md`'s
existence-guarded offer). Without an existence guard the command fails on
every render for a consumer who never ran that copy.

Pins: the shipped `statusLine.command` must not invoke the script
unconditionally — it must guard on the file's existence (or the key must be
absent). Dev-repo behavior (a consumer who HAS installed the script) must be
preserved: the guarded command still runs the script when present (S4).
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_settings() -> dict:
    return json.loads((_REPO_ROOT / "settings.json").read_text(encoding="utf-8"))


def test_status_line_command_is_existence_guarded_or_absent():
    """statusLine.command does not hard-require ~/.claude/statusline.sh to exist."""
    settings = _load_settings()
    status_line = settings.get("statusLine")
    if status_line is None:
        return  # key dropped entirely — also a valid catalog-chosen fix
    command = status_line.get("command", "")
    assert command != "~/.claude/statusline.sh", (
        "statusLine.command is the bare unconditional invocation with no "
        "existence guard — fails on every render for a consumer who never "
        "copied statusline.sh to ~/.claude/statusline.sh"
    )
    # The guard must actually test for the file before invoking it.
    assert "-x" in command or "-f" in command, (
        f"statusLine.command lacks an existence guard (-x/-f test): {command!r}"
    )


def test_status_line_command_still_references_statusline_sh_when_guarded():
    """Dev-repo behavior preserved: the guarded command still names the real script path."""
    settings = _load_settings()
    status_line = settings.get("statusLine")
    if status_line is None:
        return
    command = status_line.get("command", "")
    assert "statusline.sh" in command, (
        f"guarded statusLine.command must still invoke statusline.sh when present: {command!r}"
    )
