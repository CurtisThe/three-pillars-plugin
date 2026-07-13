#!/usr/bin/env python3
"""validate_artifact.py — Structural validation engine for artifact types.

Supports three v1 schemas: design, spec, plan. Schemas are registered in the
SCHEMAS dispatch table — adding a new type is a new entry, not an engine change.

CLI:
    python3 skills/_shared/validate_artifact.py <type> <path>

Exit codes:
    0  PASS  — well-formed artifact
    1  BLOCKED — one or more blocking violations; JSON verdict on stderr
    2  usage error (bad arguments, file not found)

Pure stdlib: re, sys, json, pathlib, dataclasses. No prompts, no network.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    """One structural defect in an artifact."""

    code: str
    message: str
    location: str
    severity: str = "block"  # "block" | "warn" — only "block" flips verdict


@dataclass
class Verdict:
    """Result of validating one artifact."""

    verdict: str           # "PASS" | "BLOCKED"
    schema_version: int    # artifact type's schema version
    artifact_type: str     # "design" | "spec" | "plan"
    violations: list[Violation] = field(default_factory=list)
    skipped: int = 0       # plan schema: count of spike tasks skipped

    @classmethod
    def from_violations(
        cls,
        artifact_type: str,
        schema_version: int,
        violations: list[Violation],
        skipped: int = 0,
    ) -> "Verdict":
        """Fold violations into a verdict: BLOCKED iff any block-severity violation."""
        verdict_str = _fold_verdict(violations)
        return cls(
            verdict=verdict_str,
            schema_version=schema_version,
            artifact_type=artifact_type,
            violations=violations,
            skipped=skipped,
        )


def _fold_verdict(violations: list[Violation]) -> str:
    """BLOCKED iff any violation has severity == 'block'; WARN-only or empty → PASS."""
    if any(v.severity == "block" for v in violations):
        return "BLOCKED"
    return "PASS"


# ---------------------------------------------------------------------------
# Schema type alias
# ---------------------------------------------------------------------------

Schema = Callable[[str], list[Violation]]

# ---------------------------------------------------------------------------
# Design schema helpers (lifted verbatim from validate_design_floor.py)
# Task 1.3: helpers + constants are defined HERE; validate_design_floor.py
# imports them back as a re-export shim (preserving its CLI contract).
# ---------------------------------------------------------------------------

SCHEMA_VERSION_DESIGN = 1

REQUIRED_SECTIONS: list[str] = [
    "Problem",
    "Vision alignment",
    "Scope",
    "Behaviors",
    "Constraints",
]
REQUIRED_SUBSECTIONS: dict[str, list[str]] = {
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
        """Top-level body + every direct ### subsection body for a ## section."""
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


# ---------------------------------------------------------------------------
# Design schema — Task 1.4: register design schema + legacy-JSON parity
# Codes: missing-section / empty-section / placeholder-section map 1:1 to the
# legacy classifier's missing / empty / placeholder_only partition.
# ---------------------------------------------------------------------------


def _design_schema(text: str) -> list[Violation]:
    """Validate design.md against the v1 floor schema."""
    sections = _parse_sections(text)
    classification = _classify(sections)
    violations: list[Violation] = []
    for name in classification["missing"]:
        violations.append(Violation(
            code="missing-section",
            message=f"Required section '{name}' is missing",
            location=name,
            severity="block",
        ))
    for name in classification["empty"]:
        violations.append(Violation(
            code="empty-section",
            message=f"Required section '{name}' is empty",
            location=name,
            severity="block",
        ))
    for name in classification["placeholder_only"]:
        violations.append(Violation(
            code="placeholder-section",
            message=f"Required section '{name}' contains only placeholder content",
            location=name,
            severity="block",
        ))
    return violations


# ---------------------------------------------------------------------------
# Spec schema (uses spec_delta.py)
# Task 2.1: Issue → Violation adapter (thin field-rename, preserves spec codes)
# ---------------------------------------------------------------------------


