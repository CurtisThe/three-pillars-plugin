"""Lexical pre-pass of reviewer_delete_guard (reviewer_delete_lex): escapes,
quote state, `#` comments, continuations and heredoc bodies. Every refused row
is a shape bash runs as a delete; each was checked with `echo` in place of
`rm`. Tests only feed strings; nothing is executed. (framework-check
invariant 3 bars literal temp paths under skills/, so cases use a neutral root.)"""
import pytest

from reviewer_delete_guard import classify
from reviewer_delete_lex import Unmodelled, cut_heredocs


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return str(path)


REFUSED = [
    # PR #200 round 2: an escaped or $'...'-quoted char is not a word boundary,
    # so the `#` stays inside the word and the rest of the line runs
    pytest.param("echo a\\ #; rm -rf /x", id="hash-after-escaped-space"),
    pytest.param("echo \\;#; rm -rf /x", id="hash-after-escaped-semi"),
    pytest.param("echo a\\\t#; rm -rf /x", id="hash-after-escaped-tab"),
    pytest.param("echo a\\|#; rm -rf /x", id="hash-after-escaped-pipe"),
    pytest.param("echo $'\\' #'; rm -rf /x", id="hash-in-ansi-c-escaped-quote"),
    pytest.param("echo $'\\'' ; rm -rf /x #'", id="ansi-c-escaped-quote-hides-rm"),
    # a line ending in an even run of backslashes is not continued
    pytest.param("echo foo\\\\\nrm -rf /x", id="even-backslashes-end-line"),
    pytest.param("echo a\\\\\\\\\nrm -rf /x/claude-1000/tmp*", id="four-backslashes-end-line"),
    # a quoted heredoc body gets no continuation: the terminator still ends it
    pytest.param("cat <<'EOF'\nx\\\nEOF\nrm -rf /x\n", id="quoted-heredoc-trailing-backslash"),
    pytest.param("cat > <S>/r.md <<'EOF'\ntext \\\nEOF\nrm -rf /x/claude-1000/tmp*",
                 id="quoted-heredoc-reply-trailing-backslash"),
    pytest.param('cat <<"EOF"\nx\\\nEOF\nrm -rf /x', id="dq-heredoc-trailing-backslash"),
    # an unquoted body pairs backslashes: `\\` is literal, the next line is the terminator
    pytest.param("cat <<EOF\nx\\\\\nEOF\nrm -rf /x", id="unquoted-heredoc-even-backslashes"),
    # fail closed where the body would otherwise swallow every later line
    pytest.param("cat <<EOF\nrm -rf /x", id="heredoc-unterminated"),
    pytest.param("cat <<$'EOF'\nbody\nEOF\nrm -rf /x", id="heredoc-ansi-c-delimiter"),
    pytest.param("echo $((1<<2))\nrm -rf /x", id="arith-shift-not-heredoc"),
    # comment boundaries the iter-1 mutants survived
    pytest.param("ls;# it's\nrm -rf /x\n# it's", id="comment-after-semi"),
    pytest.param("ls\t# it's\nrm -rf /x\n# it's", id="comment-after-tab"),
    pytest.param("ls|# it's\nrm -rf /x\n# it's", id="comment-after-pipe"),
    pytest.param("(# it's\nrm -rf /x\n)", id="comment-after-paren"),
    pytest.param("ls # a\\\n# it's\\\nrm -rf /x\n# it's", id="comment-run-backslashes"),
    # PR #200 round 3: a `#` inside an expansion, or right after the `)` / `}` /
    # backquote that closes one, is not a comment, so the rest of the line runs
    pytest.param("echo ${x:- #}; rm -rf /x", id="hash-in-param-expansion"),
    pytest.param("echo ${x// #/}; rm -rf /x", id="hash-in-param-substitution"),
    pytest.param("echo `echo a #`; rm -rf /x", id="hash-in-backquotes"),
    pytest.param('echo "`echo "a #"`"; rm -rf /x', id="hash-in-quoted-backquotes"),
    pytest.param("echo $(echo a)#; rm -rf /x", id="hash-after-subst"),
    pytest.param("echo $(( 1 ))#; rm -rf /x", id="hash-after-arith"),
    pytest.param("echo $((1+1))#; rm -rf /x", id="hash-after-arith-expr"),
    pytest.param("echo <(true)#; rm -rf /x", id="hash-after-procsub"),
    pytest.param("echo ${x}#; rm -rf /x", id="hash-after-brace"),
    pytest.param('echo "$(echo "a #")"; rm -rf /x', id="hash-in-quoted-subst"),
    pytest.param("echo $(echo a #\n); rm -rf /x", id="comment-in-subst-closes-later"),
    # a `)` in a case pattern does not close `$(`, so the `#` after `esac)` is a word char
    pytest.param("echo $(case x in a) echo;; esac)#; rm -rf /x", id="case-pattern-in-subst"),
    # PR #200 round 3.1: bash reads a pending heredoc body only after the line that
    # closes an open expansion, so a newline inside one must not start the body
    pytest.param("cat <<'E' $(echo\nrm -rf /x\nE\n)", id="heredoc-pending-newline-in-subst"),
    pytest.param("cat <<'E' <(echo\nrm -rf /x\nE\n)", id="heredoc-pending-newline-in-procsub"),
    pytest.param("cat <<'E' \"$(echo\nrm -rf /x\nE\n)\"", id="heredoc-pending-newline-in-quoted-subst"),
    pytest.param("cat <<'E' ${x:-\nrm -rf /x\nE\n}", id="heredoc-pending-newline-in-param"),
]


