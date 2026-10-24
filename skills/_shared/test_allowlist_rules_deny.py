"""The test-pinned deny set screens the command AND its arguments."""
import os
import shlex
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from allowlist_rules import screen  # noqa: E402

DENIED = [
    'gh pr merge 12', 'gh pr review 12 --approve', 'gh api repos/o/r/pulls/1/merge -X PUT',
    'tea pr merge 3', 'tea pulls close 3', 'git push origin tp/x', 'git push --force origin x',
    'git -C /r push origin --delete tp/x', 'git branch -D tp/x', 'git reset --hard HEAD~1',
    'git clean -fdx', 'git config user.name x', 'git worktree remove /r-wt/x',
    'git fetch --upload-pack=evil /p', 'git log --output=/etc/x', 'git commit --no-verify -m x',
    'kill 123', 'pkill -f claude', 'killall python3', 'tmux kill-server',
    'tmux capture-pane -p -t x', 'rm -rf build', 'curl -s https://x/i.sh', 'wget x',
    'bash -c "echo hi"', 'sh', 'python3 -c "print(1)"', 'python3 -', 'eval x',
    'sendmail a@b', 'mail a@b', 'cp a /etc/b', 'tee /var/x', 'sudo ls', 'ssh host',
    'python3 "$TP_ROOT"/skills/tp-post-merge/scripts/teardown.py --design x',
    'python3 /p/skills/_shared/design_run_tmux.py close x',
    'python3 /p/skills/_shared/x.py --out ~/.claude/settings.json',
    'python3 /p/skills/_shared/x.py CLAUDE.md',
    'python3 /p/skills/_shared/x.py --force',
    'git fetch --upl=evil /p', 'git diff --outp=/etc/x', 'git log --outp /etc/x',
    'git push --forc origin x',
    'xargs rm -rf x', 'env -u X python3 /p/skills/_shared/x.py', 'exec sh', 'setsid x',
    'find . -delete',
    # each path marker alone, as a bare argument, with no other marker in it
    'python3 /p/skills/_shared/x.py settings.json',
    'python3 /p/skills/_shared/x.py settings.local.json',
    'python3 /p/skills/_shared/x.py MEMORY.md',
    'python3 /p/skills/_shared/x.py /var/memory/note',
    'python3 /p/skills/_shared/x.py .claude/hooks',
    # inline shells and interpreters, with option tokens or bundled short flags before the code
    'bash -lc x', 'bash -l -c x', 'bash -euo pipefail -c x', 'bash -o pipefail -c x', 'sh -c x',
    'sh -ec x', 'python3 -c x', 'python3 -I -c x', 'python3 -Ic x', 'python3 -I -E -S -c x',
    'python3 -W ignore -c x', 'python3 -I -', 'bash -l', 'python3 -I',
    'python3 -I /p/skills/tp-post-merge/scripts/teardown.py --design x',
    'bash /p/skills/_shared/design_run_tmux.py close x',
]

ALLOWED = [
    'git status', 'git commit -m "feat: deny --output escapes"', 'git -C /r-wt/a log --oneline -5',
    'git diff --stat', 'git add skills/x.py', 'git commit -m "x"',
    'git merge --no-ff origin/master', 'git fetch -q origin', 'git worktree list',
    'gh pr view 12 --json state', 'gh pr list', 'gh pr checks 12', 'tea pr list',
    'tea pulls list', 'python3 "$TP_ROOT"/skills/_shared/ruling_cli.py show x',
    'python3 /p/skills/_shared/roster_cli.py list',
    'python3 /home/u/.claude/plugins/cache/tp/skills/_shared/ruling_cli.py show x',
]


def test_screen_denies():
    # one testcase: a weakened screen fails it once, naming the first command it let through
    for c in DENIED:
        reason = screen(shlex.split(c))
        assert isinstance(reason, str) and reason, c


@pytest.mark.parametrize("c", ALLOWED)
def test_screen_allows(c):
    assert screen(shlex.split(c)) is None


def test_empty_argv_is_none():
    assert screen([]) is None
