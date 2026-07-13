"""test_project_context.py — Covers all 12 behaviors from design.md.

Phase 1 (tasks 1.1, 1.2): Behaviors 1–9, 12 (helper core + CLI).
Phase 2 (task 2.1):        Behavior 2.1 (shipped living doc).
Phase 3 (tasks 3.1–3.3):  Behaviors 10, 11, read-project-docs cross-link.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HARD_CAP = 12_288
SOFT_CAP = 10_240


def _make_doc(tmp_path: Path, content_bytes: bytes) -> Path:
    """Write content_bytes to a project-context.md inside a mock project root."""
    doc_dir = tmp_path / "three-pillars-docs"
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / "project-context.md"
    doc_path.write_bytes(content_bytes)
    return tmp_path  # return the root


def _ascii_root(tmp_path: Path, n: int) -> Path:
    """Root with an n-byte (ASCII) project-context.md."""
    return _make_doc(tmp_path, b"x" * n)


# ---------------------------------------------------------------------------
# Phase 1 — behaviors 1–9, 12
# ---------------------------------------------------------------------------


class TestLoadWhenPresent:
    """Behavior 1: load_context_block reads and returns the file body."""

    def test_block_contains_body(self, tmp_path):
        from project_context import load_context_block

        body = "# My project context\nConventions: use stdlib.\n"
        root = _make_doc(tmp_path, body.encode("utf-8"))
        block = load_context_block(root)
        assert body.strip() in block or body in block


class TestAbsentDoc:
    """Behavior 2 + 12: absent doc returns empty string."""

    def test_returns_empty_string(self, tmp_path):
        from project_context import load_context_block

        # No three-pillars-docs/project-context.md in tmp_path
        block = load_context_block(tmp_path)
        assert block == ""

    def test_template_substitution_yields_nothing(self, tmp_path):
        """Behavior 12: empty block → template {project_context_block} becomes ''."""
        from project_context import load_context_block

        block = load_context_block(tmp_path)
        template = "Some prefix\n{project_context_block}\nSome suffix"
        result = template.replace("{project_context_block}", block)
        assert result == "Some prefix\n\nSome suffix"


class TestUnderCapBoundary:
    """Behavior 3: doc at exactly HARD_CAP bytes → returns block, no raise."""

    def test_at_exact_cap_returns_block(self, tmp_path):
        from project_context import load_context_block

        root = _ascii_root(tmp_path, HARD_CAP)
        block = load_context_block(root)
        assert isinstance(block, str)
        assert block != ""


class TestOverCapInProcess:
    """Behavior 4: doc at HARD_CAP+1 → raises ProjectContextTooLarge."""

    def test_raises_with_bytes_and_cap(self, tmp_path):
        from project_context import ProjectContextTooLarge, load_context_block

        root = _ascii_root(tmp_path, HARD_CAP + 1)
        with pytest.raises(ProjectContextTooLarge) as exc_info:
            load_context_block(root)
        exc = exc_info.value
        assert exc.bytes == HARD_CAP + 1
        assert exc.cap == HARD_CAP


class TestBlockFormat:
    """Behavior 7: block begins with the header and ends with blank line."""

    def test_header_present(self, tmp_path):
        from project_context import load_context_block

        root = _make_doc(tmp_path, b"Some content here.")
        block = load_context_block(root)
        assert block.startswith("## Project context (injected — do not re-derive)")

    def test_ends_with_blank_line(self, tmp_path):
        from project_context import load_context_block

        root = _make_doc(tmp_path, b"Some content here.")
        block = load_context_block(root)
        assert block.endswith("\n\n"), f"Block did not end with \\n\\n: {block!r}"


class TestUtf8ByteMeasurement:
    """Behavior 8: cap measured on UTF-8 bytes, not character count."""

    def test_multibyte_over_cap_raises(self, tmp_path):
        """A doc whose char count is under HARD_CAP but byte count is over raises."""
        from project_context import ProjectContextTooLarge, load_context_block

        # U+00E9 (é) encodes to 2 bytes in UTF-8
        # We need char_count < HARD_CAP but byte_count > HARD_CAP
        # Use HARD_CAP//2 + 1 chars of 2-byte char → byte_count = HARD_CAP + 2
        char_count = HARD_CAP // 2 + 1  # 6145 chars
        content = ("é" * char_count).encode("utf-8")  # 12290 bytes > 12288
        assert len("é" * char_count) < HARD_CAP  # char count is under cap
        assert len(content) > HARD_CAP  # byte count is over cap

        root = _make_doc(tmp_path, content)
        with pytest.raises(ProjectContextTooLarge):
            load_context_block(root)


class TestRootResolution:
    """Behavior 9: load_context_block() with no arg resolves via find_project_root."""

    def test_none_root_returns_empty(self, monkeypatch):
        """Monkeypatch project_context.find_project_root to return None → ''."""
        import project_context

        monkeypatch.setattr(project_context, "find_project_root", lambda: None)
        block = project_context.load_context_block()
        assert block == ""


class TestPathologicalDoc:
    """Hardening (impl-audit adversarial): a present-but-pathological doc must
    fail open to "" — never crash an advisory dispatch, never orphan a header."""

    def test_invalid_utf8_fails_open(self, tmp_path):
        """A non-UTF-8 (under-cap) doc returns "" rather than raising."""
        from project_context import load_context_block

        root = _make_doc(tmp_path, b"caf\xe9 latin1 not utf-8\n")  # 0xe9 invalid
        assert load_context_block(root) == ""

    def test_empty_doc_injects_nothing(self, tmp_path):
        """A present-but-empty (0-byte) doc returns "" — no orphaned header."""
        from project_context import load_context_block

        root = _make_doc(tmp_path, b"")
        assert load_context_block(root) == ""

    def test_whitespace_only_doc_injects_nothing(self, tmp_path):
        """A whitespace-only doc returns "" (no header over an empty body)."""
        from project_context import load_context_block

        root = _make_doc(tmp_path, b"   \n\t\n")
        assert load_context_block(root) == ""

    def test_unreadable_doc_fails_open(self, tmp_path):
        """An unreadable (perm 000) doc returns "" rather than raising.

        Skipped when the process can read regardless of mode (e.g. running as
        root in some CI), since chmod 000 would not actually restrict it."""
        from project_context import load_context_block

        root = _make_doc(tmp_path, b"# ctx\nreadable content\n")
        doc = root / "three-pillars-docs" / "project-context.md"
        doc.chmod(0o000)
        try:
            try:
                doc.read_bytes()
                pytest.skip("file readable despite chmod 000 (likely root)")
            except OSError:
                pass
            assert load_context_block(root) == ""
        finally:
            doc.chmod(0o644)


class TestMeasureFunction:
    """measure() returns UTF-8 byte count."""

    def test_ascii_bytes_count(self, tmp_path):
        from project_context import measure

        path = tmp_path / "test.md"
        path.write_bytes(b"hello")
        assert measure(path) == 5

    def test_multibyte_char_count(self, tmp_path):
        from project_context import measure

        path = tmp_path / "test.md"
        content = "é" * 10  # each é = 2 bytes
        path.write_bytes(content.encode("utf-8"))
        assert measure(path) == 20


# ---------------------------------------------------------------------------
# Phase 1, Task 1.2 — behaviors 5, 6 (CLI check subcommand)
# ---------------------------------------------------------------------------


class TestCliOverCap:
    """Behavior 5: CLI over-cap → exit 1 + BLOCKED-JSON on stderr."""

    def test_over_cap_exits_1_with_blocked_json(self, tmp_path, capsys, monkeypatch):
        import project_context

        root = _ascii_root(tmp_path, HARD_CAP + 1)
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        exit_code = project_context.main(["check"])
        captured = capsys.readouterr()
        assert exit_code == 1
        verdict = json.loads(captured.err)
        assert verdict["verdict"] == "BLOCKED"
        assert verdict["schema_version"] == 1
        assert verdict["bytes"] == HARD_CAP + 1
        assert verdict["cap"] == HARD_CAP

    def test_absent_doc_exits_0(self, tmp_path, capsys, monkeypatch):
        import project_context

        # No doc in tmp_path
        monkeypatch.setattr(project_context, "find_project_root", lambda: tmp_path)
        exit_code = project_context.main(["check"])
        assert exit_code == 0

    def test_under_cap_exits_0(self, tmp_path, capsys, monkeypatch):
        import project_context

        root = _ascii_root(tmp_path, SOFT_CAP)
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        exit_code = project_context.main(["check"])
        assert exit_code == 0

    def test_unreadable_doc_exits_0(self, tmp_path, capsys, monkeypatch):
        """A present-but-unreadable doc fails open to exit 0 (advisory) rather
        than crashing main with an uncaught OSError — symmetric with
        load_context_block's OSError handling.

        Skipped when the process can read regardless of mode (e.g. running as
        root in some CI), since chmod 000 would not actually restrict it."""
        import project_context

        root = _make_doc(tmp_path, b"# ctx\nreadable content\n")
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        doc = root / "three-pillars-docs" / "project-context.md"
        doc.chmod(0o000)
        try:
            try:
                doc.read_bytes()
                pytest.skip("file readable despite chmod 000 (likely root)")
            except OSError:
                pass
            exit_code = project_context.main(["check"])
            assert exit_code == 0
        finally:
            doc.chmod(0o644)


class TestCliUsageAndResolution:
    """Pin main()'s non-doc branches: usage error (exit 2) + no-repo (exit 0).

    The exit-2 usage contract is documented in main()'s docstring; without
    these tests the guard could regress (wrong code, wrong stream) silently."""

    def test_missing_subcommand_exits_2(self, capsys):
        import project_context

        exit_code = project_context.main([])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "usage" in captured.err.lower()

    def test_unknown_subcommand_exits_2(self, capsys):
        import project_context

        exit_code = project_context.main(["bogus"])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "usage" in captured.err.lower()

    def test_no_repo_exits_0(self, capsys, monkeypatch):
        import project_context

        monkeypatch.setattr(project_context, "find_project_root", lambda: None)
        exit_code = project_context.main(["check"])
        assert exit_code == 0


class TestCliBandBoundaries:
    """Behavior 6 + boundary precision for bands."""

    def test_exactly_soft_cap_is_clean(self, tmp_path, capsys, monkeypatch):
        """n == SOFT_CAP (10240) → clean, exit 0, no warning."""
        import project_context

        root = _ascii_root(tmp_path, SOFT_CAP)
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        exit_code = project_context.main(["check"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "warning" not in captured.err.lower()

    def test_soft_cap_plus_one_warns(self, tmp_path, capsys, monkeypatch):
        """n == SOFT_CAP+1 (10241) → warn on stderr, exit 0."""
        import project_context

        root = _ascii_root(tmp_path, SOFT_CAP + 1)
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        exit_code = project_context.main(["check"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "warning" in captured.err.lower()

    def test_exactly_hard_cap_warns_not_blocked(self, tmp_path, capsys, monkeypatch):
        """n == HARD_CAP (12288) → warn, exit 0 (still in warn band)."""
        import project_context

        root = _ascii_root(tmp_path, HARD_CAP)
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        exit_code = project_context.main(["check"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "warning" in captured.err.lower()

    def test_hard_cap_plus_one_is_blocked(self, tmp_path, capsys, monkeypatch):
        """n == HARD_CAP+1 (12289) → BLOCKED, exit 1."""
        import project_context

        root = _ascii_root(tmp_path, HARD_CAP + 1)
        monkeypatch.setattr(project_context, "find_project_root", lambda: root)
        exit_code = project_context.main(["check"])
        captured = capsys.readouterr()
        assert exit_code == 1
        verdict = json.loads(captured.err)
        assert verdict["verdict"] == "BLOCKED"


class TestSoftWarnBlockReturnsBlock:
    """Behavior 6: soft-warn band still returns the block (not raises)."""

    def test_soft_band_load_context_block_returns_block(self, tmp_path):
        from project_context import load_context_block

        # 11 KB is in the soft-warn band
        root = _ascii_root(tmp_path, 11_000)
        block = load_context_block(root)
        assert block != ""
        assert isinstance(block, str)


# ---------------------------------------------------------------------------
# Phase 2, Task 2.1 — shipped living doc (behavior 2.1)
# ---------------------------------------------------------------------------


class TestShippedLivingDoc:
    """Behavior 2.1: three-pillars-docs/project-context.md loads cleanly."""

    def test_shipped_doc_loads_via_helper(self):
        from project_context import load_context_block, measure
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None, "Must be run from inside the repo"
        doc_path = root / "three-pillars-docs" / "project-context.md"
        assert doc_path.is_file(), "three-pillars-docs/project-context.md must exist"

        block = load_context_block(root)
        assert block != "", "Block should be non-empty for a present doc"

    def test_shipped_doc_has_required_sections(self):
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        doc_path = root / "three-pillars-docs" / "project-context.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "## Conventions" in content
        assert "## Stack" in content
        assert "## Domain rules" in content

    def test_shipped_doc_under_soft_cap(self):
        from project_context import measure
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        doc_path = root / "three-pillars-docs" / "project-context.md"
        byte_count = measure(doc_path)
        assert byte_count <= SOFT_CAP, (
            f"project-context.md is {byte_count} bytes, exceeds soft cap {SOFT_CAP}"
        )
        assert byte_count <= HARD_CAP


# ---------------------------------------------------------------------------
# Phase 3, Task 3.1 — council SKILL.md injection (behavior 10)
# ---------------------------------------------------------------------------


class TestCouncilInjection:
    """Behavior 10: council/SKILL.md contains the injection marker."""

    def test_council_skill_md_has_marker(self):
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        skill_path = root / "skills" / "council" / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        assert "{project_context_block}" in content, (
            "council/SKILL.md missing {project_context_block} marker"
        )

    def test_council_skill_md_references_helper(self):
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        skill_path = root / "skills" / "council" / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        assert "project_context.py" in content, (
            "council/SKILL.md missing reference to project_context.py"
        )


# ---------------------------------------------------------------------------
# Phase 3, Task 3.2 — tp-phase-implement SKILL.md injection (behavior 11)
# ---------------------------------------------------------------------------


class TestPhaseImplementInjection:
    """Behavior 11: tp-phase-implement/SKILL.md contains the injection marker."""

    def test_phase_implement_skill_md_has_marker(self):
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        skill_path = root / "skills" / "tp-phase-implement" / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        assert "{project_context_block}" in content, (
            "tp-phase-implement/SKILL.md missing {project_context_block} marker"
        )

    def test_phase_implement_skill_md_references_helper(self):
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        skill_path = root / "skills" / "tp-phase-implement" / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        assert "project_context.py" in content, (
            "tp-phase-implement/SKILL.md missing reference to project_context.py"
        )


# ---------------------------------------------------------------------------
# Phase 3, Task 3.3 — read-project-docs.md cross-link
# ---------------------------------------------------------------------------


class TestReadProjectDocsCrossLink:
    """Cross-link: read-project-docs.md references project-context.md."""

    def test_read_project_docs_references_context_doc(self):
        from project_root import find_project_root

        root = find_project_root()
        assert root is not None
        docs_path = root / "skills" / "_shared" / "read-project-docs.md"
        content = docs_path.read_text(encoding="utf-8")
        assert "project-context.md" in content, (
            "read-project-docs.md missing reference to project-context.md"
        )
