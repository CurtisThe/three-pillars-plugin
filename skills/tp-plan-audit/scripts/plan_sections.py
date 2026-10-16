#!/usr/bin/env python3
"""Detailed-design section extractors for the deterministic plan audit.

Split out of ``audit_plan.py`` by responsibility: pulling the module file list
and the interface names out of a ``detailed-design.md``. ``audit_plan`` re-imports
every name here, so existing callers and tests resolve them through it unchanged.
"""

import re


def extract_section(text, header_re, level=2):
    """Extract content under a heading matching header_re at given level."""
    prefix = "#" * level
    lines = text.split("\n")
    start = end = None
    for i, line in enumerate(lines):
        if start is None:
            if re.match(rf"^{prefix}\s+{header_re}", line, re.IGNORECASE):
                start = i + 1
        elif re.match(rf"^#{{1,{level}}}\s+", line):
            end = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start:end])


def extract_module_files(detailed):
    section = extract_section(detailed, r"Module Structure")
    return [
        m.group(1)
        for line in section.split("\n")
        if (m := re.match(r"\s*[-*]\s+`([^`]+)`", line))
    ]


def extract_interface_names(detailed):
    section = extract_section(detailed, r"Interfaces")
    names = []
    for line in section.split("\n"):
        m = re.match(r"^###\s+`(.+?)`", line)
        if m:
            names.append(m.group(1).strip())
    return names
