"""Tests for living_doc_archive.py — the archive map + read-with-archive helper.

Hermetic: builds a tiny tmp tree (no real three-pillars-docs/ needed for the
read_with_archive behavior tests); the archive-map pairs are checked directly
against the real, pinned repo-relative paths.

Run with: python -m pytest skills/_shared/test_living_doc_archive.py -q
"""

from pathlib import Path

import pytest

from living_doc_archive import ARCHIVE_HEADER, ARCHIVES, archive_for, read_with_archive


# --------------------------------------------------------------------------- #
# archive_for — the pinned map
# --------------------------------------------------------------------------- #


def test_architecture_pair():
    assert archive_for("three-pillars-docs/architecture.md") == "three-pillars-docs/architecture_archive.md"


def test_known_issues_pair():
    assert archive_for("three-pillars-docs/known_issues.md") == "three-pillars-docs/known_issues_resolved.md"


def test_product_roadmap_pair():
    assert archive_for("three-pillars-docs/product_roadmap.md") == "three-pillars-docs/product_roadmap_archive.md"


def test_vision_pair():
    assert archive_for("three-pillars-docs/vision.md") == "three-pillars-docs/vision_archive.md"


def test_archives_dict_has_exactly_four_pairs():
    assert ARCHIVES == {
        "three-pillars-docs/architecture.md": "three-pillars-docs/architecture_archive.md",
        "three-pillars-docs/known_issues.md": "three-pillars-docs/known_issues_resolved.md",
        "three-pillars-docs/product_roadmap.md": "three-pillars-docs/product_roadmap_archive.md",
        "three-pillars-docs/vision.md": "three-pillars-docs/vision_archive.md",
    }


def test_archive_for_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        archive_for("three-pillars-docs/not_a_living_doc.md")


# --------------------------------------------------------------------------- #
# read_with_archive
# --------------------------------------------------------------------------- #


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_read_with_archive_present_joins_live_then_archive(tmp_path):
    _write(tmp_path, "three-pillars-docs/architecture.md", "live text\n")
    _write(tmp_path, "three-pillars-docs/architecture_archive.md", "archive text\n")
    result = read_with_archive(tmp_path, "three-pillars-docs/architecture.md")
    assert result == "live text\n" + "\n" + "archive text\n"


def test_read_with_archive_absent_returns_live_alone(tmp_path):
    _write(tmp_path, "three-pillars-docs/architecture.md", "live only text\n")
    result = read_with_archive(tmp_path, "three-pillars-docs/architecture.md")
    assert result == "live only text\n"


def test_read_with_archive_unknown_doc_raises_keyerror(tmp_path):
    _write(tmp_path, "three-pillars-docs/not_a_living_doc.md", "other text\n")
    with pytest.raises(KeyError):
        read_with_archive(tmp_path, "three-pillars-docs/not_a_living_doc.md")


def test_read_with_archive_joins_the_vision_pair(tmp_path):
    _write(tmp_path, "three-pillars-docs/vision.md", "vision text\n")
    _write(tmp_path, "three-pillars-docs/vision_archive.md", "old vision\n")
    assert read_with_archive(tmp_path, "three-pillars-docs/vision.md") == "vision text\n\nold vision\n"


# --------------------------------------------------------------------------- #
# ARCHIVE_HEADER
# --------------------------------------------------------------------------- #


def test_archive_header_has_entry_for_each_archive():
    for archive_rel in ARCHIVES.values():
        assert archive_rel in ARCHIVE_HEADER


def test_vision_archive_header_entry():
    header = ARCHIVE_HEADER["three-pillars-docs/vision_archive.md"]
    assert header.startswith("# Vision")
    assert "vision.md" in header and "moved verbatim" in header


def test_archive_header_shape():
    header = ARCHIVE_HEADER["three-pillars-docs/product_roadmap_archive.md"]
    lines = header.splitlines()
    assert lines[0].startswith("# ")
    assert lines[1] == ""
    assert lines[2].startswith(">")
    assert "moved verbatim" in lines[2]
