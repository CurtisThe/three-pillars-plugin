"""fragility_registry.py — the one list of fragility rule ids.

design: fragile-test-prevention (detailed-design-lint §Rule registry)

`RULES` is the single registry the CLI, the predicate, the triage ledger and
every test table iterate, so none of them keeps a second copy. A rule is a
named value: id, side (`test`, `production`, or `any` for both), family (`gating` or `flag`),
the day-one gating flag, and a one-line summary. Promoting a rule to gating
after its false positives are measured is a one-line change to `gating` here
(or a `fragility.gating_rules` entry in a repo's config, read by `gating_set`).
"""
from __future__ import annotations

from dataclasses import dataclass


class ConfigError(ValueError):
    """A repo config references a rule id that is not in `RULES` (exit 2)."""


@dataclass(frozen=True)
class Rule:
    id: str
    side: str
    family: str
    gating: bool
    summary: str


RULES = (
    Rule("golden-hash", "test", "gating", True,
         "an equality assert pinning a digest of a file read to a value not "
         "computed in the test"),
    Rule("shape-pin", "test", "gating", True,
         "inspect.getsource / ast.parse tracing to a module's own source "
         "instead of behaviour"),
    Rule("deny-literal", "production", "gating", True,
         "a filter-named binding to a hand-written literal collection instead "
         "of a derived allowlist"),
    Rule("name-kill", "any", "gating", True,
         "a process kill by name or pattern (pkill, killall, kill of searched "
         "PIDs) instead of a PID the code started"),
    Rule("md-read-assert", "test", "flag", False,
         "asserting on raw markdown text instead of a parsed structure"),
    Rule("line-literal", "test", "flag", False,
         "asserting an exact line number constant"),
    Rule("doc-line-cap", "test", "flag", False,
         "asserting an exact line/line-count total of a markdown doc"),
    Rule("prose-regex", "production", "flag", False,
         "regexing over prose without a closed grammar"),
    Rule("wall-clock", "test", "flag", False,
         "sleeping or asserting on a wall-clock elapsed constant"),
)


def gating_set(config: dict | None) -> list[str]:
    """The rules that gate on exit 1, from a repo config dict.

    Default: the ids of the rules with `gating=True`, in registry order.
    If `config["fragility"]["gating_rules"]` is a list of ids, that list
    replaces the default set — an unknown id raises `ConfigError`.
    """
    fragility = (config or {}).get("fragility") or {}
    if "gating_rules" not in fragility:
        return [rule.id for rule in RULES if rule.gating]
    override = fragility["gating_rules"]
    known = {rule.id for rule in RULES}
    for rule_id in override:
        if rule_id not in known:
            raise ConfigError(f"fragility.gating_rules unknown rule id: {rule_id!r}")
    return list(override)
