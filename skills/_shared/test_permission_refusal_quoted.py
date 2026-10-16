"""test_permission_refusal_quoted.py — a refusal is read only from a structured harness denial.

design: strata-classifier-cost-followups 2.4 (phase-check F1, operator ruling 2026-10-12)

`from_records` answers a refused call for `child_spawn.cmd_wait`, and `cmd_wait`'s banner makes the
ladder escalate a failed attempt to `sonnet-medium` on `permission-refused`. So the reading has to be
the harness's own denial and nothing else: a `tool_result` block the harness produced *for a denied
call* — `is_error` true AND the block's text, after leading whitespace, starting with the denial
prefix `Permission to use `. Text that merely quotes the denial inside another tool's output (a
Grep/Read of the test fixtures, Bash output, a pytest log) never flags, or every attempt that greps
for the denial string is sent up the ladder for a refusal it never hit.

The reply banner stays structural: `parse_lines` reads only the leading `permission-refused: ` block,
so a reply that contains the banner text later is quoting it, not refusing.

Nothing here starts a live `claude`, router or GPU job — `from_records` / `parse_lines` are pure
readers of records and text. Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from permission_refusal import from_records, parse_lines  # noqa: E402

PREFIX = "Permission to use "
BANNER = "permission-refused: "
RULE = "Bash(rm -rf build)"
REFUSED_TEXT = "Permission to use Bash with command rm -rf build has been denied"
QUOTED_GREP_LINE = ("child_spawn_fixture.py:190: Permission to use Bash with command "
                    "rm -rf build has been denied")
QUOTED_PYTEST_LINE = ("FAILED skills/_shared/test_child_spawn_fixture.py::test_refuse - "
                      "Permission to use Bash with command rm -rf build has been denied")


def _result(content, is_error=True) -> dict:
    """One transcript record: a `tool_result` block with `content`, answered with `is_error`."""
    block = {"type": "tool_result", "tool_use_id": "tu_inner", "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def test_error_result_without_the_prefix_is_not_a_refusal() -> None:
    """An ordinary failed tool result is not a refusal, whatever else its text says."""
    assert from_records([_result("Traceback (most recent call last):\nKeyError: 'x'\n")]) == []
    assert from_records([_result([{"type": "text", "text": "exit=1"}])]) == []


def test_not_an_error_result_with_the_denial_text_is_not_a_refusal() -> None:
    """The denial text alone never flags: a `tool_result` that did not error is not a denial."""
    assert from_records([_result(REFUSED_TEXT, is_error=False)]) == []
    assert from_records([_result(REFUSED_TEXT, is_error=None)]) == []
    assert from_records([_result([{"type": "text", "text": REFUSED_TEXT}], is_error=False)]) == []


def test_error_result_that_quotes_the_denial_mid_text_is_not_a_refusal() -> None:
    """A real error whose text only *quotes* the denial (a grep hit, a pytest log) never flags."""
    assert from_records([_result(QUOTED_GREP_LINE)]) == []
    assert from_records([_result(QUOTED_PYTEST_LINE)]) == []
    assert from_records([_result("the call failed:\n" + REFUSED_TEXT + "\nthen it gave up")]) == []
    assert from_records([_result([{"type": "text", "text": QUOTED_GREP_LINE}])]) == []


def test_grep_read_bash_output_that_quotes_the_denial_is_not_a_refusal() -> None:
    """The F1 case: the worker greps or reads the fixtures, so the denial string is in its output."""
    grep = {"type": "tool_result", "tool_use_id": "tu_grep", "is_error": False,
            "content": QUOTED_GREP_LINE}
    read = {"type": "tool_result", "tool_use_id": "tu_read",
            "content": [{"type": "text", "text": "189:        refused = {...}\n"
                                                 "190:        " + REFUSED_TEXT}]}
    bash = {"type": "tool_result", "tool_use_id": "tu_bash", "is_error": False,
            "content": "$ pytest -q\n" + QUOTED_PYTEST_LINE + "\n1 failed"}
    records = [_result(REFUSED_TEXT, is_error=False), _result(REFUSED_TEXT, is_error=None)]
    by_id = [{"type": "user", "message": {"role": "user", "content": [b]}}
             for b in (grep, read, bash)]
    assert from_records(records + by_id) == []


def test_harness_denial_still_flags_as_the_rule_to_add() -> None:
    """The one reading that counts: an error result whose text *starts* with the denial prefix."""
    assert from_records([_result(REFUSED_TEXT)]) == [RULE]
    assert from_records([_result([{"type": "text", "text": REFUSED_TEXT}])]) == [RULE]
    # leading whitespace before the prefix still counts
    assert from_records([_result("   \n" + REFUSED_TEXT)]) == [RULE]
    # a tool with no command is the bare tool name
    assert from_records([_result("Permission to use WebFetch has been denied")]) == ["WebFetch"]
    # only the block's own denial counts, and a non-error block is never read
    assert from_records([_result(REFUSED_TEXT + "\n" + REFUSED_TEXT)]) == [RULE]
    assert from_records([]) == []
    assert from_records("not a list") == []


def test_reply_banner_is_read_only_from_the_leading_block() -> None:
    """`parse_lines` stays structural: the banner text later in a reply is quoted, not refused."""
    reply = "\n".join(['{"task_id": "2.4", "sha": "abc", "claimed": "red"}', BANNER + RULE])
    assert parse_lines(reply) == []
    quoted = '{"task_id": "2.4", "note": "' + BANNER + RULE + '", "claimed": "green"}'
    assert parse_lines(quoted) == []
    assert parse_lines(BANNER + RULE + "\n" + quoted) == [RULE]
    assert parse_lines(PREFIX + "Bash has been denied") == []
