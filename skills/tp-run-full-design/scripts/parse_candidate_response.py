"""Parse a worker agent's free-form reply into a validated candidate.v1 dict.

The worker may emit scratch text plus one or more fenced ```json blocks; we
take the LAST block as the structured candidate, validate it against
candidate.v1.json, and raise typed errors for each failure mode.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "candidate.v1.json"
SCHEMA_VERSION = "tp-run-full-design/candidate/v1"
FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


class NoCandidateBlockError(Exception):
    """Raised when the reply contains no ```json fenced block."""


class SchemaValidationError(Exception):
    """Raised when the JSON is unparseable or fails schema validation."""


class UnknownSchemaVersionError(Exception):
    """Raised when the JSON's `schema` field is not a recognized version."""


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def parse_candidate_response(text: str) -> dict:
    """Extract and validate the candidate.v1 payload from a worker reply."""
    matches = FENCED_JSON_RE.findall(text)
    if not matches:
        raise NoCandidateBlockError("no ```json fenced block found in response")
    raw = matches[-1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SchemaValidationError(f"malformed JSON in candidate block: {e}") from e
    if not isinstance(parsed, dict) or parsed.get("schema") != SCHEMA_VERSION:
        raise UnknownSchemaVersionError(
            f"unknown schema version: {parsed.get('schema') if isinstance(parsed, dict) else type(parsed).__name__}"
        )
    try:
        jsonschema.validate(instance=parsed, schema=_load_schema())
    except jsonschema.ValidationError as e:
        raise SchemaValidationError(f"candidate failed schema validation: {e.message}") from e
    return parsed
