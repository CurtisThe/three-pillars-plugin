"""Tests for skills/_shared/spec_drift.py — drift-detection guard.

Covers Phase 1 of the living-spec-layer plan:
  1.1 anchor extraction from parsed requirements
  1.2 resolve_anchor — path and symbol@path resolution
  1.3 scan_spec — dangling-ref blocks, zero-anchor WARNs (strict promotes)
  1.4 retired-symbol check across surviving requirements
  1.5 scan CLI + JSON verdict + exit-code parity with spec_delta
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_delta import parse_spec  # noqa: E402
from spec_drift import (  # noqa: E402
    _extract_anchors,
    main,
    resolve_anchor,
    scan_spec,
)

# ---------------------------------------------------------------------------
# Fixture spec text helpers
# ---------------------------------------------------------------------------

def _make_spec(req_blocks: str) -> str:
    return f"## Requirements\n\n{req_blocks}\n"


ANCHOR_SPEC_TEXT = _make_spec(
    "### Requirement: Alpha\n"
    "The system SHALL do alpha.\n\n"
    "> Code: skills/_shared/spec_delta.py\n"
    "> Test: skills/_shared/test_spec_delta.py::test_merge\n\n"
    "#### Scenario: Alpha scenario\n"
    "- **WHEN** alpha happens\n"
    "- **THEN** it works\n"
)

NO_ANCHOR_SPEC_TEXT = _make_spec(
    "### Requirement: Beta\n"
    "The system SHALL do beta.\n\n"
    "#### Scenario: Beta scenario\n"
    "- **WHEN** beta happens\n"
    "- **THEN** it works\n"
)


# ---------------------------------------------------------------------------
# Task 1.1 — _extract_anchors
# ---------------------------------------------------------------------------

class TestExtractAnchors:
    def test_extract_anchors_parses_code_and_test_lines(self):
        spec = parse_spec(ANCHOR_SPEC_TEXT)
        req = spec.requirements["Alpha"]
        anchors = _extract_anchors(req)
        assert "skills/_shared/spec_delta.py" in anchors
        assert "skills/_shared/test_spec_delta.py::test_merge" in anchors

    def test_extract_anchors_no_annotations_returns_empty(self):
        spec = parse_spec(NO_ANCHOR_SPEC_TEXT)
        req = spec.requirements["Beta"]
        anchors = _extract_anchors(req)
        assert anchors == []

    def test_extract_anchors_strips_inline_html_comments(self):
        """An anchor line with a co-located <!-- --> comment (as in the
        shipped template) must yield only the real path, never the comment
        words as spurious anchors."""
        comment_spec = _make_spec(
            "### Requirement: Commented\n"
            "The system SHALL do commented.\n\n"
            "> Code: skills/_shared/spec_delta.py        <!-- repo-relative path -->\n"
            "> Test: skills/_shared/test_spec_delta.py::test_merge  <!-- path::function -->\n\n"
            "#### Scenario: Commented scenario\n"
            "- **WHEN** commented\n"
            "- **THEN** it works\n"
        )
        spec = parse_spec(comment_spec)
        anchors = _extract_anchors(spec.requirements["Commented"])
        assert anchors == [
            "skills/_shared/spec_delta.py",
            "skills/_shared/test_spec_delta.py::test_merge",
        ], f"comment words leaked into anchors: {anchors}"


# ---------------------------------------------------------------------------
# Task 1.2 — resolve_anchor
# ---------------------------------------------------------------------------

class TestResolveAnchor:
    def test_resolve_anchor_path_and_symbol(self, tmp_path):
        # Create a python file with a function and a class
        pkg = tmp_path / "rel"
        pkg.mkdir()
        py_file = pkg / "mymod.py"
        py_file.write_text(
            "def foo():\n    pass\n\nclass Bar:\n    pass\n"
        )

        # Plain path — present
        assert resolve_anchor("rel/mymod.py", tmp_path) is True

        # Plain path — missing
        assert resolve_anchor("rel/missing.py", tmp_path) is False

        # symbol@path — present symbol (function)
        assert resolve_anchor("foo@rel/mymod.py", tmp_path) is True

        # symbol@path — present symbol (class)
        assert resolve_anchor("Bar@rel/mymod.py", tmp_path) is True

        # symbol@path — absent symbol
        assert resolve_anchor("baz@rel/mymod.py", tmp_path) is False

        # symbol@path — missing file
        assert resolve_anchor("foo@rel/ghost.py", tmp_path) is False

        # ::style test anchor — path+name present
        assert resolve_anchor("rel/mymod.py::foo", tmp_path) is True

        # ::style test anchor — name absent
        assert resolve_anchor("rel/mymod.py::nope", tmp_path) is False


# ---------------------------------------------------------------------------
# Task 1.3 — scan_spec
# ---------------------------------------------------------------------------

class TestScanSpec:
    def _make_dangling_spec(self) -> str:
        return _make_spec(
            "### Requirement: Dangling\n"
            "The system SHALL have dangling.\n\n"
            "> Code: nonexistent/file.py\n\n"
            "#### Scenario: Dangling scenario\n"
            "- **WHEN** something\n"
            "- **THEN** fails\n"
        )

    def _make_clean_spec(self, existing_file: str) -> str:
        return _make_spec(
            f"### Requirement: Clean\n"
            f"The system SHALL be clean.\n\n"
            f"> Code: {existing_file}\n\n"
            f"#### Scenario: Clean scenario\n"
            f"- **WHEN** clean\n"
            f"- **THEN** works\n"
        )

    def test_scan_spec_dangling_and_zero_anchor(self, tmp_path):
        from spec_delta import Issue

        # (a) dangling ref → ERROR
        dangling_spec = parse_spec(self._make_dangling_spec())
        issues_a = scan_spec(dangling_spec, tmp_path, strict=False)
        error_codes = [i.code for i in issues_a if i.severity == "ERROR"]
        assert "dangling-ref" in error_codes

        # (b) zero-anchor, strict=False → WARN
        no_anchor_spec = parse_spec(NO_ANCHOR_SPEC_TEXT)
        issues_b = scan_spec(no_anchor_spec, tmp_path, strict=False)
        warn_codes = [i.code for i in issues_b if i.severity == "WARN"]
        assert "zero-anchor" in warn_codes
        err_codes_b = [i.code for i in issues_b if i.severity == "ERROR"]
        assert "zero-anchor" not in err_codes_b

        # (b) zero-anchor, strict=True → ERROR
        issues_b_strict = scan_spec(no_anchor_spec, tmp_path, strict=True)
        err_codes_b_strict = [i.code for i in issues_b_strict if i.severity == "ERROR"]
        assert "zero-anchor" in err_codes_b_strict

        # (c) fully-resolved → no Issues
        real_file = tmp_path / "real.py"
        real_file.write_text("# content\n")
        clean_spec = parse_spec(self._make_clean_spec("real.py"))
        issues_c = scan_spec(clean_spec, tmp_path, strict=False)
        assert issues_c == []

        # All Issues have expected fields (are spec_delta.Issue instances)
        for issue in issues_a + issues_b:
            assert hasattr(issue, "severity")
            assert hasattr(issue, "code")
            assert hasattr(issue, "message")
            assert hasattr(issue, "location")


# ---------------------------------------------------------------------------
# Task 1.4 — retired symbol check
# ---------------------------------------------------------------------------

class TestRetiredSymbol:
    def test_retired_symbol_still_anchored_blocks(self, tmp_path):
        """A surviving requirement anchoring a gone symbol yields dangling-ref ERROR."""
        # Create a file but WITHOUT the expected symbol
        src = tmp_path / "engine.py"
        src.write_text("def still_here():\n    pass\n")

        retired_spec_text = _make_spec(
            "### Requirement: RetiredFeature\n"
            "The system SHALL use the retired symbol.\n\n"
            "> Code: retired_symbol@engine.py\n\n"
            "#### Scenario: Retired scenario\n"
            "- **WHEN** we call retired\n"
            "- **THEN** nothing\n"
        )
        spec = parse_spec(retired_spec_text)
        issues = scan_spec(spec, tmp_path, strict=False)
        error_codes = [i.code for i in issues if i.severity == "ERROR"]
        # A symbol-form anchor (symbol@path) whose symbol is gone is classed
        # retired-symbol — distinct from a plain dangling path.
        assert "retired-symbol" in error_codes, (
            f"symbol@path anchor must be retired-symbol; got {error_codes}"
        )
        # The location should name the symbol or requirement
        error_issues = [i for i in issues if i.severity == "ERROR"]
        assert any("RetiredFeature" in i.location or "retired_symbol" in i.location
                   for i in error_issues)

    def test_plain_path_anchor_is_dangling_ref_not_retired_symbol(self, tmp_path):
        """A plain-path anchor (no symbol) that does not resolve must be classed
        dangling-ref, distinct from retired-symbol. Pairs with the symbol-form
        test above to keep the two classification branches discriminated."""
        plain_spec_text = _make_spec(
            "### Requirement: PlainGone\n"
            "The system SHALL reference a missing file.\n\n"
            "> Code: gone/missing.py\n\n"
            "#### Scenario: Plain scenario\n"
            "- **WHEN** we look\n"
            "- **THEN** nothing\n"
        )
        spec = parse_spec(plain_spec_text)
        issues = scan_spec(spec, tmp_path, strict=False)
        error_codes = [i.code for i in issues if i.severity == "ERROR"]
        assert "dangling-ref" in error_codes, (
            f"plain-path anchor must be dangling-ref; got {error_codes}"
        )
        assert "retired-symbol" not in error_codes, (
            "plain-path anchor must NOT be classed retired-symbol"
        )


# ---------------------------------------------------------------------------
# Task 1.5 — CLI scan + JSON verdict + exit codes
# ---------------------------------------------------------------------------

class TestCLIScan:
    def _make_specs_dir(self, tmp_path, spec_text: str, domain: str = "testdomain") -> Path:
        """Create a specs dir with one domain spec.md."""
        specs = tmp_path / "specs"
        domain_dir = specs / domain
        domain_dir.mkdir(parents=True)
        (domain_dir / "spec.md").write_text(spec_text)
        return specs

    def test_cli_scan_exit_codes_and_json_verdict(self, tmp_path):
        # --- clean tree → 0, no stderr verdict ---
        real_file = tmp_path / "myfile.py"
        real_file.write_text("# content\n")
        clean_spec = _make_spec(
            "### Requirement: Clean\n"
            "Clean thing.\n\n"
            "> Code: myfile.py\n\n"
            "#### Scenario: Clean\n"
            "- **WHEN** clean\n"
            "- **THEN** works\n"
        )
        specs_dir = self._make_specs_dir(tmp_path, clean_spec)
        result = main(["scan", str(specs_dir), "--repo", str(tmp_path)])
        assert result == 0

        # --- dangling ref → 1, stderr is JSON DRIFT ---
        dangling_spec = _make_spec(
            "### Requirement: Dangling\n"
            "Dangling thing.\n\n"
            "> Code: nope/missing.py\n\n"
            "#### Scenario: Dangling\n"
            "- **WHEN** dangling\n"
            "- **THEN** fails\n"
        )
        specs_dir2 = self._make_specs_dir(tmp_path, dangling_spec, domain="domain2")

        import io as _io
        old_stderr = sys.stderr
        sys.stderr = _io.StringIO()
        try:
            result2 = main(["scan", str(specs_dir2), "--repo", str(tmp_path)])
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert result2 == 1
        verdict = json.loads(stderr_output.strip())
        assert verdict["verdict"] == "DRIFT"
        assert "violations" in verdict
        violations = verdict["violations"]
        assert len(violations) >= 1
        for v in violations:
            assert "severity" in v
            assert "code" in v
            assert "message" in v
            assert "location" in v

        # --- bad args → 2 ---
        result3 = main([])
        assert result3 == 2

        result4 = main(["scan"])
        assert result4 == 2

    def test_cli_malformed_requirement_header_is_not_false_pass(self, tmp_path):
        """A domain spec whose `### Requirement:` header is malformed (missing
        space: `###Requirement:`) parses to zero requirements, which would
        otherwise silently disable drift detection. The scan must emit an
        ERROR `empty-domain` Issue and exit 1, NOT false-pass with exit 0."""
        malformed_spec = (
            "## Requirements\n\n"
            "###Requirement: Typo\n"  # missing space → REQ_RE does not match
            "The system SHALL do something.\n\n"
            "> Code: nonexistent/file.py\n\n"
            "#### Scenario: Whatever\n"
            "- **WHEN** x\n"
            "- **THEN** y\n"
        )
        specs_dir = self._make_specs_dir(tmp_path, malformed_spec, domain="malformed")

        import io as _io
        old_stderr = sys.stderr
        sys.stderr = _io.StringIO()
        try:
            result = main(["scan", str(specs_dir), "--repo", str(tmp_path)])
            stderr_out = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert result == 1, "malformed-header domain must NOT false-pass (expected exit 1)"
        verdict = json.loads(stderr_out.strip())
        assert verdict["verdict"] == "DRIFT"
        codes = [v["code"] for v in verdict["violations"]]
        assert "empty-domain" in codes, f"expected empty-domain Issue; got {codes}"

    def test_cli_strict_promotes_zero_anchor_to_drift(self, tmp_path):
        """--strict promotes zero-anchor-only tree from exit 0 to exit 1."""
        no_anchor_spec = NO_ANCHOR_SPEC_TEXT
        specs_dir = self._make_specs_dir(tmp_path, no_anchor_spec)

        # without --strict: zero-anchor is WARN → exit 0
        result_no_strict = main(["scan", str(specs_dir), "--repo", str(tmp_path)])
        assert result_no_strict == 0

        # with --strict: zero-anchor is ERROR → exit 1
        import io as _io
        old_stderr = sys.stderr
        sys.stderr = _io.StringIO()
        try:
            result_strict = main(["scan", str(specs_dir), "--repo", str(tmp_path), "--strict"])
            stderr_out = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert result_strict == 1
        verdict = json.loads(stderr_out.strip())
        assert verdict["verdict"] == "DRIFT"


# ---------------------------------------------------------------------------
# Phase 2 — seeded base spec tree scans clean against the real repo
# ---------------------------------------------------------------------------

class TestSeededSpecsClean:
    """Verify that the seeded pipeline and framework spec files scan with
    zero ERROR Issues against the actual repository root."""

    _REPO_ROOT = Path(__file__).resolve().parent.parent.parent

    def _run_scan_spec(self, domain: str) -> list:
        from spec_delta import parse_spec as _parse_spec

        spec_file = self._REPO_ROOT / "three-pillars-docs" / "specs" / domain / "spec.md"
        text = spec_file.read_text(encoding="utf-8")
        spec = _parse_spec(text)
        return scan_spec(spec, self._REPO_ROOT, strict=False)

    def test_seeded_pipeline_spec_scans_clean(self):
        issues = self._run_scan_spec("pipeline")
        errors = [i for i in issues if i.severity == "ERROR"]
        assert errors == [], f"pipeline spec has drift errors: {errors}"

    def test_seeded_framework_spec_scans_clean(self):
        issues = self._run_scan_spec("framework")
        errors = [i for i in issues if i.severity == "ERROR"]
        assert errors == [], f"framework spec has drift errors: {errors}"
