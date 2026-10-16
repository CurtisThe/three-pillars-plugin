"""Verb tables for reviewer_delete_guard: incidents, wrappers, find, git,
rsync/mv. Tests only feed strings; nothing is executed.
(framework-check invariant 3 bars literal temp paths under skills/, so incident
cases use a neutral root; the classifier has no temp-root special case, any path
outside scratch is refused the same way.)"""
import pytest

from reviewer_delete_guard import classify


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return str(path)


def _rows(prefix, cmds):
    return [pytest.param(c, id="%s-%d" % (prefix, n)) for n, c in enumerate(cmds)]


INCIDENTS = [
    pytest.param("rm -rf /x/claude-1000/tmp*", id="incident-claude-glob"),
    pytest.param("rm -rf /x/pytest-of-curtis/pytest-*", id="incident-pytest-glob"),
    pytest.param("find /x/pytest-of-curtis -mindepth 1 -delete", id="incident-find-delete"),
    pytest.param("find /tmp -delete", id="incident-find-tmp"),
    pytest.param("find /tmp -name x -exec rm -rf {} +", id="incident-find-exec"),
    pytest.param("rmdir /x/y", id="incident-rmdir"),
    pytest.param("unlink /x/y", id="incident-unlink"),
    pytest.param("shred -u /x/y", id="incident-shred"),
]

XARGS = [
    pytest.param("find /x/pytest-of-curtis -name 'pytest-*' -print0 | xargs -0 rm -rf",
                 id="xargs-idiom"),
    pytest.param("find <S> -print0 | xargs -0 rm -rf", id="xargs-rule-s"),
    pytest.param("parallel rm ::: a", id="wrap-parallel"),
    pytest.param("/bin/rm -rf /x", id="wrap-abs-rm"),
    pytest.param("/usr/bin/git clean -fdx", id="wrap-abs-git"),
    pytest.param("\\rm /x", id="wrap-backslash"),
    pytest.param("'rm' /x", id="wrap-quoted"),
    pytest.param("timeout -s KILL 5 rm /x", id="wrap-timeout"),
    pytest.param("nice -n 5 rm /x", id="wrap-nice"),
    pytest.param("sudo -u root rm /x", id="wrap-sudo"),
    pytest.param("env -u HOME rm /x", id="wrap-env"),
    pytest.param("stdbuf -o0 rm /x", id="wrap-stdbuf"),
    pytest.param("ionice -c 3 rm /x", id="wrap-ionice"),
    pytest.param("xargs -I{} rm {}", id="wrap-xargs-I"),
    pytest.param("xargs -n 1 rm", id="wrap-xargs-n"),
    pytest.param("exec rm /x", id="wrap-exec"),
    pytest.param("command rm /x", id="wrap-command"),
    pytest.param("time -p rm /x", id="wrap-time"),
    pytest.param("busybox rm -rf /x", id="wrap-busybox"),
    pytest.param("toybox rm /x", id="wrap-toybox"),
    pytest.param("env A=1 rm /x", id="assign-after-env"),
    pytest.param("sudo A=1 rm /x", id="assign-after-sudo"),
]

FIND = [
    pytest.param("find /x/pytest-of-curtis -maxdepth 1 -name 'pytest-*' -exec du -sh {} \\; -delete",
                 id="find-exec-terminator"),
    pytest.param("find /tmp -exec echo {} \\; -exec rm -rf {} +", id="find-exec-terminator-2"),
    pytest.param("find -L /x/claude-1000 -name 'tmp*' -delete", id="find-L"),
    pytest.param("find -L <S>/sub -delete", id="find-L-scratch"),
    pytest.param("find -H /x -delete", id="find-H"),
    pytest.param("find -D tree /x -delete", id="find-D"),
    pytest.param("find -O3 /x -delete", id="find-O"),
    pytest.param("find /x -exec sh -c 'rm \"$1\"' _ {} \\;", id="find-exec-shell"),
    pytest.param("find <S> -files0-from l -delete", id="find-files0"),
    pytest.param("find <S> -follow -delete", id="find-follow"),
    pytest.param("find <S>/sub -exec rm -rf /outside \\;", id="find-exec-verb-outside"),
    pytest.param("find <S>/sub -exec git clean -fdx \\;", id="find-exec-git-clean"),
    pytest.param("find <S>/sub -execdir rm -rf ../../.. \\;", id="find-execdir-relative"),
    pytest.param("find <S>/sub -ok mv {} /outside \\;", id="find-ok-mv-outside"),
    pytest.param("find <S>/sub -exec sh -c 'rm -rf /outside' \\;", id="find-exec-shell-outside"),
    pytest.param("find <S>/sub -exec env rm -rf /outside +", id="find-exec-wrapper-outside"),
]

