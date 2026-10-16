"""living_doc_scaffold.py — the condensed scaffold for the four living docs.

design: skill-context-diet (D3 shape, D5 caps, D8 consumer templates).

A living doc is an index of what is true now; the archive is the record. So the
template `/tp-setup` and `/tp-docs-init` write in a consumer repo is already in
the condensed shape from day one:

  - one row or bullet per current item (never a multi-paragraph entry);
  - a `## History` heading at the end, one line per update;
  - the one-line pointer `> History and evidence live in <archive>.`;
  - the cold archive sibling, seeded with `living_doc_archive.ARCHIVE_HEADER`;
  - `known_issues` additionally gets the cold `known_issues_low.md` (D5b) and
    the "N Low issues → `known_issues_low.md`" pointer in the live doc, so the
    live file carries High and Medium only.

Every template is far under its `file_size_guard.char_caps` soft cap, so a fresh
consumer scaffold never warns and never blocks (D8 behaviour 0). Scaffolding
**never overwrites** an existing doc or archive — operator work wins, so the call
is an idempotent no-op on a repo that already has the doc.

Public surface:
    DOC_NAMES             — the closed set of `doc` names.
    LOW_DOC_REL           — repo-relative path of the cold Low doc.
    scaffold(root, doc)   — write one doc (+ its archive); the rel paths written.
    scaffold_all(root)    — every doc; the rel paths written.
    main(argv) -> int     — CLI `--doc <name>` | `--all` [--repo-root R].

Stdlib only. CLI modelled on `project_context.py scaffold`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from living_doc_archive import ARCHIVE_HEADER, archive_for
from project_root import find_project_root

DOCS_DIR = "three-pillars-docs"

# doc name -> repo-relative live-doc path. The closed set the plan names.
DOC_PATHS: dict[str, str] = {
    "vision": f"{DOCS_DIR}/vision.md",
    "architecture": f"{DOCS_DIR}/architecture.md",
    "product_roadmap": f"{DOCS_DIR}/product_roadmap.md",
    "known_issues": f"{DOCS_DIR}/known_issues.md",
}
DOC_NAMES: tuple[str, ...] = tuple(DOC_PATHS)

# The cold Low doc (D5b): exempt from the caps, never a live section.
LOW_DOC_REL = f"{DOCS_DIR}/known_issues_low.md"
LOW_DOC_CONTENT = (
    "# Known Issues — LOW\n"
    "\n"
    "> Cold storage for Low issues, one line each. Moved out of "
    " [`known_issues.md`](known_issues.md) so the live doc stays one-Read-pass "
    "small. Promoting a Low to Medium (or High) moves its entry back into the "
    "live doc in the same commit.\n"
    "\n"
    "- L<nn> — <one-line symptom>. <fix pointer: design/PR/issue>\n"
)

# ---------------------------------------------------------------------------
# Templates (module constants — the condensed shape, D3)
# ---------------------------------------------------------------------------

VISION_TEMPLATE = """\
# Vision