def _issue_to_violation(issue: object) -> Violation:
    """Thin field-rename adapter: spec_delta.Issue → Violation.

    Preserves the spec_delta Issue code intact (missing-scenario,
    empty-requirement-name, duplicate-op-target, etc.) while giving the
    engine a uniform Violation shape across all three artifact types.
    """
    # Issue has: severity, code, message, location
    severity_map = {"ERROR": "block", "WARN": "warn", "WARNING": "warn"}
    sev = severity_map.get(getattr(issue, "severity", "ERROR"), "block")
    return Violation(
        code=issue.code,
        message=issue.message,
        location=issue.location,
        severity=sev,
    )


def _spec_schema(text: str) -> list[Violation]:
    """Validate a delta-spec file against v1 spec schema.

    Task 2.2: parse + validate + scenario floor.
    Uses spec_delta.parse_delta and spec_delta.validate; wraps SpecParseError
    into a parse-error Violation; adopts the Issue list via _issue_to_violation.
    Registered under 'spec' in SCHEMAS.
    """
    import spec_delta

    try:
        delta = spec_delta.parse_delta(text)
    except spec_delta.SpecParseError as e:
        return [Violation(
            code="parse-error",
            message=str(e),
            location="parse",
            severity="block",
        )]

    # Fail-closed on an empty/whitespace spec: parse_delta returns Delta(ops=[]) for
    # a file with no operation sections, and spec_delta.validate([]) yields no issues
    # -> the gate would PASS blank content. Mirror _plan_schema's no-tasks BLOCK and
    # _design_schema's missing-section BLOCK so all three artifact types fail closed on
    # empty input. (Real-review finding on PR #63.)
    if not delta.ops:
        return [Violation(
            code="no-operations",
            message="Spec delta has no operations (ADDED/MODIFIED/REMOVED/RENAMED ...)",
            location="spec",
            severity="block",
        )]

    issues = spec_delta.validate(delta, base=None)
    violations = [_issue_to_violation(i) for i in issues]

    # Task 2.3: engine delta-consistency policy.
    # MODIFIED + REMOVED on the same requirement is caught by spec_delta.validate
    # as duplicate-op-target (>1 op on one target in one delta). The engine
    # enforces this as blocking by mapping ERROR severity → "block" in
    # _issue_to_violation. Policy lives here (engine layer), not in spec_delta
    # (which stays a pure parse/validate/merge primitive per OQ2 decision).
    # No extra engine rule is needed — spec_delta.validate already covers it.

    return violations


# ---------------------------------------------------------------------------
# Plan schema
# Task 3.1: TASK_FIELD_RE label parsing (both syntaxes)
# Accepts both **Label**: ... (33/34 TDD plans) and - **Label:** ... (fleet-precheck)
# Group(1) is the label text (may contain spaces, normalized to lower-case by caller)
# ---------------------------------------------------------------------------

SCHEMA_VERSION_PLAN = 1

# Matches both **Label**: ... and - **Label:** ... (both conventions in corpus)
# Group(1) is the label text (may contain spaces, normalized by caller)
TASK_FIELD_RE = re.compile(r"^\s*-?\s*\*\*([A-Za-z][A-Za-z ]*?):?\*\*:?\s")
TASK_HEADING_RE = re.compile(r"^###\s+Task\b")

# Task 3.3: per-task spike detection + skip (real-fixture regression)
# Spike tasks are detected per-task by field labels (Hypothesis/Try/Evaluate),
# NOT per-file — so a mixed plan (TDD + spike tasks) works correctly.
# Spike tasks are skipped (skipped++, no violation), never blocked.
_SPIKE_LABELS = frozenset({"hypothesis", "try", "evaluate"})

