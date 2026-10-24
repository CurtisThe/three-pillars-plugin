"""Fix 1.fix: python_comment_only also requires an identical AST.

On Python 3.12 the spaces inside an f-string replacement field's `=` specifier appear in no
token, so the token-stream check alone calls `f"{x=}"` -> `f"{x = }"` neutral although the
printed output changes. The AST dump differs, so the class must reject it. Example-based table
(test-fragility.md section 3): each case is one concrete input with the spec's expected answer.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import proof_neutral_carry as pnc  # noqa: E402

# Two neutral lines so a case can edit below the frozen lines 1-2.
PRE = "import os\nimport sys\n"

REJECTED = {
    "fstring debug specifier spacing": (
        PRE + 'x = 1\nprint(f"{x=}")\n', PRE + 'x = 1\nprint(f"{x = }")\n'),
    "fstring debug specifier spacing with comment edit": (
        PRE + 'x = 1\nprint(f"{x=}")  # a\n', PRE + 'x = 1\nprint(f"{x = }")  # b\n'),
}

ACCEPTED = {
    "comment edit": (PRE + "x = 1  # old\n", PRE + "x = 1  # new\n"),
    "comment edit next to fstring with equals": (
        PRE + 'x = 1\nprint(f"{x=}")  # old\n', PRE + 'x = 1\nprint(f"{x=}")  # new\n'),
    "comment added above fstring with equals": (
        PRE + 'x = 1\nprint(f"{x = }")\n', PRE + 'x = 1\n# show it\nprint(f"{x = }")\n'),
}


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_ast_change_is_not_neutral(name):
    ok, why = pnc.python_comment_only(*REJECTED[name])
    assert ok is False
    assert why.startswith("ast-differs")


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_comment_only_still_neutral(name):
    assert pnc.python_comment_only(*ACCEPTED[name]) == (True, "")