*Last updated: <YYYY-MM-DD> — see [History](#history) for the full changelog.*

> History and evidence live in vision_archive.md.

## Problem
<What pain this project eliminates, and for whom. 2-4 sentences.>

## Users
<Who this is for, and who it is not for.>

## Principles
- **<principle>** — what it means, and when it applies as a tie-breaker.

## Non-goals
- **<non-goal>** — what this project will explicitly never become, and why.

## Success signals
- <Qualitative sign the vision is being realized. Not a metric.>

## History
- <YYYY-MM-DD> — one-sentence summary of what changed.
"""

ARCHITECTURE_TEMPLATE = """\
# Architecture

*Last updated: <YYYY-MM-DD> — see [History](#history) for the full changelog.*

> History and evidence live in architecture_archive.md.

One row per **current** decision. Superseded decisions, rationale and evidence
move to the archive — the live doc is authoritative for how the system is built
today.

## Overview
<What the system does, at the level of `vision.md`'s Problem section.>

## Goals and Non-Goals
- **Goal:** <a goal of the architecture as built>.
- **Non-goal:** <echo `vision.md`'s non-goals; never contradict them>.

## Key Components
| Component | Responsibility | Where it lives |
|---|---|---|
| <name> | <what it does> | <path> |

## Architecture Decisions
| Decision | The rule as it stands now | Where it lives |
|---|---|---|
| <decision> | <what is true now> | <path or design link> |

## Constraints
- <constraint: hardware, dependency, compatibility>.

## History
- <YYYY-MM-DD> — one-sentence summary of what changed.
"""

PRODUCT_ROADMAP_TEMPLATE = """\
# Product Roadmap

*Last updated: <YYYY-MM-DD> — see [History](#history) for the full changelog.*

> **Why this exists:** see [vision.md](vision.md). The vision lives in one
> place; the roadmap never duplicates it.

> History and evidence live in product_roadmap_archive.md.

Current state and the queue only. Completed designs and history roll to the
archive in the same commit that writes them.

## Current State
- <what works now>.
- <what does not work yet>.

## Design Inventory
| Design | Status | Link |
|---|---|---|
| <slug> | <Seeded / Designing / Implementing / Done — PR #NN / Parked> | [design](tp-designs/<slug>/design.md) |

## Implementation Sequence
1. <what to build next, ordered by impact against the vision> — <dependency>.

## Methodology
- <how work gets built here: the pipeline / spike flow this repo uses>.

## History
- <YYYY-MM-DD> — one-sentence summary of what changed.
"""

KNOWN_ISSUES_TEMPLATE = """\
# Known Issues

*Last updated: <YYYY-MM-DD> — see [History](#history) for the full changelog.*

> History and evidence live in known_issues_resolved.md.

Open issues only — **High and Medium**, one short entry each. Long evidence goes
to the archive; resolved issues move to `known_issues_resolved.md`; Lows live in
the cold file named on the pointer line below.

## High
### H<nn> — <one-line symptom>
- **Trigger:** <how it reproduces>.
- **Fix pointer:** <design / PR / path where the fix lands>.

## Medium
### M<nn> — <one-line symptom>
- **Trigger:** <how it reproduces>.
- **Fix pointer:** <design / PR / path where the fix lands>.

0 Low issues → `known_issues_low.md` (one line each; promote a Low to Medium by
moving its entry back into this doc in the same commit).

## History
- <YYYY-MM-DD> — one-sentence summary of what changed.
"""

TEMPLATES: dict[str, str] = {
    "vision": VISION_TEMPLATE,
    "architecture": ARCHITECTURE_TEMPLATE,
    "product_roadmap": PRODUCT_ROADMAP_TEMPLATE,
    "known_issues": KNOWN_ISSUES_TEMPLATE,
}


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


def _write_new(path: Path, text: str) -> bool:
    """Write *text* to *path* only when the file is absent. Never overwrites
    operator work. Returns True when the file was written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def scaffold(root, doc: str) -> list[str]:
    """Write the condensed template for *doc* plus its cold archive sibling.

    Args:
        root: repo root directory.
        doc: one of `DOC_NAMES`.

    Returns:
        The repo-relative paths written, in live-doc order (cold extras last).
        Empty when every target already existed — the call is idempotent and
        never overwrites an existing doc or archive.

    Raises:
        ValueError: *doc* is not one of `DOC_NAMES`.
        KeyError: *doc* has no archive pair in `living_doc_archive`.
    """
    if doc not in DOC_PATHS:
        raise ValueError(
            f"unknown doc {doc!r}; expected one of {', '.join(DOC_NAMES)}"
        )
    root = Path(root)
    live_rel = DOC_PATHS[doc]
    archive_rel = archive_for(live_rel)
    created: list[str] = []
    if _write_new(root / live_rel, TEMPLATES[doc]):
        created.append(live_rel)
    if _write_new(root / archive_rel, ARCHIVE_HEADER[archive_rel]):
        created.append(archive_rel)
    if doc == "known_issues" and _write_new(root / LOW_DOC_REL, LOW_DOC_CONTENT):
        created.append(LOW_DOC_REL)
    return created


def scaffold_all(root) -> list[str]:
    """Scaffold every living doc. The rel paths written across all docs."""
    created: list[str] = []
    for doc in DOC_NAMES:
        created.extend(scaffold(root, doc))
    return created


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write the condensed living-doc templates (idempotent).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc", choices=DOC_NAMES, metavar="NAME",
                       help="scaffold one doc: " + " | ".join(DOC_NAMES))
    group.add_argument("--all", action="store_true",
                       help="scaffold every living doc")
    parser.add_argument("--repo-root", default=None, metavar="R",
                        help="repo root (default: the enclosing git repo)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. argv excludes the program name.

    Exit codes: 0 — created or already present (both no-op outcomes);
    2 — usage error (no `--doc`/`--all`, or an unknown doc name).
    """
    args = _build_parser().parse_args(argv)
    root = Path(args.repo_root) if args.repo_root else find_project_root()
    if root is None:
        print("no repo root resolved — nothing scaffolded", file=sys.stderr)
        return 0
    docs = DOC_NAMES if args.all else (args.doc,)
    created = scaffold_all(root) if args.all else scaffold(root, args.doc)
    for rel in created:
        print(f"created {rel}")
    if not created:
        rels = ", ".join(DOC_PATHS[d] for d in docs)
        print(f"{rels} already exists — left unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
