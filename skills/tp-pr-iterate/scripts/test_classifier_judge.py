"""Tests for `classifier_judge` — Sonnet prompt builder + response parser.

The helper owns:
- `build_prompt(borderline, diff_context) -> str` — builds the Sonnet prompt.
- `parse_response(text) -> list[dict]` — extracts JSON, validates each
  entry against `classified-comment.v1.json`, rejects unknown fields.

What the helper does NOT own (C1 architectural constraint):
- Any `import anthropic`.
- Any `subprocess.run(["claude", ...])`.
The model invocation happens in `/tp-pr-iterate` SKILL.md prose via
`Agent()`. This test file asserts API shape; Task 5.8's grep test asserts
the helper file is import-free of `anthropic` via `ast.parse`.

Run with: pytest skills/tp-pr-iterate/scripts/test_classifier_judge.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import classifier_judge  # noqa: E402


@dataclass
class _Comment:
    """Minimal duck-type for what build_prompt reads off a comment."""

    id: int
    body: str
    path: str
    user: str


def test_build_prompt_includes_borderline_comments_and_diff_context():
    borderline = [
        _Comment(id=42, body="this might be a bug or a typo", path="src/foo.py", user="alice"),
        _Comment(id=43, body="rename or refactor?", path="src/bar.py", user="bob"),
    ]
    diff_context = {"src/foo.py": "@@ -10,3 +10,3 @@\n-x\n+y", "src/bar.py": "@@ -1 +1 @@\n+z"}

    prompt = classifier_judge.build_prompt(borderline, diff_context)

    # The prompt must reference each comment so Sonnet can address them.
    assert "42" in prompt or "id=42" in prompt, "comment id 42 must appear"
    assert "43" in prompt or "id=43" in prompt, "comment id 43 must appear"
    assert "this might be a bug or a typo" in prompt
    assert "rename or refactor?" in prompt
    # Diff context must be embedded.
    assert "src/foo.py" in prompt
    assert "src/bar.py" in prompt
    assert "@@ -10,3 +10,3 @@" in prompt
    # Classification instructions must spell out the verdict vocabulary so
    # Sonnet returns one of the three values parse_response accepts.
    body_l = prompt.lower()
    assert "structural" in body_l
    assert "minor" in body_l
    assert "unclear" in body_l


def test_parse_response_validates_per_classified_comment_schema():
    """parse_response returns a list[dict] each validating against
    classified-comment.v1.json. Title-case confidence per VALID_CONFIDENCES."""

    sonnet_text = """Here is my classification:

```json
[
  {
    "comment_id": 42,
    "reviewer": "alice",
    "verdict": "structural",
    "confidence": "High",
    "reason": "names a race condition explicitly"
  },
  {
    "comment_id": 43,
    "reviewer": "bob",
    "verdict": "minor",
    "confidence": "Medium",
    "reason": "rename-only change to a private helper"
  }
]
```

Hope that helps."""

    result = classifier_judge.parse_response(sonnet_text)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["comment_id"] == 42
    assert result[0]["verdict"] == "structural"
    assert result[0]["confidence"] == "High"
    assert result[1]["verdict"] == "minor"
    assert result[1]["confidence"] == "Medium"


def test_parse_response_rejects_unknown_fields():
    """`additionalProperties: false` in the schema must be enforced."""

    sonnet_text = """```json
[
  {
    "comment_id": 99,
    "reviewer": "alice",
    "verdict": "structural",
    "confidence": "High",
    "reason": "ok",
    "extra_field_not_in_schema": "should be rejected"
  }
]
```"""

    with pytest.raises(Exception):
        # jsonschema.ValidationError is acceptable; any subclass is fine.
        classifier_judge.parse_response(sonnet_text)
