"""living_doc_archive.py — the living-doc → archive map + read-with-archive helper.

Four living docs each roll their oldest / superseded content into a sibling
archive file so the live doc stays one-Read-pass small (see `vision.md`, `architecture.md`,
`known_issues.md`, `product_roadmap.md` and their archive siblings). This module
is the single source of truth for that pairing:

  - `ARCHIVES` — the repo-relative (POSIX) live -> archive map.
  - `archive_for(rel)` — look up a live doc's archive path; `KeyError` if `rel`
    is not a living doc this module knows about.
  - `read_with_archive(repo_root, rel)` — read the live doc, followed by its
    archive (if present) so callers see the full history without needing to
    know the archive exists.
  - `ARCHIVE_HEADER` — the header text to seed a brand-new archive file on its
    first rollover, modelled on `product_roadmap_archive.md` lines 1-5.

Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

ARCHIVES: dict[str, str] = {
    "three-pillars-docs/architecture.md": "three-pillars-docs/architecture_archive.md",
    "three-pillars-docs/known_issues.md": "three-pillars-docs/known_issues_resolved.md",
    "three-pillars-docs/product_roadmap.md": "three-pillars-docs/product_roadmap_archive.md",
    "three-pillars-docs/vision.md": "three-pillars-docs/vision_archive.md",
}

ARCHIVE_HEADER: dict[str, str] = {
    "three-pillars-docs/architecture_archive.md": (
        "# Architecture — Archive\n"
        "\n"
        "> Historical content moved verbatim out of [`architecture.md`](architecture.md) to keep "
        "the live architecture doc readable. The live doc is authoritative for how the system is "
        "built today; nothing here is current.\n"
    ),
    "three-pillars-docs/known_issues_resolved.md": (
        "# Known Issues — RESOLVED archive\n"
        "\n"
        "> Resolved issues moved verbatim out of [`known_issues.md`](known_issues.md) so the live "
        "file stays one-Read-pass small. Entries arrive here verbatim when resolved.\n"
    ),
    "three-pillars-docs/product_roadmap_archive.md": (
        "# Product Roadmap — Archive\n"
        "\n"
        "> Historical content moved verbatim out of [`product_roadmap.md`](product_roadmap.md) to "
        "keep the live roadmap readable. The live roadmap is authoritative for what to build next; "
        "nothing here is current.\n"
    ),
    "three-pillars-docs/vision_archive.md": (
        "# Vision — Archive\n"
        "\n"
        "> Historical content moved verbatim out of [`vision.md`](vision.md) to keep the live "
        "vision readable. The live vision is authoritative for why the project exists; nothing "
        "here is current.\n"
    ),
}


def archive_for(rel: str) -> str:
    """Return the archive rel-path for a living doc's rel-path. `KeyError` if
    `rel` is not one of the three docs this module archives."""
    return ARCHIVES[rel]


def read_with_archive(repo_root, rel: str) -> str:
    """Read the live doc's text, followed by its archive's text (if the archive
    file exists). Returns the live text alone when the archive is absent.
    `KeyError` if `rel` is not a known living doc."""
    archive_rel = archive_for(rel)  # raises KeyError for unknown docs
    root = Path(repo_root)
    live_text = (root / rel).read_text(encoding="utf-8")
    archive_path = root / archive_rel
    if archive_path.is_file():
        return live_text + "\n" + archive_path.read_text(encoding="utf-8")
    return live_text
