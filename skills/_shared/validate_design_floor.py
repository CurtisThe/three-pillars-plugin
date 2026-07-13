#!/usr/bin/env python3
"""validate_design_floor.py — Shape A validator gate for /tp-design --auto.

Re-export shim: the section-parsing/classification helpers and the design
schema now live in validate_artifact.py. This module imports them back and
re-serializes to the exact legacy stderr-JSON contract so existing callers
see no change.

CLI (UNCHANGED):
    python3 skills/_shared/validate_design_floor.py <design_dir>

Exit codes (UNCHANGED):
    0  PASS  — well-formed; missing optional sections warn on stderr (not JSON)
    1  BLOCKED — one or more required sections missing / empty / placeholder-only.
                 JSON verdict on stderr (NOT stdout):
                    {"verdict": "BLOCKED",
                     "schema_version": 1,
                     "missing": [...],
                     "empty": [...],
                     "placeholder_only": [...]}
    2  usage error (bad arguments, design.md not found).

Pure stdlib: re, sys, json, pathlib. No prompts, no network, no LLM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Re-import everything from the engine (helpers + constants moved there)
from validate_artifact import (
    OPTIONAL_SECTIONS,
    SCHEMA_VERSION_DESIGN as SCHEMA_VERSION,
    _classify,
    _missing_optional,
    _parse_sections,
)

# Re-export constants for any external importers that reference them by name
from validate_artifact import (  # noqa: F401
    HEADING_RE,
    MIN_CONTENT_CHARS,
    PLACEHOLDER_RE,
    REQUIRED_SECTIONS,
    REQUIRED_SUBSECTIONS,
    _is_non_placeholder_content,
)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_design_floor.py <design_dir>", file=sys.stderr)
        return 2
    design_dir = Path(argv[1])
    design_md = design_dir / "design.md"
    if not design_md.is_file():
        print(f"design.md not found: {design_md}", file=sys.stderr)
        return 2

    sections = _parse_sections(design_md.read_text(encoding="utf-8"))
    classification = _classify(sections)

    if any(classification[k] for k in ("missing", "empty", "placeholder_only")):
        verdict = {
            "verdict": "BLOCKED",
            "schema_version": SCHEMA_VERSION,
            **classification,
        }
        print(json.dumps(verdict), file=sys.stderr)
        return 1

    missing_optional = _missing_optional(sections)
    if missing_optional:
        print(
            "warning: design.md is missing optional section(s): "
            + ", ".join(missing_optional),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
