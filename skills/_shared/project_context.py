"""project_context.py — Load and size-check the project-context.md living doc.

Reads `three-pillars-docs/project-context.md` from the repo root and returns
a prompt-ready block for injection into spawned-agent prompts (council Round 1,
tp-phase-implement workers). Mirrors the stderr-BLOCKED-JSON / exit-code idiom
of validate_design_floor.py and the soft/hard two-band cap of file_size_guard.py.

Public surface:
    INJECTED_HARD_CAP  — 12,288 bytes (hard cap; over this → raise / exit 1)
    INJECTED_SOFT_CAP  — 10,240 bytes (soft cap; over this → warn on stderr)
    ProjectContextTooLarge — raised by load_context_block when over hard cap
    measure(path)          — UTF-8 encoded byte count
    load_context_block(root=None) -> str  — load + size-check + wrap
    scaffold_stub(root=None) -> bool  — write a placeholder doc when absent (idempotent)
    main(argv) -> int      — CLI `check` | `scaffold` subcommands

Stdlib-only: sys, json, pathlib + in-repo project_root. No network, no LLM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from project_root import find_project_root

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INJECTED_HARD_CAP: int = 12_288  # bytes — injected-context bound
INJECTED_SOFT_CAP: int = 10_240  # bytes — soft-warn threshold

_DOC_RELPATH = Path("three-pillars-docs") / "project-context.md"
_BLOCK_HEADER = "## Project context (injected — do not re-derive)"

# Placeholder scaffold written by /tp-docs-init (and referenced by /tp-setup) when
# the doc is absent. Fixed schema (## Conventions / ## Stack / ## Domain rules) with
# a one-line purpose header + operator-fill guidance. Deliberately terse and far
# under the INJECTED_HARD_CAP so a freshly scaffolded doc always loads cleanly.
STUB_CONTENT = """\
This file is injected into every spawned subagent (council members, phase-implement /
run-full-design workers, pr-fix / readonly-auditor dispatches) so they carry project
conventions without re-deriving them from the codebase. Keep it terse and under the
~12 KB injected cap. Replace each placeholder below with your project's real rules,
then delete this sentence.

## Conventions

- **Imports**: <import ordering + dependency manager — e.g. stdlib-first, then third-party, then local>
- **Module layout**: <one responsibility per file? where do modules and tests live?>
- **Naming**: <test-file naming pattern, directory conventions>
- **Commits**: <scoped `git add`? conventional-commit prefixes? trailer policy?>

## Stack

- **Language / runtime**: <languages and versions>
- **Frameworks / libraries**: <primary frameworks a worker must match>
- **Test command**: <the canonical command that runs the test suite>

## Domain rules