# Task 3.4: TDD field scoring — required BLOCK, Red/Green WARN, no-tasks
# Required: File/Test/Done when → missing-task-field (BLOCK)
# Strongly-expected: Red/Green → task-field-warning (WARN, non-blocking)
# Optional: Refactor → silent (no violation)
# Plan with zero ### Task headings → no-tasks (BLOCK)
_REQUIRED_FIELDS = frozenset({"file", "test", "done when"})

# Strongly-expected fields for TDD tasks (missing → WARN)
_EXPECTED_FIELDS = frozenset({"red", "green"})


def _extract_field_labels(body: str) -> frozenset[str]:
    """Extract normalized field labels from a task body.

    Task 3.5: dash-style label robustness regression.
    TASK_FIELD_RE accepts both **Label**: and - **Label:** conventions;
    this function normalizes to lower-case with collapsed spaces so both
    syntaxes yield the same frozenset key (e.g., 'done when').
    """
    labels: set[str] = set()
    for line in body.splitlines():
        m = TASK_FIELD_RE.match(line)
        if m:
            # Normalize: lower-case, collapse internal spaces
            label = re.sub(r"\s+", " ", m.group(1).lower().strip())
            labels.add(label)
    return frozenset(labels)


def _segment_tasks(text: str) -> list[tuple[str, str]]:
    """Segment plan text into (heading, body) pairs for each ### Task.

    Task 3.2: task block segmentation under phases.
    Walks the plan text, finds ### Task headings, slices each task body
    as the lines up to the next ###/##/EOF.
    """
    lines = text.splitlines()
    tasks: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_body_lines: list[str] = []

    for line in lines:
        if TASK_HEADING_RE.match(line):
            if current_heading is not None:
                tasks.append((current_heading, "\n".join(current_body_lines)))
            current_heading = line.strip()
            current_body_lines = []
        elif current_heading is not None:
            # Stop collecting body at next ## or ### heading (non-Task)
            # But TASK_HEADING_RE already handles ### Task lines above.
            # A ## or non-Task ### heading ends the current task's body.
            if re.match(r"^#{2,3}\s", line) and not TASK_HEADING_RE.match(line):
                # End current task body, but don't start a new task
                tasks.append((current_heading, "\n".join(current_body_lines)))
                current_heading = None
                current_body_lines = []
            else:
                current_body_lines.append(line)

    if current_heading is not None:
        tasks.append((current_heading, "\n".join(current_body_lines)))

    return tasks


def _plan_schema(text: str) -> list[Violation]:
    """Validate a plan.md against the v1 plan schema."""
    tasks = _segment_tasks(text)

    if not tasks:
        return [Violation(
            code="no-tasks",
            message="Plan has no ### Task headings",
            location="plan",
            severity="block",
        )]

    violations: list[Violation] = []
    skipped_count = 0  # tracked via metadata; returned via Verdict.skipped

    # Store skipped count in a mutable container so the caller can access it
    _plan_schema._last_skipped = 0  # type: ignore[attr-defined]

    for heading, body in tasks:
        labels = _extract_field_labels(body)

        # Spike detection: any Hypothesis/Try/Evaluate label → skip this task
        if labels & _SPIKE_LABELS:
            skipped_count += 1
            continue

        # TDD task: check required fields
        for req_field in sorted(_REQUIRED_FIELDS):
            if req_field not in labels:
                violations.append(Violation(
                    code="missing-task-field",
                    message=f"Required field '{req_field}' is missing",
                    location=heading,
                    severity="block",
                ))

        # Strongly-expected fields: WARN
        for exp_field in sorted(_EXPECTED_FIELDS):
            if exp_field not in labels:
                violations.append(Violation(
                    code="task-field-warning",
                    message=f"Expected field '{exp_field}' is missing",
                    location=heading,
                    severity="warn",
                ))

        # Refactor: optional, silent (no violation)

    _plan_schema._last_skipped = skipped_count  # type: ignore[attr-defined]
    return violations


