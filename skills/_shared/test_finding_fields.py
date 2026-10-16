"""Tests for finding_fields: the registries and normalize.

Oracle: example.
"""

from __future__ import annotations

import finding_fields


def test_origins_registry():
    assert finding_fields.ORIGINS == ("original", "regression", "unclassified")


def test_fragility_classes_registry():
    assert finding_fields.FRAGILITY_CLASSES == (
        "open-ended",
        "change-detector",
        "blocklist",
        "none",
        "unclassified",
    )


def test_fragile_classes_is_subset_excluding_none_and_unclassified():
    assert finding_fields.FRAGILE_CLASSES == (
        "open-ended",
        "change-detector",
        "blocklist",
    )
    assert set(finding_fields.FRAGILE_CLASSES) <= set(finding_fields.FRAGILITY_CLASSES)
    assert "none" not in finding_fields.FRAGILE_CLASSES
    assert "unclassified" not in finding_fields.FRAGILE_CLASSES


def test_normalize_keeps_known_origin_and_fragility_class():
    finding = {"origin": "regression", "fragility_class": "blocklist"}
    result = finding_fields.normalize(finding)
    assert result["origin"] == "regression"
    assert result["fragility_class"] == "blocklist"


def test_normalize_turns_missing_origin_into_unclassified():
    finding = {"fragility_class": "open-ended"}
    result = finding_fields.normalize(finding)
    assert result["origin"] == "unclassified"
    assert result["fragility_class"] == "open-ended"


def test_normalize_turns_unknown_origin_into_unclassified():
    finding = {"origin": "bogus", "fragility_class": "none"}
    result = finding_fields.normalize(finding)
    assert result["origin"] == "unclassified"
    assert result["fragility_class"] == "none"


def test_normalize_turns_missing_fragility_class_into_unclassified():
    finding = {"origin": "original"}
    result = finding_fields.normalize(finding)
    assert result["origin"] == "original"
    assert result["fragility_class"] == "unclassified"


def test_normalize_turns_unknown_fragility_class_into_unclassified():
    finding = {"origin": "original", "fragility_class": "bogus"}
    result = finding_fields.normalize(finding)
    assert result["origin"] == "original"
    assert result["fragility_class"] == "unclassified"


def test_normalize_does_not_mutate_input():
    finding = {"origin": "original"}
    finding_fields.normalize(finding)
    assert finding == {"origin": "original"}


def test_normalize_preserves_other_keys():
    finding = {"origin": "original", "fragility_class": "none", "message": "hi"}
    result = finding_fields.normalize(finding)
    assert result["message"] == "hi"
