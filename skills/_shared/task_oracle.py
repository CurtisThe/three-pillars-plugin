"""task_oracle.py — the plan **Oracle** and **Entry point** fields: a task's test grammars.

design: fragile-test-prevention (detailed-design-stages Part A)

A plan task declares which oracle styles its tests use in one strict field::

    **Oracle**: example, property

* ``field := "none" | type ("," type)*`` (whitespace around a comma is free);
* ``type``: one of ``ORACLE_TYPES``; unknown types and duplicates are errors;
* the pairing rule: a ``property`` or ``metamorphic`` test has at least one
  ``example`` from the spec, so a pairing type without ``example`` is malformed;
* ``none``: the task declares no oracle style — valid only when its Targets
  field is also ``none`` (``validate_pair``).

The **Entry point** field names what the tests reach::

    **Entry point**: `skills/_shared/x.py::check`, `skills/tp-plan/SKILL.md`

* ``field := "none" | item ("," item)*``; ``item := "`" path ["::" qualname] "`"``;
* ``path``: ``task_targets.path_errors(path, any_ext=True)`` — the Targets
  path-segment rule over any extension (a prose task names its ``SKILL.md``);
* ``qualname``: dotted Python identifiers (``Cls.meth``); duplicates are errors;
* ``none``: valid only with Targets ``none`` (``validate_pair``).

``ORACLE_TYPES`` is the single registry — ``test-fragility.md`` names it rather
than keeping a second copy of the list. ``types`` come back in registry order,
so ``render_oracle`` output parses back to the same ``types`` (round-trip).
Both parsers return ``{kind, types|items, errors}`` like ``parse_targets``, so
``audit_oracle`` and any runtime reader share one grammar. Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ORACLE_TYPES = ("example", "property", "metamorphic", "schema", "round-trip",
                "differential")
PAIRING_TYPES = ("property", "metamorphic")

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import task_targets  # noqa: E402 — sibling grammar module


def parse_oracle(field: str | None) -> dict:
    """A task's **Oracle** field → ``{kind, types, errors}``.

    ``kind`` is ``ok`` (``types`` in ``ORACLE_TYPES`` order), ``missing``
    (field absent) or ``malformed`` (an error naming each offending item:
    unknown type, duplicate, empty item, pairing type without ``example``).
    """
    if field is None:
        return {"kind": "missing", "types": [], "errors": []}
    text = field.strip()
    if text == "none":
        return {"kind": "ok", "types": [], "errors": []}
    errors: list[str] = []
    seen: set[str] = set()
    for item in (p.strip() for p in text.split(",")):
        if not item:
            errors.append(f"empty Oracle type {''!r}")
        elif item not in ORACLE_TYPES:
            errors.append(f"unknown Oracle type {item!r}")
        elif item in seen:
            errors.append(f"duplicate Oracle type {item!r}")
        else:
            seen.add(item)
    types = [t for t in ORACLE_TYPES if t in seen]
    if not errors:
        for t in PAIRING_TYPES:
            if t in types and "example" not in types:
                errors.append(f"Oracle type {t!r} requires an 'example' type")
    return {"kind": "malformed" if errors else "ok", "types": types,
            "errors": errors}


def render_oracle(parsed: dict) -> str:
    """Canonical text of a parsed Oracle: ``none``, else the types in registry
    order, comma-separated. Parsing the result gives the same ``types``."""
    return ", ".join(parsed["types"]) or "none"


def parse_entry_point(field: str | None) -> dict:
    """A task's **Entry point** field → ``{kind, items, errors}``.

    ``kind`` is ``ok``, ``missing`` (field absent) or ``malformed`` (an error naming
    each offending item). ``items`` are ``{path, symbol}`` (``symbol`` is ``None`` for
    a bare path) in field order; ``none`` is ``ok`` with no items.
    """
    if field is None:
        return {"kind": "missing", "items": [], "errors": []}
    text = field.strip()
    if text == "none":
        return {"kind": "ok", "items": [], "errors": []}
    items: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in (p.strip() for p in text.split(",")):
        if not raw:
            errors.append(f"empty Entry point item {raw!r}")
            continue
        if len(raw) < 2 or raw[0] != "`" or raw[-1] != "`" or "`" in raw[1:-1]:
            errors.append(f"Entry point item {raw!r} is not a single backticked item")
            continue
        content = raw[1:-1]
        path, sep, qualname = content.partition("::")
        bad = task_targets.path_errors(path, any_ext=True)
        if sep:
            bad += [f"bad qualname part {q!r} in {content!r} (a Python identifier)"
                    for q in qualname.split(".") if not q.isidentifier()]
        if content in seen:
            bad.append(f"duplicate Entry point item {content!r}")
        seen.add(content)
        errors += bad
        if not bad:
            items.append({"path": path, "symbol": qualname if sep else None})
    return {"kind": "malformed" if errors else "ok", "items": items,
            "errors": errors}


def render_entry_point(parsed: dict) -> str:
    """Canonical text of a parsed Entry point: ``none``, else the backticked items
    in field order, comma-separated. Parsing the result gives the same value."""
    return ", ".join(
        "`" + i["path"] + (f"::{i['symbol']}" if i["symbol"] else "") + "`"
        for i in parsed["items"]) or "none"


def validate_pair(oracle: dict, targets_field: str | None,
                  entry_point: dict | str | None = None) -> list[str]:
    """Pairing rule against the task's **Targets** field ([] = passes).

    An Oracle — or an Entry point (parsed, or its raw field text) — of ``none`` is
    refused unless the Targets field (via ``task_targets.parse_targets``) is ``none``.
    """
    if isinstance(entry_point, str):
        entry_point = parse_entry_point(entry_point)
    nones = [name for name, parsed, key in (("Oracle", oracle, "types"),
                                            ("Entry point", entry_point, "items"))
             if parsed and parsed.get("kind") == "ok" and not parsed.get(key)]
    if nones and task_targets.parse_targets(targets_field).get("reason") != task_targets.NONE:
        return [f"{name} is none: the task's Targets field must be none" for name in nones]
    return []
