"""test_settings_shape.py — Shape tests for settings.json and schema docs.

Phase 5:
  TestSettingsShape  (Task 5.1) — deny rule present, allow unchanged, skipDangerous=false
  TestDocsShape      (Task 5.2) — schema description + residual note
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SHARED_DIR.parent.parent


class TestSettingsShape:
    """settings.json shape: deny array contains no-verify rules, allow unchanged."""

    def _load_settings(self) -> dict:
        settings_path = _REPO_ROOT / "settings.json"
        return json.loads(settings_path.read_text())

    def test_settings_is_valid_json(self):
        """settings.json parses as JSON."""
        settings = self._load_settings()
        assert isinstance(settings, dict)

    def test_deny_array_exists(self):
        """permissions.deny exists and is a list."""
        settings = self._load_settings()
        deny = settings.get("permissions", {}).get("deny")
        assert deny is not None, "permissions.deny is missing from settings.json"
        assert isinstance(deny, list), f"permissions.deny must be a list, got {type(deny)}"

    def test_deny_contains_no_verify_long_form(self):
        """permissions.deny contains the Bash(git commit --no-verify:*) rule."""
        settings = self._load_settings()
        deny = settings["permissions"]["deny"]
        assert "Bash(git commit --no-verify:*)" in deny, (
            f"Bash(git commit --no-verify:*) not in deny: {deny}"
        )

    def test_deny_contains_no_verify_short_form(self):
        """permissions.deny contains the Bash(git commit -n:*) rule."""
        settings = self._load_settings()
        deny = settings["permissions"]["deny"]
        assert "Bash(git commit -n:*)" in deny, (
            f"Bash(git commit -n:*) not in deny: {deny}"
        )

    def test_allow_list_still_contains_pytest(self):
        """permissions.allow still contains Bash(python -m pytest:*)."""
        settings = self._load_settings()
        allow = settings.get("permissions", {}).get("allow", [])
        assert "Bash(python -m pytest:*)" in allow, (
            f"Bash(python -m pytest:*) missing from allow: {allow}"
        )

    def test_skip_dangerous_mode_still_false(self):
        """skipDangerousModePermissionPrompt is still false."""
        settings = self._load_settings()
        val = settings.get("skipDangerousModePermissionPrompt")
        assert val is False, (
            f"skipDangerousModePermissionPrompt must be false, got {val!r}"
        )


class TestDocsShape:
    """Schema description contains the land-boundary sentence; residual note exists."""

    def _load_schema(self) -> dict:
        schema_path = _SHARED_DIR / "repo-config.schema.json"
        return json.loads(schema_path.read_text())

    def test_schema_is_valid_json(self):
        """repo-config.schema.json parses as JSON."""
        schema = self._load_schema()
        assert isinstance(schema, dict)

    def test_require_human_approval_description_has_land_boundary_sentence(self):
        """The require_human_approval description mentions land.py hard-refuses."""
        schema = self._load_schema()
        # Navigate to the require_human_approval description
        desc = (
            schema
            .get("properties", {})
            .get("review", {})
            .get("properties", {})
            .get("require_human_approval", {})
            .get("description", "")
        )
        assert desc, "require_human_approval description is empty or missing"
        # The description should mention the land-boundary guarantee
        desc_lower = desc.lower()
        assert "land" in desc_lower or "irreversible" in desc_lower, (
            "require_human_approval description should mention the land boundary "
            f"guarantee. Got: {desc!r}"
        )
        # Should not imply opting out bypasses the irreversible boundary
        assert "land.py" in desc or "land boundary" in desc_lower or "irreversible" in desc_lower

    def test_deny_residual_note_exists(self):
        """The prefix-match limitation is documented in the require_human_approval description.

        The deny rule Bash(git commit --no-verify:*) uses a prefix match, which
        cannot block '--no-verify' appearing after other args. The residual note
        must appear specifically in the require_human_approval description in
        repo-config.schema.json — not just anywhere in the file — so that removing
        the note from that description fails this test.
        """
        schema = self._load_schema()
        # Navigate specifically to the require_human_approval description
        desc = (
            schema
            .get("properties", {})
            .get("review", {})
            .get("properties", {})
            .get("require_human_approval", {})
            .get("description", "")
        )
        assert desc, (
            "require_human_approval description is empty or missing in repo-config.schema.json"
        )
        desc_lower = desc.lower()
        # The residual note must appear in this specific description
        assert "prefix" in desc_lower, (
            "The deny-rule prefix-match residual note must appear in the "
            "require_human_approval description in repo-config.schema.json. "
            "Expected 'prefix' (describing that Bash(git commit --no-verify:*) uses a "
            "prefix match and cannot block --no-verify after other args). "
            f"Got description: {desc!r}"
        )
