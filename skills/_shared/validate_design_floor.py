#!/usr/bin/env python3
"""validate_design_floor.py — Shape A validator gate for /tp-design --auto.

Reads <design_dir>/design.md and decides whether it satisfies v1 of the
design-floor schema: the minimum-completeness contract that lets the
autonomous pipeline run without a human in the loop.

CLI:
    python3 skills/_shared/validate_design_floor.py <design_dir>

Exit codes:
    0  PASS  — well-formed; missing optional sections still produce a
              human-readable warning on stderr but do not block.
    1  BLOCKED — one or more required sections missing / empty / placeholder-only.
                 A JSON verdict is emitted on stderr (NOT stdout):

                    {"verdict": "BLOCKED",
                     "schema_version": 1,
                     "missing": [...],
                     "empty": [...],
                     "placeholder_only": [...]}

    2  usage error (bad arguments, design.md not found).

Pure stdlib: re, sys, json, pathlib. No prompts, no network, no LLM.
Schema version constant lives here under SCHEMA_VERSION = 1 — bump on
extension and add v2 handling if back-compat ever matters.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1

REQUIRED_SECTIONS: list[str] = [
    "Problem",
    "Vision alignment",
    "Scope",
    "Behaviors",
    "Constraints",
]
REQUIRED_SUBSECTIONS: dict[str, list[str]] = {
    # ## Scope must contain a non-empty ### In scope subsection.
    "Scope": ["In scope"],
}
OPTIONAL_SECTIONS: list[str] = ["Dependencies", "Entities", "Open Questions"]

MIN_CONTENT_CHARS = 20
PLACEHOLDER_RE = re.compile(r"^(\.\.\.+|TBD\b.*)$")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")


def _parse_sections(text: str) -> dict[str, str]:
    """Flatten ## and ### headings into a {name: body} map.

    A ### subsection under `## Parent` becomes the key `"Parent.Sub"`. The
    body of a ## heading is the prose between it and the next heading
    (## or ###), not including any ### subsection content. The body of a
    ### heading runs to the next heading of any level.
    """
    sections: dict[str, str] = {}
    current_h2: str | None = None
    current_key: str | None = None
    current_body: list[str] = []

    def _flush() -> None:
        if current_key is not None:
            sections[current_key] = "\n".join(current_body).strip()

    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if not m:
            current_body.append(line)
            continue
        _flush()
        level = len(m.group(1))
        name = m.group(2)
        if level == 2:
            current_h2 = name
            current_key = name
        else:
            current_key = f"{current_h2}.{name}" if current_h2 else name
        current_body = []
    _flush()
    return sections


def _is_non_placeholder_content(body: str) -> bool:
    """Body must contain at least one non-whitespace line that is not a
    placeholder and clears the MIN_CONTENT_CHARS bar (non-whitespace count).
    """
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if PLACEHOLDER_RE.match(line):
            continue
        non_ws = re.sub(r"\s", "", line)
        if len(non_ws) >= MIN_CONTENT_CHARS:
            return True
    return False


def _classify(sections: dict[str, str]) -> dict[str, list[str]]:
    missing: list[str] = []
    empty: list[str] = []
    placeholder_only: list[str] = []

    def _gather_bodies(name: str) -> list[str]:
        """Top-level body + every direct ### subsection body for a ## section.

        Design.md files in this repo conventionally populate a required
        section either inline or via ### subsections (e.g. `## Behaviors`
        with `### Skill shape A/B/C` below). Either form must count as
        non-empty for the parent section.
        """
        prefix = f"{name}."
        return [sections.get(name, "")] + [
            v for k, v in sections.items() if k.startswith(prefix)
        ]

    for name in REQUIRED_SECTIONS:
        if name not in sections:
            missing.append(name)
            continue
        bodies = [b for b in _gather_bodies(name) if b.strip()]
        if not bodies:
            empty.append(name)
        elif not any(_is_non_placeholder_content(b) for b in bodies):
            placeholder_only.append(name)

    for parent, subs in REQUIRED_SUBSECTIONS.items():
        if parent not in sections:
            continue
        for sub in subs:
            key = f"{parent}.{sub}"
            if key not in sections:
                missing.append(key)
                continue
            body = sections[key]
            if not body.strip():
                empty.append(key)
            elif not _is_non_placeholder_content(body):
                placeholder_only.append(key)

    return {"missing": missing, "empty": empty, "placeholder_only": placeholder_only}


def _missing_optional(sections: dict[str, str]) -> list[str]:
    return [name for name in OPTIONAL_SECTIONS if name not in sections]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_design_floor.py <design_dir>", file=sys.stderr)
        return 2
    design_dir = Path(argv[1])
    design_md = design_dir / "design.md"
    if not design_md.is_file():
        print(f"design.md not found: {design_md}", file=sys.stderr)
        return 2

    sections = _parse_sections(design_md.read_text())
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