NO_TARGET = [pytest.param(c, id="rule-z-%d" % n) for n, c in enumerate(["rm", "rm -rf", "xargs rm"])]

GIT = [
    "git clean -fdx", "git reset --hard", "git -C /x reset --hard HEAD~1",
    "git checkout -- a.py", "git checkout a.py", "git checkout -f main", "git checkout main",
    "git switch -f main", "git restore a.py", "git rm a.py", "git rm --cached a.py",
    "git worktree remove ../wt", "git branch -D tp/x", "git push origin --delete tp/x",
    "git push origin :tp/x", "git stash", "git stash pop", "git stash push -m x",
    "git stash drop", "git stash clear", "git --git-dir=/x/.git clean -fd",
    "git push --prune origin", "git push --mirror origin", "git push origin +:tp/x",
    "git --attr-source X clean -fdx",
    "git checkout --detach -f x", "git checkout --detach x -- f", "git checkout x",
    "git checkout -- f", "git checkout --detach x y", "git checkout --detach -B b x",
    "git checkout --detach --ours x", "git checkout --detach -p x", "git checkout --force --detach x",
    "arr[$(rm -rf /x)]=1", "a[0]=1 rm -rf /x",
]

RSYNC_MV = [
    "rsync -a --delete /a/ /b/", "rsync -a --delete-after /a/ /b/",
    "rsync --remove-source-files /a /b", "mv -t /x a", "mv --target-directory=/x a",
]


@pytest.mark.parametrize("cmd", INCIDENTS + XARGS + FIND + NO_TARGET)
def test_refused(cmd, scratch):
    verdict = classify(cmd.replace("<S>", scratch), scratch=scratch, cwd=scratch)
    assert not verdict.allowed


@pytest.mark.parametrize("cmd", _rows("git", GIT) + _rows("rsync-mv", RSYNC_MV))
def test_refused_even_with_scratch_cwd(cmd, scratch):
    assert not classify(cmd, scratch=scratch, cwd=scratch).allowed


def test_find_without_start_uses_cwd(scratch, tmp_path):
    other = str(tmp_path / "other")
    for cmd in ("find -delete", "find . -delete"):
        assert not classify(cmd, scratch=scratch, cwd=other).allowed


@pytest.mark.parametrize("cmd, needle", [
    ("git clean -fdx", "git clean"),
    ("rm /x/y", "rm outside scratch"),
    ("find <S> -print0 | xargs -0 rm -rf", "operands from stdin"),
    ("rm", "no provable target"),
    ("rm $(cat l)", "unparseable"),
    ("git reset --hard", "git reset --hard"),
    ("git stash", "git stash"),
])
def test_reason_names_form(cmd, needle, scratch):
    verdict = classify(cmd.replace("<S>", scratch), scratch=scratch, cwd=scratch)
    assert not verdict.allowed
    assert needle in verdict.reason


ALLOWED = [
    "pytest -q", "python3 -m pytest x", "git diff a...b", "git log --oneline", "git status",
    "git clean -n", "git stash list", "git stash show -p", "grep -rn rm skills/",
    'echo "rm -rf /"', "find . -name '*.py'", "rsync -a /a/ /b/", "rm --help",
    "command -v rm", "which rm", "git switch main", "git branch --list",
    "find /x -name a -exec du -sh {} \\;", "git -C /x log -1",
    "git checkout --detach origin/candidate/x/single", "git checkout -q --detach origin/x",
    "git checkout --quiet --detach origin/x", "git switch --detach origin/x",
    # Slot 8 Step 1 regression checkout (tp-run-full-design SKILL.md): a symbolic branch,
    # since base_sync fixtures need `git symbolic-ref HEAD`; plus array-element assignment.
    "git switch -C regress/s origin/candidate/s/single", "arr[0]=1; echo ok", "m[k]=v",
]


@pytest.mark.parametrize("cmd", [
    "find <S>/sub -exec rm -rf {} +", "find <S>/sub -execdir rm {} \\;",
    "find <S>/sub -name a -exec grep x {} +", "find /x -exec grep x {} +",
    "git push origin main:main",
])
def test_allowed_in_scratch(cmd, scratch):
    verdict = classify(cmd.replace("<S>", scratch), scratch=scratch, cwd=scratch)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd", _rows("ok", ALLOWED))
def test_allowed(cmd, scratch):
    verdict = classify(cmd, scratch=scratch, cwd=scratch)
    assert verdict.allowed, verdict.reason
