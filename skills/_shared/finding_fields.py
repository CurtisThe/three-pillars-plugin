"""Registries and normalization for finding `origin` and `fragility_class`.

See three-pillars-docs/completed-tp-designs/fragile-test-prevention/detailed-design.md,
section `finding_fields.normalize`.
"""

from __future__ import annotations

ORIGINS = ("original", "regression", "unclassified")

FRAGILITY_CLASSES = (
    "open-ended",
    "change-detector",
    "blocklist",
    "none",
    "unclassified",
)

FRAGILE_CLASSES = ("open-ended", "change-detector", "blocklist")


def normalize(finding: dict) -> dict:
    """Return a copy of `finding` with `origin` and `fragility_class` set.

    A missing or unknown value becomes `unclassified`, never a guess.
    """
    result = dict(finding)

    origin = result.get("origin")
    result["origin"] = origin if origin in ORIGINS else "unclassified"

    fragility_class = result.get("fragility_class")
    result["fragility_class"] = (
        fragility_class if fragility_class in FRAGILITY_CLASSES else "unclassified"
    )

    return result
