"""Tests for skills/tp-spec — /tp-spec skill subcommands.

Covers Phase 3 of the living-spec-layer plan:
  3.1 Template parses as a valid delta after placeholder substitution
  3.2 `add` scaffolds spec-delta.md; refuses to clobber existing
  3.3 `validate` calls real validate_artifact API then drift scan
  3.4 `merge` writes base via spec_delta.merge; refuses on conflict
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure _shared is importable
_SKILL_DIR = Path(__file__).resolve().parent
_SHARED = _SKILL_DIR.parent / "_shared"
sys.path.insert(0, str(_SHARED))
sys.path.insert(0, str(_SKILL_DIR))

import spec_delta  # noqa: E402
from spec_delta import parse_delta, MergeConflict, SpecParseError  # noqa: E402

# ---------------------------------------------------------------------------
# Task 3.1 — template parses as a valid delta
# ---------------------------------------------------------------------------

class TestTemplateParsesAsDelta:
    """Task 3.1: the scaffold template must be a structurally valid delta skeleton."""

    _TEMPLATE = _SKILL_DIR / "templates" / "spec-delta.template.md"

    def test_template_parses_as_delta(self):
        """Read template, substitute placeholder, assert parse_delta succeeds + yields ADDED op."""
        text = self._TEMPLATE.read_text(encoding="utf-8")
        filled = text.replace("{{REQUIREMENT_NAME}}", "My Test Requirement")
        delta = parse_delta(filled)
        assert delta.ops, "template must yield at least one operation"
        kinds = [op.kind for op in delta.ops]
        assert "ADDED" in kinds, f"template must yield an ADDED op; got {kinds}"


# ---------------------------------------------------------------------------
# Task 3.2 — `add` scaffolds and refuses clobber
# ---------------------------------------------------------------------------

class TestAddScaffoldsAndRefusesClobber:
    """Task 3.2: tp_spec add <design> scaffolds spec-delta.md; refuses clobber."""

    def _designs_root(self, tmp_path: Path) -> Path:
        d = tmp_path / "three-pillars-docs" / "tp-designs"
        d.mkdir(parents=True)
        return d

    def test_add_scaffolds_and_refuses_clobber(self, tmp_path):
        """add to absent design → file created from template; add again → untouched."""
        from tp_spec import cmd_add

        designs_root = self._designs_root(tmp_path)
        template = _SKILL_DIR / "templates" / "spec-delta.template.md"

        design_name = "my-design"
        design_dir = designs_root / design_name
        design_dir.mkdir()

        delta_path = design_dir / "spec-delta.md"
        assert not delta_path.exists()

        # First call: should create the file
        result = cmd_add(design_name, designs_root=designs_root, template_path=template)
        assert result == 0, "cmd_add should succeed on absent spec-delta.md"
        assert delta_path.exists(), "spec-delta.md should be created"
        content = delta_path.read_text(encoding="utf-8")
        assert "{{REQUIREMENT_NAME}}" in content, "created file should contain placeholder"

        # Second call: should refuse to clobber; content unchanged
        original_content = content
        delta_path.write_text("CUSTOM CONTENT — do not overwrite")
        result2 = cmd_add(design_name, designs_root=designs_root, template_path=template)
        assert result2 == 0, "cmd_add should no-op on existing spec-delta.md (exit 0)"
        assert delta_path.read_text(encoding="utf-8") == "CUSTOM CONTENT — do not overwrite", \
            "existing spec-delta.md must not be overwritten"

    def test_add_missing_design_dir(self, tmp_path):
        """add with a design that has no directory → non-zero exit."""
        from tp_spec import cmd_add

        designs_root = self._designs_root(tmp_path)
        template = _SKILL_DIR / "templates" / "spec-delta.template.md"

        result = cmd_add("nonexistent-design", designs_root=designs_root, template_path=template)
        assert result != 0, "cmd_add should fail when design directory does not exist"


# ---------------------------------------------------------------------------
# Task 3.3 — `validate` uses real validate_artifact API then drift scan
# ---------------------------------------------------------------------------

class TestValidateUsesRealApiThenDrift:
    """Task 3.3: validate calls validate_artifact('spec', Path(delta_path)) — real API."""

    def _make_valid_delta(self, path: Path) -> None:
        path.write_text(
            "## ADDED Requirements\n\n"
            "### Requirement: My Feature\n\n"
            "The system SHALL do the feature.\n\n"
            "> Code: skills/_shared/spec_delta.py\n\n"
            "#### Scenario: Happy path\n\n"
            "- **WHEN** triggered\n"
            "- **THEN** works\n"
        )

    def _make_invalid_delta(self, path: Path) -> None:
        """A structurally invalid delta: ADDED with no scenario."""
        path.write_text(
            "## ADDED Requirements\n\n"
            "### Requirement: Bad Feature\n\n"
            "The system SHALL do bad things (no scenario).\n"
        )

    def test_validate_uses_real_api_then_drift(self, tmp_path):
        """validate: BLOCKED on invalid delta; valid delta triggers drift scan."""
        from tp_spec import cmd_validate

        # Set up a minimal specs dir (drift scan needs it). The base spec must
        # carry at least one requirement whose anchor resolves, so the drift
        # scan is genuinely clean (an empty base now ERRORs as empty-domain).
        specs_dir = tmp_path / "specs"
        domain_dir = specs_dir / "pipeline"
        domain_dir.mkdir(parents=True)
        anchored_file = tmp_path / "anchored.py"
        anchored_file.write_text("# real implementing file\n")
        (domain_dir / "spec.md").write_text(
            "## Requirements\n\n"
            "### Requirement: Base Feature\n\n"
            "The system SHALL do the base feature.\n\n"
            "> Code: anchored.py\n\n"
            "#### Scenario: Base\n\n"
            "- **WHEN** base\n"
            "- **THEN** works\n"
        )

        # --- invalid delta → BLOCKED (non-zero exit) ---
        bad_delta = tmp_path / "bad-spec-delta.md"
        self._make_invalid_delta(bad_delta)
        result_bad = cmd_validate(
            delta_path=bad_delta,
            specs_dir=specs_dir,
            repo=tmp_path,
        )
        assert result_bad != 0, "invalid delta must yield non-zero exit"

        # --- valid delta → passes validation and drift scan (exit 0) ---
        good_delta = tmp_path / "good-spec-delta.md"
        self._make_valid_delta(good_delta)
        result_good = cmd_validate(
            delta_path=good_delta,
            specs_dir=specs_dir,
            repo=tmp_path,
        )
        assert result_good == 0, "valid delta against clean spec tree must exit 0"

    def test_validate_fails_on_real_drift(self, tmp_path, capsys):
        """A schema-valid delta against a base spec whose anchor does NOT
        resolve must drive cmd_validate to non-zero AND the failure must be
        DRIFT (not the schema-BLOCKED path). This kills a `return 0` mutant
        in the drift-scan call: the schema validation passes, so the only
        thing that can fail the command is the drift scan."""
        from tp_spec import cmd_validate

        # Base domain spec with a requirement whose > Code: anchor is dangling.
        specs_dir = tmp_path / "specs"
        domain_dir = specs_dir / "pipeline"
        domain_dir.mkdir(parents=True)
        (domain_dir / "spec.md").write_text(
            "## Requirements\n\n"
            "### Requirement: Dangling Base\n\n"
            "The system SHALL reference a file that does not exist.\n\n"
            "> Code: does/not/exist.py\n\n"
            "#### Scenario: Dangling\n\n"
            "- **WHEN** scanned\n"
            "- **THEN** drift is reported\n"
        )

        # A fully schema-valid delta (so validate_artifact returns non-BLOCKED).
        good_delta = tmp_path / "good-spec-delta.md"
        self._make_valid_delta(good_delta)

        result = cmd_validate(
            delta_path=good_delta,
            specs_dir=specs_dir,
            repo=tmp_path,
        )
        captured = capsys.readouterr()
        assert result != 0, "valid delta + dangling base anchor must fail validation"
        combined = captured.out + captured.err
        assert "DRIFT" in combined, (
            "failure must come from the drift scan (verdict DRIFT), not the "
            f"schema-BLOCKED path; output was: {combined!r}"
        )

    def test_validate_does_not_use_wrong_api(self, tmp_path):
        """Explicitly assert tp_spec does NOT reference validate_artifact.validate(text, 'spec')."""
        tp_spec_src = (_SKILL_DIR / "tp_spec.py").read_text(encoding="utf-8")
        # The nonexistent API would look like: validate_artifact.validate(... "spec")
        # or validate(delta_text, "spec")
        assert 'validate_artifact.validate(' not in tp_spec_src, \
            "tp_spec.py must not call nonexistent validate_artifact.validate(text, type) API"


# ---------------------------------------------------------------------------
# Task 3.4 — `merge` writes base and refuses conflict
# ---------------------------------------------------------------------------

class TestMergeWritesBaseAndRefusesConflict:
    """Task 3.4: merge calls spec_delta.merge; refuses on MergeConflict/SpecParseError."""

    def _make_base(self, path: Path) -> None:
        path.write_text(
            "### Requirement: Existing Feature\n\n"
            "The system SHALL do the existing feature.\n\n"
            "> Code: skills/_shared/spec_delta.py\n\n"
            "#### Scenario: Existing\n\n"
            "- **WHEN** existing\n"
            "- **THEN** works\n"
        )

    def _make_valid_delta(self, path: Path) -> None:
        path.write_text(
            "## ADDED Requirements\n\n"
            "### Requirement: New Feature\n\n"
            "The system SHALL do the new feature.\n\n"
            "> Code: skills/_shared/spec_delta.py\n\n"
            "#### Scenario: New\n\n"
            "- **WHEN** new\n"
            "- **THEN** works\n"
        )

    def _make_conflicting_delta(self, path: Path) -> None:
        """Delta trying to ADD a requirement that already exists in base → MergeConflict."""
        path.write_text(
            "## ADDED Requirements\n\n"
            "### Requirement: Existing Feature\n\n"
            "The system SHALL conflict.\n\n"
            "> Code: skills/_shared/spec_delta.py\n\n"
            "#### Scenario: Conflict\n\n"
            "- **WHEN** conflict\n"
            "- **THEN** fails\n"
        )

    def _make_unparseable_delta(self, path: Path) -> None:
        path.write_text("This is not a valid delta at all — no section headers.\n")

    def _setup_design(self, tmp_path: Path, domain: str = "pipeline") -> tuple:
        """Create specs/<domain>/spec.md + tp-designs/<design>/spec-delta.md structures."""
        specs_dir = tmp_path / "specs"
        domain_dir = specs_dir / domain
        domain_dir.mkdir(parents=True)
        base_path = domain_dir / "spec.md"

        designs_root = tmp_path / "three-pillars-docs" / "tp-designs"
        design_dir = designs_root / "my-design"
        design_dir.mkdir(parents=True)
        delta_path = design_dir / "spec-delta.md"

        return specs_dir, base_path, designs_root, delta_path

    def test_merge_writes_base_on_success(self, tmp_path):
        """merge <design>: valid delta → base is updated with merged content."""
        from tp_spec import cmd_merge

        specs_dir, base_path, designs_root, delta_path = self._setup_design(tmp_path)
        self._make_base(base_path)
        self._make_valid_delta(delta_path)

        result = cmd_merge(
            design_name="my-design",
            designs_root=designs_root,
            specs_dir=specs_dir,
            domain="pipeline",
        )
        assert result == 0, "merge with valid delta should exit 0"

        merged_text = base_path.read_text(encoding="utf-8")
        assert "New Feature" in merged_text, "merged base should contain the added requirement"
        assert "Existing Feature" in merged_text, "merged base should preserve existing requirements"

    def test_merge_refuses_on_conflict(self, tmp_path):
        """merge: conflicting delta → base NOT written, non-zero exit."""
        from tp_spec import cmd_merge

        specs_dir, base_path, designs_root, delta_path = self._setup_design(tmp_path)
        self._make_base(base_path)
        original_content = base_path.read_text(encoding="utf-8")
        self._make_conflicting_delta(delta_path)

        result = cmd_merge(
            design_name="my-design",
            designs_root=designs_root,
            specs_dir=specs_dir,
            domain="pipeline",
        )
        assert result != 0, "merge with conflicting delta must exit non-zero"
        assert base_path.read_text(encoding="utf-8") == original_content, \
            "base must not be modified on a refused merge"

    def test_merge_refuses_on_unparseable_delta(self, tmp_path):
        """merge: unparseable delta → base NOT written, non-zero exit."""
        from tp_spec import cmd_merge

        specs_dir, base_path, designs_root, delta_path = self._setup_design(tmp_path)
        self._make_base(base_path)
        original_content = base_path.read_text(encoding="utf-8")
        self._make_unparseable_delta(delta_path)

        result = cmd_merge(
            design_name="my-design",
            designs_root=designs_root,
            specs_dir=specs_dir,
            domain="pipeline",
        )
        assert result != 0, "merge with unparseable delta must exit non-zero"
        assert base_path.read_text(encoding="utf-8") == original_content, \
            "base must not be modified on parse failure"

    def test_merge_errors_when_base_absent(self, tmp_path):
        """merge: delta present but base spec.md absent → non-zero exit, no base written."""
        from tp_spec import cmd_merge

        specs_dir, base_path, designs_root, delta_path = self._setup_design(tmp_path)
        # Deliberately do NOT create the base spec.md.
        self._make_valid_delta(delta_path)
        assert not base_path.exists()

        result = cmd_merge(
            design_name="my-design",
            designs_root=designs_root,
            specs_dir=specs_dir,
            domain="pipeline",
        )
        assert result != 0, "merge must fail when the base spec is absent"
        assert not base_path.exists(), "no base file may be written when base was absent"

    def test_merge_skips_when_no_delta(self, tmp_path):
        """merge with no spec-delta.md → no-op skip, exit 0, base untouched."""
        from tp_spec import cmd_merge

        specs_dir, base_path, designs_root, delta_path = self._setup_design(tmp_path)
        self._make_base(base_path)
        original_content = base_path.read_text(encoding="utf-8")
        # delta_path NOT created

        result = cmd_merge(
            design_name="my-design",
            designs_root=designs_root,
            specs_dir=specs_dir,
            domain="pipeline",
        )
        assert result == 0, "merge with no spec-delta.md must exit 0 (skip)"
        assert base_path.read_text(encoding="utf-8") == original_content, \
            "base must be untouched when there is no delta to merge"


# ---------------------------------------------------------------------------
# Task 5.1 — tp-design-complete documents merge sub-step and stages base spec
# ---------------------------------------------------------------------------

class TestDesignCompleteDocumentsMergeAndStagesBase:
    """Task 5.1: tp-design-complete/SKILL.md must document:
    (a) a /tp-spec merge <design> sub-step ordered BEFORE the step-6c git mv
    (b) the staging block explicitly adds three-pillars-docs/specs/ path so the
        merged base (outside the design dir) lands in the archival commit.
    (c) the merge sub-step documents the no-op-skip when spec-delta.md is absent.
    """

    _SKILL_MD = Path(__file__).resolve().parent.parent / "tp-design-complete" / "SKILL.md"

    def test_design_complete_documents_merge_and_stages_base(self):
        """SKILL.md has /tp-spec merge sub-step BEFORE git mv AND stages specs/ path."""
        text = self._SKILL_MD.read_text(encoding="utf-8")

        # (a) Must mention /tp-spec merge somewhere
        assert "/tp-spec merge" in text, (
            "tp-design-complete/SKILL.md must document a '/tp-spec merge {design-name}' sub-step"
        )

        # (b) The merge sub-step must appear BEFORE the git mv line
        merge_idx = text.find("/tp-spec merge")
        git_mv_idx = text.find("git mv three-pillars-docs/tp-designs/")
        assert merge_idx != -1, "'/tp-spec merge' not found in SKILL.md"
        assert git_mv_idx != -1, "'git mv three-pillars-docs/tp-designs/' not found in SKILL.md"
        assert merge_idx < git_mv_idx, (
            "'/tp-spec merge' sub-step must appear BEFORE the 'git mv' line in SKILL.md "
            f"(merge at {merge_idx}, git mv at {git_mv_idx})"
        )

        # (c) The staging block must explicitly mention three-pillars-docs/specs/
        assert "three-pillars-docs/specs/" in text, (
            "tp-design-complete/SKILL.md step-6f staging must explicitly add "
            "'three-pillars-docs/specs/<domain>/spec.md' so the merged base "
            "(outside the design dir) is captured in the archival commit"
        )

    def test_design_complete_documents_noop_skip(self):
        """SKILL.md merge sub-step must document no-op skip when spec-delta.md absent."""
        text = self._SKILL_MD.read_text(encoding="utf-8")

        # Must mention the no-op / skip behavior for missing spec-delta.md
        has_noop = (
            "spec-delta.md does not exist" in text
            or "no spec-delta.md" in text
            or "no-op" in text.lower()
        )
        assert has_noop, (
            "tp-design-complete/SKILL.md merge sub-step must explicitly document "
            "that the step is a no-op / skip when the design has no spec-delta.md"
        )


# ---------------------------------------------------------------------------
# H1 (plugin-mode-parity) — the docs tree resolves from cwd (the consumer repo
# under operation), NOT the module's __file__ location. In plugin mode the
# module loads from the plugin cache, so a __file__-anchored root operates on
# the cache — /tp-spec add errors "design directory not found", /tp-spec merge
# silently no-ops. These reproduce the foreign-repo failure the review found.
# ---------------------------------------------------------------------------

class TestPluginModeResolvesConsumerCwd:
    """main() must resolve three-pillars-docs from cwd / --repo, not __file__."""

    def _consumer_with_design(self, tmp_path: Path, name: str = "my-design") -> Path:
        consumer = tmp_path / "consumer"
        design_dir = consumer / "three-pillars-docs" / "tp-designs" / name
        design_dir.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=str(consumer), check=True)
        return consumer

    def test_add_resolves_designs_root_from_cwd(self, tmp_path, monkeypatch):
        """add with cwd = a foreign consumer repo scaffolds INTO that repo —
        proving the root is cwd-derived, not module-derived (plugin cache)."""
        from tp_spec import main

        consumer = self._consumer_with_design(tmp_path)
        monkeypatch.chdir(consumer)
        rc = main(["add", "my-design"])
        assert rc == 0, "add must succeed against the consumer repo (cwd)"
        delta = consumer / "three-pillars-docs" / "tp-designs" / "my-design" / "spec-delta.md"
        assert delta.exists(), (
            "add must scaffold into the consumer repo resolved from cwd, "
            "not the module location (plugin cache in plugin mode)"
        )

    def test_add_honors_repo_override(self, tmp_path, monkeypatch):
        """--repo overrides cwd resolution, even from an unrelated cwd."""
        from tp_spec import main

        consumer = self._consumer_with_design(tmp_path, name="d")
        # cwd is deliberately NOT the consumer repo.
        monkeypatch.chdir(tmp_path)
        rc = main(["add", "d", "--repo", str(consumer)])
        assert rc == 0
        delta = consumer / "three-pillars-docs" / "tp-designs" / "d" / "spec-delta.md"
        assert delta.exists(), "--repo must direct the scaffold to the named repo"

    def test_merge_no_delta_skips_against_cwd_root(self, tmp_path, monkeypatch):
        """merge from a consumer cwd must inspect the consumer's design dir —
        the silent-false-success bug resolved the (empty) cache path instead."""
        from tp_spec import main

        consumer = self._consumer_with_design(tmp_path, name="dz")
        monkeypatch.chdir(consumer)
        # No spec-delta.md in the consumer design dir → legitimate skip (rc 0),
        # but the path it reports must be the CONSUMER dir, not a cache path.
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["merge", "dz"])
        assert rc == 0
        out = buf.getvalue()
        assert str(consumer) in out, (
            "merge must resolve the delta path under the consumer repo (cwd), "
            f"not the module/cache location; output was: {out!r}"
        )