@pytest.mark.parametrize("cmd", REFUSED)
def test_refused(cmd, scratch):
    cmd = cmd.replace("<S>", scratch)
    assert not classify(cmd, scratch=scratch, cwd=scratch).allowed, cmd


ALLOWED = [
    pytest.param("echo a\\ #b", id="escaped-space-hash-word"),
    pytest.param("echo 'a' # it's fine", id="comment-after-quote-space"),
    pytest.param("echo $'tab\\there'", id="ansi-c-plain"),
    pytest.param("ls \\\n  -la", id="odd-backslash-continues"),
    pytest.param("cat > <S>/r.md <<'EOF'\nline \\\nEOF", id="quoted-heredoc-backslash-body"),
    pytest.param("cat > <S>/r.md <<EOF\na \\\nrm -rf /x\nEOF", id="unquoted-heredoc-continued-body"),
    pytest.param("echo ${#HOME}", id="param-length"),
    pytest.param("echo $((2#101))", id="arith-base-hash"),
    pytest.param("echo $(echo a)#b", id="hash-after-subst-word"),
    pytest.param('echo "$(echo "a #")"', id="quoted-hash-in-quoted-subst"),
    pytest.param("echo ${x:-y} # it's", id="comment-after-brace-space"),
    pytest.param("git diff $(git merge-base a b) # since base", id="comment-after-subst-space"),
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd, scratch):
    verdict = classify(cmd.replace("<S>", scratch), scratch=scratch, cwd=scratch)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd,text", [
    ("echo a\\ #b", "echo a\\ #b"),
    ("echo \\;#x", "echo \\;#x"),
    ("ls # c \\\nrm x", "ls \nrm x"),
    ("ls \\\n# c\nrm x", "ls \nrm x"),
    ("echo foo\\\\\nrm x", "echo foo\\\\\nrm x"),
    ("echo \"a\\\nb\"", "echo \"ab\""),
    ("echo $(echo a)#; rm x", "echo $(echo a)#; rm x"),
    ("echo ${x:-y} # c\nrm x", "echo ${x:-y} \nrm x"),
    ("echo \"$(echo \"a #\")\" # c", "echo \"$(echo \"a #\")\" "),
])
def test_cut_text(cmd, text):
    assert cut_heredocs(cmd)[0] == text


def test_quoted_body_keeps_backslash_lines():
    text, docs = cut_heredocs("cat <<'EOF'\nx\\\nEOF\nrm y")
    assert text == "cat << __TP_HD__ \nrm y"
    assert docs[0].body == "x\\\n" and docs[0].quoted


def test_unquoted_body_splices_odd_tail():
    text, docs = cut_heredocs("cat <<EOF\na\\\nEOF\nb\\\\\nEOF\nls")
    assert docs[0].body == "aEOF\nb\\\\\n" and text.endswith("\nls")


@pytest.mark.parametrize("cmd", ["cat <<EOF\nx", "cat <<EOF", "cat <<`x`\nx\n`x`",
                                 "echo $'a\\'b'", "cat <<EOF \"a\nb\"\nEOF",
                                 # inside an expansion: a word-start `#`, a `case`,
                                 # a stray or missing closer
                                 "echo $(ls # c)", "echo `ls # c`", "echo ${x:- #}",
                                 "echo $(case x in a) ;; esac)", "echo ${x:-)}",
                                 "echo $(ls", "echo `ls"])
def test_ambiguous_refused(cmd):
    with pytest.raises(Unmodelled):
        cut_heredocs(cmd)