- <a project-specific invariant or vocabulary a generic agent would not infer>
- <another domain rule — keep terse; the injected cap forces discipline>
"""


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ProjectContextTooLarge(Exception):
    """Raised when project-context.md exceeds INJECTED_HARD_CAP bytes.

    Attributes:
        bytes: measured byte count of the file.
        cap:   the hard cap that was exceeded (always INJECTED_HARD_CAP).
    """

    def __init__(self, byte_count: int, cap: int) -> None:
        self.bytes = byte_count
        self.cap = cap
        super().__init__(
            f"project-context.md is {byte_count} bytes, exceeds hard cap {cap}"
        )


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def measure(path: Path) -> int:
    """Return the UTF-8 encoded byte count of the file at *path*."""
    return len(path.read_bytes())


def load_context_block(root: "Path | None" = None) -> str:
    """Load project-context.md and return a prompt-ready block.

    Args:
        root: repo root directory. When None, resolved via find_project_root().
              If resolution returns None (not a git repo), returns "".

    Returns:
        A non-empty prompt-ready string when the doc exists and is within the
        hard cap, or "" when the doc is absent or root resolution fails.

    Raises:
        ProjectContextTooLarge: when the doc exceeds INJECTED_HARD_CAP bytes.
    """
    # Resolve root
    if root is None:
        resolved = find_project_root()
        if resolved is None:
            return ""
        root = resolved

    doc_path = Path(root) / _DOC_RELPATH
    if not doc_path.is_file():
        return ""

    # Read the raw bytes once. An unreadable file (permissions, a race) is a
    # resolution failure, not an operator over-cap error — fail open to "" so an
    # advisory injection never crashes a council/worker dispatch.
    try:
        raw = doc_path.read_bytes()
    except OSError:
        return ""

    byte_count = len(raw)
    if byte_count > INJECTED_HARD_CAP:
        raise ProjectContextTooLarge(byte_count, INJECTED_HARD_CAP)

    # Decode as UTF-8. A malformed (non-UTF-8) doc is likewise a resolution
    # failure — fail open rather than abort the dispatch with a raw decode error.
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""

    # A present-but-empty / whitespace-only doc injects nothing — never an
    # orphaned header over an empty body (behavior 12's intent extends here).
    if not body.strip():
        return ""

    return f"{_BLOCK_HEADER}\n\n{body}\n\n"


def scaffold_stub(root: "Path | None" = None) -> bool:
    """Write a placeholder project-context.md when absent. Idempotent.

    Creates `{root}/three-pillars-docs/project-context.md` from STUB_CONTENT if
    it does not already exist, creating the parent dir if needed. **Never
    overwrites an existing file** — the design principle "never overwrite
    operator work" — so re-running is a safe no-op.

    Args:
        root: repo root directory. When None, resolved via find_project_root().
              If resolution returns None (not a git repo), no-op.

    Returns:
        True if the stub was written, False if a doc already existed or the root
        could not be resolved (both no-ops).
    """
    if root is None:
        resolved = find_project_root()
        if resolved is None:
            return False
        root = resolved

    doc_path = Path(root) / _DOC_RELPATH
    if doc_path.exists():
        return False  # never overwrite operator work

    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(STUB_CONTENT, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """CLI entry point. argv excludes the program name.

    Usage: project_context.py {check|scaffold}

    `check`    — size-check the doc (exit 1 on over-cap, advisory warn in the
                 soft band, exit 0 otherwise).
    `scaffold` — write a placeholder doc when absent (idempotent, exit 0).

    Exit codes:
        0  — doc absent, unreadable, under soft cap, or in the soft-warn band (advisory);
             also every `scaffold` outcome (created or already-present)
        1  — doc exceeds INJECTED_HARD_CAP (BLOCKED)
        2  — usage error (missing or unknown subcommand)
    """
    if not argv or argv[0] not in ("check", "scaffold"):
        print("usage: project_context.py {check|scaffold}", file=sys.stderr)
        return 2

    if argv[0] == "scaffold":
        root = find_project_root()
        if root is None:
            print("no repo root resolved — nothing scaffolded", file=sys.stderr)
            return 0
        created = scaffold_stub(root)
        rel = str(_DOC_RELPATH)
        print(f"created {rel}" if created else f"{rel} already exists — left unchanged")
        return 0

    # argv[0] == "check": resolve root from cwd
    root = find_project_root()
    if root is None:
        # No repo — absent is a no-op
        return 0

    doc_path = root / _DOC_RELPATH
    if not doc_path.is_file():
        return 0

    # A present-but-unreadable doc (permissions, I/O race) is a resolution
    # failure, not an operator over-cap block — fail open to the advisory 0
    # exit, mirroring load_context_block's OSError handling.
    try:
        byte_count = measure(doc_path)
    except OSError:
        return 0

    if byte_count > INJECTED_HARD_CAP:
        verdict = {
            "verdict": "BLOCKED",
            "schema_version": 1,
            "bytes": byte_count,
            "cap": INJECTED_HARD_CAP,
        }
        print(json.dumps(verdict), file=sys.stderr)
        return 1

    if byte_count > INJECTED_SOFT_CAP:
        print(
            f"warning: project-context.md is {byte_count} bytes "
            f"(soft cap {INJECTED_SOFT_CAP}); consider trimming before the "
            f"hard cap ({INJECTED_HARD_CAP}) is reached",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
