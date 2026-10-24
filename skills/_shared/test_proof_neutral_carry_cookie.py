"""A comment edit is neutral only when Python reads the file as UTF-8 (review round 1 finding).

The classifier compares the str view of a `.py` file, but Python decodes source with the coding
cookie. Under a utf-7 or `unicode_escape` cookie an edit that looks like a comment change adds a
statement, so every non-UTF-8 cookie is not neutral. Example-based oracle (test-fragility.md
section 3): each case is one concrete before/after pair.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proof_neutral_carry as pnc  # noqa: E402


def _src(*lines):
    return "\n".join(lines) + "\n"


def test_utf7_comment_edit_that_decodes_to_code_is_not_neutral():
    before = _src("# -*- coding: utf-7 -*-", "import os", "ALLOW = False", "# tuning note")
    after = _src("# -*- coding: utf-7 -*-", "import os", "ALLOW = False",
                 "# tuning note +AAo-ALLOW = True")
    ok, why = pnc.python_comment_only(before, after)
    assert (ok, why) == (False, "source encoding is not UTF-8")


@pytest.mark.parametrize("cookie", ["unicode_escape", "raw_unicode_escape", "latin-1"])
def test_other_cookies_are_not_neutral(cookie):
    head = f"# -*- coding: {cookie} -*-"
    before = _src(head, "import os", "X = 1", "# a")
    after = _src(head, "import os", "X = 1", "# b")
    assert pnc.python_comment_only(before, after)[0] is False


@pytest.mark.parametrize("head", ["# -*- coding: utf-8 -*-", "# coding: utf_8", "import os"])
def test_utf8_cookie_or_none_keeps_a_comment_edit_neutral(head):
    before = _src(head, "import sys", "X = 1  # a")
    after = _src(head, "import sys", "X = 1  # b")
    assert pnc.python_comment_only(before, after) == (True, "")


def test_waiver_after_other_text_in_a_comment_is_a_directive():
    before = _src("import os", "import sys", "try:", "    pass", "except Exception:  # best effort")
    after = _src("import os", "import sys", "try:", "    pass",
                 "except Exception:  # best effort #tp-allow-fail-open: ok")
    assert pnc.python_comment_only(before, after)[0] is False
