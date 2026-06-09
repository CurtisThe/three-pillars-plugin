#!/usr/bin/env python3
"""spec_drift.py — drift-detection guard for the living-spec-layer.

Scans the base spec tree for dangling anchors and zero-anchor requirements.
Mirrors spec_delta's exit-code + JSON-verdict contract:
  0 — clean (no ERROR Issues)
  1 — DRIFT (at least one ERROR Issue; JSON verdict on stderr)
  2 — usage error

Reuses spec_delta.parse_spec and spec_delta.Issue.
Pure stdlib: re, sys, json, pathlib.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from spec_delta import Issue, Spec, parse_spec

SCHEMA_VERSION = 1

# Annotation prefix pattern: lines like "> Code: ..." or "> Test: ..."
_ANNOTATION_RE = re.compile(
    r"^>\s*(?:Code|Test)\s*:\s*(.+)$",
    re.IGNORECASE,
)

# Symbol definition patterns: "def name" or "class name"
_SYMBOL_DEF_RE = re.compile(r"^\s*(?:def|class)\s+(\w+)\b")


# ---------------------------------------------------------------------------
# Task 1.1 — anchor extraction
# ---------------------------------------------------------------------------

def _extract_anchors(req) -> list[str]:
    """Extract all > Code: / > Test: anchor tokens from a Requirement's block.

    Returns a list of raw anchor tokens (repo-relative paths, symbol@path,
    or path::name).  Returns [] when no annotations are present.
    """
    anchors: list[str] = []
    for line in req.block.splitlines():
        m = _ANNOTATION_RE.match(line.strip())
        if m:
            raw = m.group(1)
            # Strip inline HTML comments before tokenizing so template
            # guidance like `<!-- repo-relative path -->` co-located on an
            # anchor line does not produce spurious dangling-ref anchors.
            raw = re.sub(r"<!--.*?-->", "", raw).strip()
            # Split comma or space-separated entries
            for token in re.split(r"[,\s]+", raw):
                token = token.strip()
                if token:
                    anchors.append(token)
    return anchors


# ---------------------------------------------------------------------------
# Task 1.2 — anchor resolution
# ---------------------------------------------------------------------------

def _parse_anchor(anchor: str):
    """Normalise an anchor into (symbol_or_name, path_str).

    Supports three forms:
      - "rel/path.py"           → (None, "rel/path.py")
      - "symbol@rel/path.py"    → ("symbol", "rel/path.py")
      - "rel/path.py::name"     → ("name", "rel/path.py")
    """
    if "@" in anchor:
        symbol, path_str = anchor.split("@", 1)
        return symbol.strip(), path_str.strip()
    if "::" in anchor:
        path_str, name = anchor.split("::", 1)
        return name.strip(), path_str.strip()
    return None, anchor


def resolve_anchor(anchor: str, repo: Path) -> bool:
    """Return True iff the anchor is satisfied within repo.

    Plain path: the file must exist under repo.
    symbol@path / path::name: the file must exist AND contain a
    'def symbol' or 'class symbol' definition.
    """
    name, path_str = _parse_anchor(anchor)
    full_path = repo / path_str
    if not full_path.exists():
        return False
    if name is None:
        return True
    # Check for symbol definition in the file
    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        m = _SYMBOL_DEF_RE.match(line)
        if m and m.group(1) == name:
            return True
    return False


# ---------------------------------------------------------------------------
# Task 1.3 & 1.4 — scan_spec
# ---------------------------------------------------------------------------

def scan_spec(spec: Spec, repo: Path, strict: bool) -> list[Issue]:
    """Scan all requirements in spec for anchor drift.

    For each requirement:
    - Zero anchors → Issue("WARN"/"ERROR", "zero-anchor", ...)
    - Each unresolvable anchor → Issue("ERROR", "dangling-ref"/"retired-symbol", ...)

    Returns a list of Issue objects (reusing spec_delta.Issue).
    """
    issues: list[Issue] = []
    for req_name, req in spec.requirements.items():
        anchors = _extract_anchors(req)
        if not anchors:
            severity = "ERROR" if strict else "WARN"
            issues.append(Issue(
                severity=severity,
                code="zero-anchor",
                message=f"requirement has no > Code: or > Test: anchors",
                location=req_name,
            ))
            continue
        for anchor in anchors:
            if not resolve_anchor(anchor, repo):
                # Distinguish symbol-form anchors (retired-symbol) vs plain paths (dangling-ref)
                name, path_str = _parse_anchor(anchor)
                if name is not None:
                    code = "retired-symbol"
                else:
                    code = "dangling-ref"
                issues.append(Issue(
                    severity="ERROR",
                    code=code,
                    message=f"anchor does not resolve: {anchor!r}",
                    location=f"{req_name}/{anchor}",
                ))
    return issues


# ---------------------------------------------------------------------------
# Task 1.5 — CLI
# ---------------------------------------------------------------------------

def _verdict_dict(violations: list[Issue]) -> dict:
    """Serialise Issues to the JSON verdict dict (mirrors spec_delta._issue_dict)."""
    return {
        "verdict": "DRIFT",
        "schema_version": SCHEMA_VERSION,
        "violations": [
            {
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
                "location": i.location,
            }
            for i in violations
        ],
    }


def main(argv: list[str]) -> int:
    """CLI entry-point.

    Usage: scan <specs-dir> [--repo <root>] [--strict]

    Exit codes:
      0 — no ERROR Issues (clean)
      1 — DRIFT (at least one ERROR; JSON verdict on stderr)
      2 — usage error
    """
    if not argv or argv[0] != "scan":
        print(
            "usage: spec_drift.py scan <specs-dir> [--repo <root>] [--strict]",
            file=sys.stderr,
        )
        return 2

    args = argv[1:]
    specs_dir_str: str | None = None
    repo_str: str | None = None
    strict = False

    i = 0
    while i < len(args):
        if args[i] == "--repo":
            if i + 1 >= len(args):
                print("usage: scan <specs-dir> [--repo <root>] [--strict]", file=sys.stderr)
                return 2
            repo_str = args[i + 1]
            i += 2
        elif args[i] == "--strict":
            strict = True
            i += 1
        elif args[i].startswith("--"):
            print(f"unknown flag: {args[i]}", file=sys.stderr)
            return 2
        elif specs_dir_str is None:
            specs_dir_str = args[i]
            i += 1
        else:
            print(f"unexpected argument: {args[i]}", file=sys.stderr)
            return 2

    if specs_dir_str is None:
        print("usage: scan <specs-dir> [--repo <root>] [--strict]", file=sys.stderr)
        return 2

    specs_dir = Path(specs_dir_str)
    repo = Path(repo_str) if repo_str else Path.cwd()

    if not specs_dir.is_dir():
        print(f"specs-dir not found: {specs_dir}", file=sys.stderr)
        return 2

    # Discover every <specs-dir>/<domain>/spec.md
    all_violations: list[Issue] = []
    for domain_dir in sorted(specs_dir.iterdir()):
        spec_file = domain_dir / "spec.md"
        if not domain_dir.is_dir() or not spec_file.exists():
            continue
        try:
            text = spec_file.read_text(encoding="utf-8")
            spec = parse_spec(text)
        except Exception as exc:
            all_violations.append(Issue(
                severity="ERROR",
                code="parse-error",
                message=str(exc),
                location=str(spec_file),
            ))
            continue
        # A committed domain spec that parses to zero requirements is almost
        # always a malformed `### Requirement:` header (e.g. the missing space
        # in `###Requirement:`) silently disabling drift detection for the whole
        # domain. Treat it as ERROR so the guard fails loud rather than
        # false-passing an entire domain.
        if not spec.requirements:
            all_violations.append(Issue(
                severity="ERROR",
                code="empty-domain",
                message=(
                    "domain spec parsed to zero requirements — likely a malformed "
                    "`### Requirement:` header; drift detection would be silently disabled"
                ),
                location=str(spec_file),
            ))
            continue
        violations = scan_spec(spec, repo, strict=strict)
        all_violations.extend(violations)

    errors = [v for v in all_violations if v.severity == "ERROR"]
    if errors:
        print(json.dumps(_verdict_dict(errors)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
