#!/usr/bin/env python3
"""permission_refusal.py — a refused tool call, read where it is written, as a rule an operator adds.

design: strata-classifier-cost-followups (design §A3; plan Task 1.5)

A child launched with `dontAsk` and a deny list can have a call refused. That refusal is a named
fast-failure class (`permission-refused`), and the ladder can only act on it if the refused call is
read out of the child and carried in the reply the ladder already reads. Two readings, in that order:

1. the host result's structured `permission_denials` — the `--output-format json` object the child
   printed last (`_smoke_waited` parses the same object the same way), naming tool and input;
2. only as a fallback, the prose `Permission to use … has been denied` in free text or in a
   transcript's `tool_result` blocks — the exact `dontAsk` wording is unverified, so it is a fallback
   and never the first reading. In a transcript only the harness's **own error result** counts (task
   2.4, F1): `is_error` true *and* text *starting* with the denial prefix — quoted denial prose (a
   Grep/Read of a fixture, a Bash log) never flags.

Either way the answer is the **rule text an operator would add** to the allow list: `Bash(rm -rf
build)`, or a bare tool name where the tool takes no command (`WebFetch`). `lines` renders those rules
as the leading `permission-refused: <rule>` lines of a worker's reply file (the ladder's `F`, which
§2 step 6 reads with `--reply-json F`); `parse_lines` is its inverse, and Task 1.6's classifier reads
the banner with it — `extract` cannot match the banner's own shape. Every function returns a list and
never raises: a reader of a live transcript or a half-written result object answers `[]`. Stdlib only.
"""
from __future__ import annotations

import re

__all__ = ["DENIED_RE", "BANNER", "rule_of", "from_result", "extract", "from_records", "lines",
           "parse_lines"]

# The CLI's refusal prose: tool + optional command in one capture, the fallback reading.
DENIED_RE = re.compile(r"Permission to use (.+?) has been denied")
_WITH_COMMAND = " with command "
BANNER = "permission-refused: "


def rule_of(tool: str, command: str | None = None) -> str:
    """The rule an operator would add: `<Tool>(<command>)`, or the bare tool name without one."""
    tool = str(tool or "").strip()
    command = str(command or "").strip()
    return f"{tool}({command})" if tool and command else tool


def _dedup(rules: list[str]) -> list[str]:
    """The rules in order of first appearance, each once."""
    seen: dict[str, None] = {}
    for rule in rules:
        if rule:
            seen.setdefault(rule, None)
    return list(seen)


def from_result(obj) -> list[str]:
    """The rules of a host result's structured `permission_denials`; [] for anything else."""
    denials = obj.get("permission_denials") if isinstance(obj, dict) else None
    rules = []
    for denial in denials if isinstance(denials, list) else []:
        if not isinstance(denial, dict):
            continue
        tool_input = denial.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        rules.append(rule_of(str(denial.get("tool_name") or ""),
                             str(command) if isinstance(command, str) else None))
    return _dedup(rules)


def extract(text: str) -> list[str]:
    """The rules named by refusal prose in free text — the fallback reading. Deduped."""
    rules = []
    for found in DENIED_RE.findall(str(text or "")):
        tool, _, command = found.partition(_WITH_COMMAND)
        rules.append(rule_of(tool.strip(), command.strip() or None))
    return _dedup(rules)


def _block_text(content) -> str:
    """A `tool_result` block's content as text: a string, or its `text` blocks joined."""
    if isinstance(content, str):
        return content
    parts = [str(b.get("text")) for b in content if isinstance(b, dict)
             and isinstance(b.get("text"), str)] if isinstance(content, list) else []
    return "\n".join(parts)


def _denial_rule(text: str) -> str:
    """The rule of a denial whose text starts (after whitespace) with the denial prose; else ""."""
    found = DENIED_RE.match(str(text or "").lstrip())
    if found is None:
        return ""
    tool, _, command = found.group(1).partition(_WITH_COMMAND)
    return rule_of(tool.strip(), command.strip() or None)


def from_records(records) -> list[str]:
    """The rules of the harness's denial results in transcript records; [] for anything else.

    A block counts only when the harness marked it `is_error` *and* its text *begins* with the denial
    prose — the denial for the call it refused. The same words quoted elsewhere never flag.
    """
    rules = []
    for rec in records if isinstance(records, list) else []:
        content = rec.get("message", {}).get("content") if isinstance(rec, dict) else None
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_result" \
                    and block.get("is_error") is True:
                rules.append(_denial_rule(_block_text(block.get("content"))))
    return _dedup(rules)


def lines(rules: list[str]) -> list[str]:
    """The reply-file banner: one `permission-refused: <rule>` line per rule, in order."""
    return [BANNER + rule for rule in _dedup(list(rules or []))]


def parse_lines(text: str) -> list[str]:
    """The rules of the leading `permission-refused: ` lines of `text` — `lines`'s inverse.

    Only the leading block counts: the banner is what `cmd_wait` prepends above the worker's own
    reply, so the same text anywhere later in the reply is the worker quoting something, not a
    refusal it hit.
    """
    rules = []
    for line in str(text or "").splitlines():
        if not line.startswith(BANNER):
            break
        rules.append(line[len(BANNER):].strip())
    return _dedup(rules)
