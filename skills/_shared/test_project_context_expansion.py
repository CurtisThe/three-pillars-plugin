"""test_project_context_expansion.py — PR #106 expansion behaviors.

Split from test_project_context.py (which sits at the 500-line hard cap) per the
file-size split-by-responsibility rule. Covers the three deferred expansions the
operator green-lit 2026-07-02:

  1. Scaffold-by-default (OQ3): scaffold_stub writes a valid stub when absent and
     is idempotent (never overwrites operator work).
  2. All-spawner injection (OQ1): the three remaining spawner docs reference
     project_context.py + the {project_context_block} marker (doc-level, like
     behaviors 10/11).
  3. Fail-open preserved: adding scaffold/advisory did NOT invert the helper's
     fail-open resolution (behaviors 2, 9, 12 stay exactly as-is).
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HARD_CAP = 12_288
SOFT_CAP = 10_240
REQUIRED_SECTIONS = ("## Conventions", "## Stack", "## Domain rules")


def _doc(root: Path) -> Path:
    return root / "three-pillars-docs" / "project-context.md"


# ---------------------------------------------------------------------------
# 1. Scaffold-by-default (OQ3)
# ---------------------------------------------------------------------------


class TestScaffoldWhenAbsent:
    """scaffold_stub writes a schema-valid stub when the doc is absent."""

    def test_creates_stub_when_absent(self, tmp_path):
        from project_context import scaffold_stub

        assert scaffold_stub(tmp_path) is True
        assert _doc(tmp_path).is_file()

    def test_stub_has_fixed_schema(self, tmp_path):
        from project_context import scaffold_stub

        scaffold_stub(tmp_path)
        content = _doc(tmp_path).read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            assert section in content, f"stub missing {section!r}"

    def test_stub_has_purpose_header(self, tmp_path):
        """One-line purpose header at the top, before the first section."""
        from project_context import scaffold_stub

        scaffold_stub(tmp_path)
        content = _doc(tmp_path).read_text(encoding="utf-8")
        first_line = content.splitlines()[0]
        assert first_line.strip() != ""
        assert not first_line.startswith("## "), "purpose header, not a section"
        assert content.index("injected") < content.index("## Conventions")

    def test_stub_loads_cleanly_via_helper(self, tmp_path):
        """Item 1: a freshly scaffolded stub loads cleanly (non-empty block)."""
        from project_context import load_context_block, scaffold_stub

        scaffold_stub(tmp_path)
        block = load_context_block(tmp_path)
        assert block != ""
        assert block.startswith("## Project context (injected — do not re-derive)")

    def test_stub_well_under_injected_cap(self, tmp_path):
        from project_context import measure, scaffold_stub

        scaffold_stub(tmp_path)
        n = measure(_doc(tmp_path))
        assert n < HARD_CAP, f"stub is {n} bytes, must be under {HARD_CAP}"
        assert n < SOFT_CAP, f"stub is {n} bytes, should be well under soft cap"


class TestScaffoldIdempotent:
    """scaffold_stub never overwrites operator work — idempotent no-op."""

    def test_second_call_is_noop_returns_false(self, tmp_path):
        from project_context import scaffold_stub

        assert scaffold_stub(tmp_path) is True
        assert scaffold_stub(tmp_path) is False

    def test_does_not_overwrite_existing_content(self, tmp_path):
        """An operator-authored doc is left byte-for-byte untouched."""
        from project_context import scaffold_stub

        doc = _doc(tmp_path)
        doc.parent.mkdir(parents=True, exist_ok=True)
        operator_text = "# My hand-written context\n\n## Conventions\nreal rules\n"
        doc.write_text(operator_text, encoding="utf-8")

        assert scaffold_stub(tmp_path) is False
        assert doc.read_text(encoding="utf-8") == operator_text

    def test_no_repo_root_is_noop(self, monkeypatch):
        """None root (not a git repo) is a no-op returning False — never raises."""
        import project_context

        monkeypatch.setattr(project_context, "find_project_root", lambda: None)
        assert project_context.scaffold_stub() is False


class TestScaffoldCli:
    """`project_context.py scaffold` — exit 0, created then idempotent."""

    def test_scaffold_creates_then_idempotent(self, tmp_path, capsys, monkeypatch):
        import project_context

        monkeypatch.setattr(project_context, "find_project_root", lambda: tmp_path)
        assert project_context.main(["scaffold"]) == 0
        out1 = capsys.readouterr().out
        assert "created" in out1

        assert project_context.main(["scaffold"]) == 0
        out2 = capsys.readouterr().out
        assert "already exists" in out2

    def test_scaffold_no_repo_exits_0(self, capsys, monkeypatch):
        import project_context

        monkeypatch.setattr(project_context, "find_project_root", lambda: None)
        assert project_context.main(["scaffold"]) == 0

    def test_docs_init_wires_scaffold_by_default(self):
        """OQ3 'scaffold by default': tp-docs-init step 5b must invoke
        `project_context.py scaffold`. This is the doc-presence guard for the
        scaffold surface, symmetric with the injection-surface marker guards in
        TestAllSpawnerInjection. Without it, dropping step 5b would silently
        stop by-default scaffolding while the scaffold_stub unit tests above
        stay green (the wiring, not just the function, is the contract)."""
        path = _repo_root().joinpath("skills", "tp-docs-init", "SKILL.md")
        assert path.is_file(), f"{path} must exist"
        content = path.read_text(encoding="utf-8")
        assert "project_context.py scaffold" in content, (
            "tp-docs-init/SKILL.md must wire the by-default scaffold "
            "invocation (`project_context.py scaffold`, step 5b)"
        )


# ---------------------------------------------------------------------------
# 2. All-spawner injection (OQ1) — doc-level, like behaviors 10/11
# ---------------------------------------------------------------------------

# Each remaining spawner surface must (a) carry the {project_context_block}
# marker and (b) reference the project_context.py helper that fills it.
#   - tp-run-full-design/SKILL.md  → compose() dispatch feeds the tp-worker slot
#     AND the tp-readonly-auditor audit slots.
#   - tp-pr-fix/SKILL.md           → step-5 fix-generation worker dispatch.
#   - agents/tp-readonly-auditor.md → provenance note on the injected context.
_SPAWNER_SURFACES = [
    ("skills", "tp-run-full-design", "SKILL.md"),
    ("skills", "tp-pr-fix", "SKILL.md"),
    ("agents", "tp-readonly-auditor.md"),
]


def _repo_root():
    from project_root import find_project_root

    root = find_project_root()
    assert root is not None, "Must be run from inside the repo"
    return root


class TestAllSpawnerInjection:
    """OQ1: the three remaining spawner docs reference the helper + marker."""

    def _read(self, parts):
        path = _repo_root().joinpath(*parts)
        assert path.is_file(), f"{path} must exist"
        return path.read_text(encoding="utf-8")

    def test_run_full_design_has_marker_and_helper(self):
        content = self._read(("skills", "tp-run-full-design", "SKILL.md"))
        assert "{project_context_block}" in content
        assert "project_context.py" in content

    def test_run_full_design_names_both_slots(self):
        """compose() injection must document it flows to BOTH the worker
        (tp-worker) and audit (tp-readonly-auditor) slots — the two named
        spawners that share the compose() dispatch prompt."""
        content = self._read(("skills", "tp-run-full-design", "SKILL.md"))
        idx = content.index("{project_context_block}")
        window = content[idx : idx + 900]
        assert "tp-worker" in window
        assert "tp-readonly-auditor" in window

    def test_pr_fix_has_marker_and_helper(self):
        content = self._read(("skills", "tp-pr-fix", "SKILL.md"))
        assert "{project_context_block}" in content
        assert "project_context.py" in content

    def test_readonly_auditor_has_marker_and_helper(self):
        content = self._read(("agents", "tp-readonly-auditor.md"))
        assert "{project_context_block}" in content
        assert "project_context.py" in content

    def test_every_surface_omits_when_empty(self):
        """Byte-for-byte preservation: each injection documents the OMIT-when-
        empty rule so an absent doc reproduces today's behavior."""
        for parts in _SPAWNER_SURFACES:
            content = self._read(parts)
            lowered = content.lower()
            assert "omit" in lowered or "empty" in lowered, (
                f"{parts[-1]} must document the omit-when-empty rule"
            )


# ---------------------------------------------------------------------------
# 3. Fail-open preserved — behaviors 2, 9, 12 stay exactly as-is
# ---------------------------------------------------------------------------


class TestFailOpenPreserved:
    """Regression guard: the scaffold/advisory expansions must NOT invert the
    helper's fail-open resolution. `load_context_block` still returns "" for an
    absent doc (behavior 2) and a None root (behavior 9); the empty block still
    substitutes to nothing (behavior 12). This is the load-bearing invariant the
    'required' semantics must NEVER break — required is advisory-only."""

    def test_absent_doc_still_returns_empty(self, tmp_path):
        from project_context import load_context_block

        assert load_context_block(tmp_path) == ""  # behavior 2

    def test_none_root_still_returns_empty(self, monkeypatch):
        import project_context

        monkeypatch.setattr(project_context, "find_project_root", lambda: None)
        assert project_context.load_context_block() == ""  # behavior 9

    def test_empty_block_substitutes_to_nothing(self, tmp_path):
        from project_context import load_context_block

        block = load_context_block(tmp_path)
        template = "prefix\n{project_context_block}\nsuffix"
        assert template.replace("{project_context_block}", block) == "prefix\n\nsuffix"
