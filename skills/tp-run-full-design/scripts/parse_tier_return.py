"""Parse a dispatched tier subagent's free-form reply into a validated dict.

Generic sibling of parse_candidate_response: the subagent may emit scratch
text plus one or more fenced ```json blocks; we take the LAST block as the
structured return envelope, check its `schema` field against the const the
caller-supplied schema pins (so the wrong schema class is rejected early),
validate against that schema, and raise typed errors for each failure mode.

The caller passes the schema_path for the slot's class (generator/audit/
handoff). Derived schemas inherit the base tier-return via allOf+$ref; refs
resolve through a referencing.Registry built from every schema in the dir.

The orchestrator keeps ONLY the returned dict and discards the raw reply
(the "return-clipping" rule) — this function is the clip point.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


class NoReturnBlockError(Exception):
    """Raised when the reply contains no ```json fenced block."""


class SchemaValidationError(Exception):
    """Raised when the JSON is unparseable or fails schema validation."""


class UnknownSchemaVersionError(Exception):
    """Raised when the block's `schema` field is not the one the schema pins."""


@functools.lru_cache(maxsize=None)
def _load_schema(schema_path: str) -> dict:
    """Read + parse a schema JSON once per path (the schemas dir is static per run)."""
    return json.loads(Path(schema_path).read_text())


@functools.lru_cache(maxsize=1)
def _registry() -> Registry:
    """Build the $ref registry once — the schema dir doesn't change at runtime,
    and the orchestrator calls parse_tier_return once per dispatched slot."""
    resources = []
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        schema = _load_schema(str(path))
        if "$id" in schema:
            resources.append(
                (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT7))
            )
    return Registry().with_resources(resources)


def _expected_schema_const(schema: dict) -> str | None:
    """The `schema` const a valid instance must carry, if the schema pins one.

    Returns None for the base tier-return schema (whose `schema` field has no
    const); the class guard is then skipped. That is acceptable because the
    orchestrator only ever passes a concrete class schema (generator/audit/
    handoff) as schema_path, never the base.
    """
    return schema.get("properties", {}).get("schema", {}).get("const")


def parse_tier_return(text: str, schema_path: Path) -> dict:
    """Extract and validate a tier return envelope against schema_path.

    Returns the validated dict (including its `status`); the orchestrator
    branches on `status` and discards the raw reply.
    """
    matches = FENCED_JSON_RE.findall(text)
    if not matches:
        raise NoReturnBlockError("no ```json fenced block found in tier reply")
    raw = matches[-1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SchemaValidationError(f"malformed JSON in tier-return block: {e}") from e

    schema = _load_schema(str(schema_path))
    expected = _expected_schema_const(schema)
    if not isinstance(parsed, dict) or (
        expected is not None and parsed.get("schema") != expected
    ):
        got = parsed.get("schema") if isinstance(parsed, dict) else type(parsed).__name__
        raise UnknownSchemaVersionError(
            f"unknown schema version: {got!r} (expected {expected!r})"
        )

    validator = jsonschema.Draft7Validator(schema, registry=_registry())
    error = jsonschema.exceptions.best_match(validator.iter_errors(parsed))
    if error is not None:
        raise SchemaValidationError(f"tier return failed schema validation: {error.message}")
    return parsed
