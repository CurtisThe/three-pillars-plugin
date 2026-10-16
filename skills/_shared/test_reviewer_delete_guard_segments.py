"""Shell layer and composition for reviewer_delete_guard: separators, heredocs,
recursion, Rule U and Rule C. Tests only feed strings; nothing is executed.
(framework-check invariant 3 bars literal temp paths under skills/, so incident
cases use a neutral root; the classifier has no temp-root special case, any path
outside scratch is refused the same way.)"""
import pytest

from reviewer_delete_guard import classify
from reviewer_delete_shell import segments


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return str(path)


SEPARATORS = [
    pytest.param("true && rm -rf /x", id="sep-and"),
    pytest.param("ls; rm /x", id="sep-semi"),
    pytest.param("nohup rm /x &", id="sep-nohup-bg"),
    pytest.param("ls\nrm /x", id="sep-newline"),
    pytest.param("( rm -rf /x )", id="sep-subshell"),
    pytest.param("{ rm -rf /x; }", id="sep-brace"),
    pytest.param("! rm /x", id="sep-bang"),
    pytest.param("if true; then rm /x; fi", id="sep-if"),
    pytest.param("for f in a; do rm /x; done", id="sep-for"),
    pytest.param("case a in a) rm /x;; esac", id="sep-case"),
    # plan wrote "ls \\\nrm /x", which bash joins to `ls rm /x` (harmless); a
    # faithful classifier allows that, so the continuation case adds a real `&&`.
    pytest.param("ls \\\n&& rm /x", id="sep-continuation"),
    pytest.param("echo PR#194 tidy; rm -rf /x/claude-1000/tmp*", id="hash-midword"),
    pytest.param("find /x -name a ';' -delete", id="quoted-semi"),
    pytest.param("find /x \\( -name a \\) -delete", id="escaped-parens"),
    pytest.param("rm /x/ok ';' /x/other", id="quoted-semi-operand"),
    pytest.param("echo 'x';'rm' -rf /x/claude-1000/tmp*", id="quote-pair-semi"),
    pytest.param('echo "a"&&"rm" -rf /x', id="quote-pair-and"),
    pytest.param("echo a\\\\;rm -rf /x", id="escaped-backslash-semi"),
    pytest.param("echo a\\\\|rm -rf /x", id="escaped-backslash-pipe"),
    pytest.param("function f { rm -rf /x; }; f", id="kw-function"),
    pytest.param("function f() { rm -rf /x; }; f", id="kw-function-parens"),
    pytest.param("coproc rm -rf /x", id="kw-coproc"),
    pytest.param("coproc N { rm -rf /x; }", id="kw-coproc-named"),
    pytest.param("/bin/[r]m -rf /x", id="verb-bracket-glob"),
]

HEREDOCS = [
    pytest.param("bash <<'EOF'\nrm -rf /x\nEOF", id="heredoc-shell"),
    pytest.param('sh <<< "rm -rf /x"', id="herestring-shell"),
    pytest.param("cat <<EOF\n$(rm -rf /x)\nEOF", id="heredoc-unquoted-expands"),
    pytest.param("cat <<'EOF'\nx\nEOF\nrm -rf /x", id="heredoc-after-terminator"),
]

# `#` comments: a quote, `<<WORD` or trailing backslash inside one is inert in bash
COMMENTS = [
    pytest.param("# clean the scratch's leftovers\nrm -rf /x/claude-1000/tmp*\nls  # check it's gone",
                 id="comment-apostrophes"),
    pytest.param("ls  # reply goes out later via cat <<EOF\nrm -rf /x/claude-1000/tmp*",
                 id="comment-heredoc-op"),
    pytest.param("# drop stale dirs \\\nrm -rf /x/claude-1000/tmp*", id="comment-backslash"),
    pytest.param("ls \\\n# note \\\nrm -rf /x", id="comment-after-continuation"),
    pytest.param("echo '# quoted'; rm -rf /x", id="comment-quoted-hash"),
]

RECURSION = [
    pytest.param('bash -c "rm -rf /x"', id="rec-bash-c"),
    pytest.param("sh -c 'cd /x; rm y'", id="rec-sh-c-cd"),
    pytest.param("echo 'rm -rf /x' | sh", id="rec-stdin-shell"),
    pytest.param("bash -c 'bash -c \"bash -c \\\"bash -c true\\\"\"'", id="rec-depth-four"),
]

