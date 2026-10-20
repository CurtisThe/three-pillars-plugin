"""The fence's expansion pre-check reads real quoting (PR #323 review, round 1).

Fence mode reads a single-quoted span as data before it looks for a `$(…)` or a
backtick beside a delete word. It used to strip any `'…'` pair by regex, so two
apostrophes inside a double-quoted message (`don't … it's`) erased the real
backtick between them, and the quotes inside an unquoted heredoc body (which
bash does not treat as quoting) erased a `$(…)` that bash runs. The scan now
tracks double quotes and backslash escapes, and reads heredoc bodies as text.
"""
from __future__ import annotations

import pytest

from delete_fence_verbs import strip_single_quoted
from reviewer_delete_guard import classify


def _allowed(cmd, root):
    return classify(cmd, scratch=[root], cwd=root, mode="fence").allowed


@pytest.fixture
def dirs(tmp_path):
    root, out = tmp_path / "root", tmp_path / "out"
    root.mkdir()
    out.mkdir()
    return str(root), str(out)


def test_apostrophes_inside_double_quotes_do_not_hide_a_backtick(dirs):
    root, out = dirs
    cmd = 'git commit -m "don\'t run `rm -rf %s` here, it\'s done"' % out
    assert not _allowed(cmd, root)


def test_single_quotes_in_an_unquoted_heredoc_do_not_hide_an_expansion(dirs):
    root, out = dirs
    cmd = "cat > notes.txt <<EOF\n'$(rm -rf %s)'\nEOF" % out
    assert not _allowed(cmd, root)


def test_escaped_double_quote_keeps_the_double_quoted_state(dirs):
    root, out = dirs
    cmd = 'git commit -m "a \\" \' `rm -rf %s` \'"' % out
    assert not _allowed(cmd, root)


def test_dollar_paren_in_double_quotes_still_denied(dirs):
    root, _out = dirs
    assert not _allowed('echo "$(rm -rf /home/x)"', root)


def test_backtick_in_a_real_single_quoted_message_stays_allowed(dirs):
    root, _out = dirs
    assert _allowed("git commit -m 'fix `rm` handling'", root)


def test_single_quoted_span_after_a_double_quoted_apostrophe_stays_allowed(dirs):
    root, _out = dirs
    assert _allowed("git commit -m \"it's\" -m 'a `rm` note'", root)


@pytest.mark.parametrize("text,want", [
    ("a 'b' c", "a '' c"),
    ("\"it's\" 'x'", "\"it's\" ''"),
    ("\\'x 'y'", "\\'x ''"),
    ("'open", "'open"),
    ("\"a \\\" 'b' \"", "\"a \\\" 'b' \""),
    ("$'a\\'b' `x`", "$'a\\'b' `x`"),
])
def test_strip_single_quoted_spans(text, want):
    assert strip_single_quoted(text) == want
