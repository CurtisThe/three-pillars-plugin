"""Tests for allowlist_normalize: a Bash command becomes per-subcommand prefixes."""
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from allowlist_normalize import normalize  # noqa: E402


def p(c):
    return [(s.prefix, s.kind) for s in normalize(c)]


def test_framework_script_relative_to_skills():
    want = [("python3 skills/_shared/ruling_cli.py", "rule")]
    assert p('python3 "$TP_ROOT"/skills/_shared/ruling_cli.py show x') == want
    assert p("python3 /home/u/.claude/plugins/cache/tp/skills/_shared/ruling_cli.py") == want
    assert p("python3 skills/_shared/ruling_cli.py") == want


def test_compound_split():
    assert p("git status && gh pr view 3 --json state | head -5; ls") == [
        ("git status", "rule"), ("gh pr view", "rule"), ("head", "rule"), ("ls", "rule")]


def test_wrappers_stripped():
    assert p("timeout 60 python3 skills/_shared/x.py") == [("python3 skills/_shared/x.py", "rule")]
    assert p("nohup git fetch -q origin") == [("git fetch", "rule")]


def test_env_prefix_not_coverable():
    c = 'TP_LOCAL_MODE=wait python3 "$TP_ROOT"/skills/_shared/launch_design_run.py x'
    assert p(c) == [("python3 skills/_shared/launch_design_run.py", "env-prefixed")]


def test_git_c_exact_prefix():
    subs = normalize("git -C /home/u/r-wt/x worktree list")
    assert [(s.prefix, s.kind) for s in subs] == [("git -C worktree list", "git-C")]
    for f, v in asdict(subs[0]).items():
        if f != "argv":
            assert "/home/u/r-wt/x" not in str(v)


def test_unparseable():
    assert p('echo "unterminated') == [("echo", "unparseable")]
    assert p('rm "unterminated') == [("rm", "unparseable")]


SUBSTITUTIONS = [
    "git status $(rm x)", "git status `rm x`", "git diff <(rm x)", "git status ${X}",
    "git diff >(rm x)",
    # not at the start of a word, or not in the first subcommand
    "git status a$(rm x)", "git status a`rm x`", "git diff a<(rm x)", "git diff a>(rm x)",
    "git status a${X}", 'git status "a $(rm x) b"', 'git status "a `rm x` b"', 'git status "a ${X} b"',
    "git status ok; git status $(rm x)", "git status ok && git status a`rm x`",
    "git status | git diff a<(rm x)", "git status\ngit status a${X}"]


def test_substitution_is_unparseable():
    # one testcase: a weakened check fails it once, naming the first command it let through
    for c in SUBSTITUTIONS:
        assert p(c) == [("git", "unparseable")], (c, p(c))


def test_heredoc_commit_is_one_unparseable():
    c = 'git commit -m "$(cat <<\'EOF\'\nfeat: x\nrm -rf y\nEOF\n)"'
    assert p(c) == [("git", "unparseable")]


def test_quoted_newline_stays_in_token():
    assert p('git commit -m "line one\nline two"') == [("git commit", "rule")]
    assert p("git status\ngit log") == [("git status", "rule"), ("git log", "rule")]


def test_wrapper_with_options_is_unparseable():
    assert p("timeout -k 5 60 rm -rf x") == [("timeout", "unparseable")]


@pytest.mark.parametrize("c,root", [
    ('python3 "$TP_ROOT"/skills/_shared/x.py', "tp-root-text"),
    ("python3 /home/u/.claude/plugins/cache/tp/skills/_shared/x.py", "absolute"),
    ("python3 skills/_shared/x.py", "relative"),
    ('python3 "$TP_SEAT_ROOT"/skills/_shared/x.py', "other-var"),
    ("git status", "none"),
])
def test_root_form_tagged(c, root):
    assert normalize(c)[0].root == root


def test_screen_reason_carried():
    reason = normalize("git push --force origin x")[0].screen
    assert isinstance(reason, str) and reason
    assert normalize("git status")[0].screen is None


def test_redirect_outside_roots_screened():
    assert normalize("git diff > /etc/x.diff", roots=("/r",))[0].screen == "write:outside-roots"
    assert normalize("git diff > /r/x.diff", roots=("/r",))[0].screen is None
    assert normalize("git diff > out.diff")[0].screen is None
    for c in ("git status 2>/dev/null", "git status 2>&1"):
        subs = normalize(c)
        assert [(s.prefix, s.kind) for s in subs] == [("git status", "rule")]
        assert subs[0].screen is None