RULE_U = [
    pytest.param("rm $(cat list)", id="u-subst"),
    pytest.param("rm `cat list`", id="u-backtick"),
    pytest.param('eval "rm -rf /x"', id="u-eval"),
    pytest.param("echo 'rm -rf /x", id="u-unbalanced"),
    pytest.param('env -S "rm -rf /x"', id="u-env-S"),
    pytest.param("watch rm /x", id="u-watch"),
    pytest.param("sudo --bogus-opt rm /x", id="u-wrapper-option"),
    pytest.param("echo $(date); rm -rf x", id="u-expansion-destructive"),
]

CD = [
    pytest.param("cd /x/claude-1000 && rm -rf tmp*", id="cd-and"),
    pytest.param("cd /x/claude-1000; find . -delete", id="cd-find"),
    pytest.param("pushd /x && rm y", id="cd-pushd"),
    pytest.param("cd /x || rm y", id="cd-or"),
    pytest.param("env -C /tmp rm -rf x", id="cd-env-C"),
    pytest.param('bash -c "cd /x; rm y"', id="cd-nested"),
]


# Containment is *strictly* inside scratch: the dir itself, a sibling sharing its
# prefix, and a `..` back out are all outside.
BOUNDARY = [
    pytest.param("rm -rf <S>", id="boundary-self"),
    pytest.param("rm -rf <S>-x", id="boundary-sibling-prefix"),
    pytest.param("rm -rf <S>/..", id="boundary-dotdot"),
    pytest.param("rmdir <S>", id="boundary-rmdir-self"),
]


@pytest.mark.parametrize("cmd", SEPARATORS + HEREDOCS + COMMENTS + RECURSION + RULE_U + CD + BOUNDARY)
def test_refused(cmd, scratch):
    cmd = cmd.replace("<S>", scratch)
    verdict = classify(cmd, scratch=scratch, cwd=scratch)
    assert not verdict.allowed, f"guard let a destructive command through: {cmd!r}"


def test_unparseable_reason(scratch):
    assert "unparseable" in classify("echo 'rm", scratch=scratch, cwd=scratch).reason
    assert "unparseable" in classify("rm $(cat l)", scratch=scratch, cwd=scratch).reason


ALLOWED = [
    pytest.param("cat > <S>/reply.md <<'EOF'\nrm -rf /x/claude-1000/tmp*\nEOF", id="heredoc-reply"),
    pytest.param('cat > <S>/reply.md <<"EOF"\nrm -rf /x\nEOF', id="heredoc-reply-dq"),
    pytest.param("cat > <S>/r.md <<-EOF\n\tplain body\n\tEOF", id="heredoc-dash"),
    pytest.param("echo PR#194 tidy", id="hash-echo"),
    pytest.param("ls  # note", id="trailing-comment"),
    pytest.param("rm -rf <S>/x  # not /elsewhere", id="comment-not-operand"),
    pytest.param("cat $(git ls-files | head -1)", id="subst-no-destructive"),
    pytest.param("git diff $(git merge-base a b)", id="subst-git"),
    pytest.param("cd <S> && rm -rf <S>/x", id="cd-absolute-operand"),
    pytest.param("ls 2>&1 | head", id="fd-redirect"),
    pytest.param("[ -f x ] && echo ok", id="test-bracket"),
    pytest.param("echo ';'", id="quoted-semi-echo"),
    pytest.param("echo a\\;b", id="escaped-semi-word"),
    pytest.param("echo 'a;b' \"c&&d\"", id="quoted-punct-inside-word"),
    pytest.param("function f { ls; }", id="kw-function-benign"),
    pytest.param("[[ -f x ]] && echo ok", id="test-double-bracket"),
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd, scratch):
    verdict = classify(cmd.replace("<S>", scratch), scratch=scratch, cwd=scratch)
    assert verdict.allowed, verdict.reason


def test_segments_split_and_comment_not_stripped():
    segs = segments("echo PR#194 tidy; rm x")
    assert [s.argv for s in segs] == [["echo", "PR#194", "tidy"], ["rm", "x"]]


def test_segments_drops_redirect():
    assert segments("rm -rf x >/dev/null")[0].argv == ["rm", "-rf", "x"]
    assert segments("rm -rf x 2>&1")[0].argv == ["rm", "-rf", "x"]


def test_segments_heredoc_flag():
    seg = segments("cat <<'EOF'\nbody\nEOF")[0]
    assert seg.argv == ["cat"]
    assert len(seg.heredocs) == 1
    assert tuple(seg.heredocs[0]) == ("body\n", True)
    assert segments("cat <<EOF\nbody\nEOF")[0].heredocs[0].quoted is False
