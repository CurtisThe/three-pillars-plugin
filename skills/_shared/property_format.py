"""Canonical reference for the six Notion property-format transforms.

The PUBLIC three-pillars substrate never serializes Notion properties. This module
is the documentation-as-test reference that the private plugin's
`notion-format-smoke` CI imports `TRANSFORMS` from to verify its writer matches.

**Anchored count**: six transforms. The dict keys exported in `TRANSFORMS` are the
public contract; the v3-audit "gotcha" names in parentheses are the historical
external labels these transforms address (kept here so the v3-audit M2 and v4-audit
clarification-3 trail is greppable):

    | `TRANSFORMS` key       | v3-audit gotcha label                |
    |------------------------|--------------------------------------|
    | `number_raw`           | number-raw                           |
    | `datetime_iso`         | datetime-int                         |
    | `select_with_emoji`    | select-with-emoji                    |
    | `relation_uuid_array`  | relation-as-url-array-string         |
    | `person_uuid_array`    | person-as-uuid-array-string          |
    | `checkbox_bool`        | checkbox-as-YES-NO                   |

Adding a seventh transform requires coordinated update with the private plugin's
smoke test. Resolves v3 audit M2 and v4 audit clarification 3 in a single place.

See: three-pillars-docs/completed-tp-designs/substrate-test-harness/detailed-design.md §Interfaces
"""

from __future__ import annotations

from datetime import datetime, timezone


# --- number_raw ---

def number_raw(n: int | float) -> dict:
    """42 -> {"number": 42}. Inverse preserves numeric type."""
    return {"number": n}


def number_raw_inv(payload: dict) -> int | float:
    return payload["number"]


# --- datetime_iso ---
#
# Contract: input MUST be timezone-aware UTC; serialized as
# "YYYY-MM-DDTHH:MM:SS+00:00" (no microseconds, explicit offset — NOT Z).
# Inverse parses via datetime.fromisoformat (Python 3.11+).

def datetime_iso(dt: datetime) -> dict:
    """datetime -> {"date": {"start": "YYYY-MM-DDTHH:MM:SS+00:00"}}.

    Raises ValueError if dt is naive (no tzinfo).
    """
    if dt.tzinfo is None:
        raise ValueError("datetime_iso requires timezone-aware datetime (got naive)")
    # Strip microseconds, normalize to UTC, format with explicit +00:00 offset.
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return {"date": {"start": dt.isoformat()}}


def datetime_iso_inv(payload: dict) -> datetime:
    return datetime.fromisoformat(payload["date"]["start"])


# --- select_with_emoji ---

def select_with_emoji(name: str) -> dict:
    """\"🔥 hot\" -> {\"select\": {\"name\": \"🔥 hot\"}}. Preserves Unicode bytewise."""
    return {"select": {"name": name}}


def select_with_emoji_inv(payload: dict) -> str:
    return payload["select"]["name"]


# --- relation_uuid_array ---

def relation_uuid_array(uuids: list[str]) -> dict:
    """[uuid] -> {\"relation\": [{\"id\": uuid}, ...]}."""
    return {"relation": [{"id": u} for u in uuids]}


def relation_uuid_array_inv(payload: dict) -> list[str]:
    return [item["id"] for item in payload["relation"]]


# --- person_uuid_array ---

def person_uuid_array(uuids: list[str]) -> dict:
    """[uuid] -> {\"people\": [{\"id\": uuid, \"object\": \"user\"}, ...]}."""
    return {"people": [{"id": u, "object": "user"} for u in uuids]}


def person_uuid_array_inv(payload: dict) -> list[str]:
    return [item["id"] for item in payload["people"]]


# --- checkbox_bool ---

def checkbox_bool(b: bool) -> dict:
    """True -> {\"checkbox\": True}. NOT \"YES\"/\"NO\" strings."""
    return {"checkbox": b}


def checkbox_bool_inv(payload: dict) -> bool:
    return payload["checkbox"]


# --- Canonical examples (one (input, payload) pair per transform) ---

_CANONICAL_DT = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
_CANONICAL_DT_STR = "2026-05-23T12:00:00+00:00"

CANONICAL_EXAMPLES: dict[str, tuple] = {
    "number_raw": (42, {"number": 42}),
    "datetime_iso": (_CANONICAL_DT, {"date": {"start": _CANONICAL_DT_STR}}),
    "select_with_emoji": ("🔥 hot", {"select": {"name": "🔥 hot"}}),
    "relation_uuid_array": (
        ["abc-uuid-1", "def-uuid-2"],
        {"relation": [{"id": "abc-uuid-1"}, {"id": "def-uuid-2"}]},
    ),
    "person_uuid_array": (
        ["user-uuid-1"],
        {"people": [{"id": "user-uuid-1", "object": "user"}]},
    ),
    "checkbox_bool": (True, {"checkbox": True}),
}


# --- TRANSFORMS table (name -> (forward, inverse)) ---

TRANSFORMS: dict[str, tuple] = {
    "number_raw": (number_raw, number_raw_inv),
    "datetime_iso": (datetime_iso, datetime_iso_inv),
    "select_with_emoji": (select_with_emoji, select_with_emoji_inv),
    "relation_uuid_array": (relation_uuid_array, relation_uuid_array_inv),
    "person_uuid_array": (person_uuid_array, person_uuid_array_inv),
    "checkbox_bool": (checkbox_bool, checkbox_bool_inv),
}
