"""classifier_judge — Sonnet prompt builder + response parser.

The helper owns prompt construction and schema-validated response parsing
only. The model invocation itself happens in `/tp-pr-iterate` SKILL.md
prose via `Agent(subagent_type="general-purpose", ...)` — never here.

C1 architectural constraint (asserted by Task 5.8's grep test via
`ast.parse`): this file must NOT `import anthropic` and must NOT
`subprocess.run(["claude", ...])`. Compute prompts; parse JSON; that is
the entire surface.

Public API:
- `build_prompt(borderline, diff_context) -> str` — builds the Sonnet
  prompt embedding comment text + diff hunks + classification
  instructions. `borderline` is a list of comment-like objects with at
  least `id`, `body`, `path`, `user` attributes; `diff_context` is a dict
  mapping file paths to diff-hunk strings.
- `parse_response(text) -> list[dict]` — extracts the JSON block from
  Sonnet's response, validates each entry against
  `classified-comment.v1.json` (additionalProperties=false), returns the
  validated list. Raises `jsonschema.ValidationError` on schema failure
  and `ValueError` when no JSON block can be located.

Prompt calibration history (Phase 8.2):
  - v0 (initial): 75% structural/minor accuracy, 0% unclear-as-structural.
    Too narrow on "structural" (bug-only definition); no safety bias.
  - v1: over-broadened structural — 65% accuracy. Stale dates / counts /
    status text got upgraded to structural.
  - v2 (current): 90-100% structural/minor accuracy, 100% unclear-as-
    structural across 2 runs. Uses a decision-tree structure (concrete
    code change → structural; pure question/reaction → structural via
    safety bias; trivial cosmetic → minor). Calibrated against
    `eval/comments.jsonl` (25 curated comments from CurtisThe/three-pillars
    PRs #16/#18/#19, astral-sh/ruff #25454, cli/cli #13479,
    Aider-AI/aider #5132). Reproduce with `eval/run_eval.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "classified-comment.v1.json"
_SCHEMA: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


_PROMPT_TEMPLATE = """\
You classify borderline PR review comments. Your output feeds a loop
driver that decides between (a) firing another fix-round of subagent
work to address the comment, or (b) skipping / batching the comment as
not worth a fix-round.

Decision tree (apply in order; the first match wins):

1. Does the comment request a CONCRETE CODE CHANGE that takes more
   than a one-line text edit? Examples:
   - New methods, traits, functions, or trait impls ("add `as_slice`",
     "implement `IntoIterator`").
   - Concrete code suggestions in ```suggestion``` blocks or with
     explicit code snippets to apply.
   - Missing logic: a dedup call, validation, error handling, retry,
     auth check, or other real-correctness behavior.
   - Refactor requests with concrete next-steps ("move this type to X").
   - Real bug, race, security issue, or incorrect behavior at runtime.
   - Operator-facing instructions (runbooks, CLI commands) that will
     misdirect or FAIL if followed as written — wrong path that doesn't
     exist, missing step, wrong command output.
   - Schema or contract violations against a documented spec (e.g., an
     enum field with an out-of-vocab value, a struct field not in the
     schema) — even if the fix is small, the load-bearing concern is
     spec correctness.
   → Verdict: "structural".

2. Is the comment a PURE QUESTION, REACTION, or NON-ACTION text with
   no embedded change request? Examples:
   - "Do we need this?" / "Have you considered X?" — open question.
   - "Very good" / "Good call" / "Nice" — praise.
   - "This was never used since" — author's justification, not a
     request.
   - Off-topic discussion or chitchat.
   → Verdict: "structural" anyway. The downstream system treats these
   safely (a fix-round on a non-actionable comment costs little and
   keeps a human in the loop). RESERVE "unclear" ONLY for cases where
   the comment text is so garbled or context-dependent that you cannot
   even classify the comment's intent (e.g., a single emoji with no
   surrounding text). In practice this should be rare.

3. Otherwise, the comment is a TRIVIAL COSMETIC FIX with no system
   behavior impact:
   - Typo, grammar, spelling, single-word rename.
   - Stale narrative tense, stale dates, version refs, item counts in
     human-readable text where the surrounding system still works.
   - Stale status / "last updated" lines, frontmatter tweaks.
   - Add a docstring or a sentence of documentation.
   - Tense / wording / capitalization tweaks.
   - Internal documentation contradictions where neither claim drives
     real behavior.
   → Verdict: "minor".

Tie-breaker: between structural and minor, prefer structural — the cost
of one extra fix-round is lower than the cost of silently shipping an
unaddressed substantive comment.

Confidence (title-case): "High", "Medium", or "Low".

Return STRICT JSON inside a fenced ```json``` block, an array of objects
matching:

  {{
    "comment_id":  <int or str — echo the input id>,
    "reviewer":    <str — echo the reviewer>,
    "verdict":     "structural" | "minor" | "unclear",
    "confidence":  "High" | "Medium" | "Low",
    "reason":      <one short sentence, ≤ 20 words>
  }}

Do NOT add extra fields. Do NOT omit required fields. Keep `reason`
under 20 words to avoid truncated output.

# Borderline comments

{comments_block}

# Diff context (file → hunk)

{diff_block}
"""


def _format_comment(c: Any) -> str:
    return (
        f"- id={getattr(c, 'id', '?')} reviewer={getattr(c, 'user', '?')!r} "
        f"path={getattr(c, 'path', '?')!r}\n"
        f"  body: {getattr(c, 'body', '')}"
    )


def _format_diff(diff_context: dict[str, str]) -> str:
    if not diff_context:
        return "(no diff context provided)"
    lines = []
    for path, hunk in diff_context.items():
        lines.append(f"## {path}\n{hunk}")
    return "\n\n".join(lines)


def build_prompt(borderline: list[Any], diff_context: dict[str, str]) -> str:
    """Build the Sonnet classification prompt. See module docstring."""
    comments_block = (
        "\n\n".join(_format_comment(c) for c in borderline)
        if borderline
        else "(no borderline comments)"
    )
    diff_block = _format_diff(diff_context)
    return _PROMPT_TEMPLATE.format(
        comments_block=comments_block, diff_block=diff_block
    )


_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_FENCED_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _extract_json_block(text: str) -> str:
    """Extract the JSON block from a Sonnet response.

    Resolution order:
      1. ```json fenced block (case-insensitive label). This is what the
         prompt instructs the model to emit.
      2. Any fenced block whose stripped content starts with `[` or `{` —
         covers the rare case where the model omits the language label.
      3. Raw JSON at the start of the stripped text.

    Requiring the `json` label first means a leading explanatory ``` block
    (no label) can't be grabbed as JSON by mistake.
    """
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1)
    for m in _ANY_FENCED_RE.finditer(text):
        block = m.group(1).strip()
        if block.startswith(("[", "{")):
            return block
    stripped = text.strip()
    if stripped.startswith(("[", "{")):
        return stripped
    raise ValueError("no JSON block found in Sonnet response")


def parse_response(text: str) -> list[dict]:
    """Extract + validate the classifier verdicts. See module docstring."""
    block = _extract_json_block(text)
    data = json.loads(block)
    if not isinstance(data, list):
        raise ValueError("Sonnet response JSON must be a top-level array")
    for entry in data:
        _VALIDATOR.validate(entry)
    return data