# ---------------------------------------------------------------------------
# SCHEMAS dispatch table — Task 1.2: registry + dispatch + parse-error guard
# Adding a new artifact type is a single new entry here (extensible without
# engine changes, per the design constraint).
# ---------------------------------------------------------------------------

SCHEMAS: dict[str, Schema] = {
    "design": _design_schema,
    "spec": _spec_schema,
    "plan": _plan_schema,
}

_SCHEMA_VERSIONS: dict[str, int] = {
    "design": SCHEMA_VERSION_DESIGN,
    "spec": 1,
    "plan": SCHEMA_VERSION_PLAN,
}


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------


def validate_artifact(artifact_type: str, path: Path) -> Verdict:
    """Dispatch to the registered schema and fold violations into a Verdict.

    Never raises on a well-formed-but-invalid artifact. A parse failure
    becomes a single BLOCKED Violation (code='parse-error').
    """
    schema = SCHEMAS.get(artifact_type)
    if schema is None:
        return Verdict.from_violations(
            artifact_type,
            0,
            [Violation(
                code="unknown-type",
                message=f"Unknown artifact type: {artifact_type!r}",
                location="dispatch",
                severity="block",
            )],
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return Verdict.from_violations(
            artifact_type,
            _SCHEMA_VERSIONS.get(artifact_type, 1),
            [Violation(
                code="parse-error",
                message=f"Cannot read file: {e}",
                location=str(path),
                severity="block",
            )],
        )

    try:
        violations = schema(text)
    except Exception as e:
        violations = [Violation(
            code="parse-error",
            message=f"Schema raised an error: {e}",
            location=str(path),
            severity="block",
        )]

    # Retrieve skipped count for plan schema
    skipped = 0
    if artifact_type == "plan":
        skipped = getattr(_plan_schema, "_last_skipped", 0)

    return Verdict.from_violations(
        artifact_type,
        _SCHEMA_VERSIONS.get(artifact_type, 1),
        violations,
        skipped=skipped,
    )


# ---------------------------------------------------------------------------
# CLI — Task 4.1: main(argv) dispatch + exit codes + stderr JSON
# Exit 0 PASS / 1 BLOCKED (JSON on stderr) / 2 usage error.
# Channel contract: JSON verdict goes to stderr ONLY, never stdout.
# ---------------------------------------------------------------------------


def _verdict_to_dict(verdict: Verdict) -> dict:
    return {
        "verdict": verdict.verdict,
        "schema_version": verdict.schema_version,
        "artifact_type": verdict.artifact_type,
        "violations": [
            {
                "code": v.code,
                "message": v.message,
                "location": v.location,
                "severity": v.severity,
            }
            for v in verdict.violations
        ],
        "skipped": verdict.skipped,
    }


def main(argv: list[str]) -> int:
    # Parse: validate_artifact.py <type> <path>
    # NOTE: cross-spec base validation (spec_delta.validate(delta, base=...)) is not
    # yet wired to a CLI flag; the spec schema validates with base=None. A documented
    # but unparsed --base flag was removed here (real-review finding on PR #63) to
    # avoid a fake contract — re-add it together with the argv parsing when wired.
    if len(argv) < 3:
        print(
            "usage: validate_artifact.py <type> <path>",
            file=sys.stderr,
        )
        return 2

    artifact_type = argv[1]
    if artifact_type not in SCHEMAS:
        print(
            f"unknown artifact type: {artifact_type!r}\n"
            f"known types: {', '.join(sorted(SCHEMAS))}",
            file=sys.stderr,
        )
        return 2

    path = Path(argv[2])

    # Task 4.2: design directory-arg parity with legacy validate_design_floor.py CLI.
    # When type is 'design' and the path is a directory, resolve to design.md inside.
    if artifact_type == "design" and path.is_dir():
        path = path / "design.md"

    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    verdict = validate_artifact(artifact_type, path)

    if verdict.verdict == "BLOCKED":
        print(json.dumps(_verdict_to_dict(verdict)), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
