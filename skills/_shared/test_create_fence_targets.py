"""Create-target reader for the create fence (design run-scratch-in-fence, Task 1.4).

`shell_targets(command, cwd, env)` lists the literal paths a Bash command would
create and the targets it cannot prove; `python_targets(source)` does the same
for an inline Python body; `has_create_verb` is the cheap prefilter. Commands are
only parsed here; nothing is executed. Paths under /srv are illustrative and are
never touched (see skills/_shared/test-fragility.md: assert on returned values).
"""
import os

import pytest

import run_scratch
from create_fence_py import python_targets
from create_fence_targets import has_create_verb, shell_targets

CWD = "/srv/w"
ENV = {"HOME": "/home/u", "TMPDIR": "/srv/w/.tp-scratch/run"}


def _st(cmd, cwd=CWD, env=None):
    return shell_targets(cmd, cwd, dict(ENV if env is None else env))


def _has(paths, expected):
    return any(p == expected or p.startswith(expected + "/") for p in paths)


VERBS = [
    ("echo hi > f", "/srv/w/f"),
    ("echo hi >> f", "/srv/w/f"),
    ("make &> log", "/srv/w/log"),
    ("make 2> err", "/srv/w/err"),
    ("echo x | tee out", "/srv/w/out"),
    ("echo x | tee -a out", "/srv/w/out"),
    ("mkdir d", "/srv/w/d"),
    ("mkdir -p /srv/a/b", "/srv/a/b"),
    ("touch f", "/srv/w/f"),
    ("cp a /srv/dst", "/srv/dst"),
    ("mv a b /srv/dir", "/srv/dir"),
    ("install -m 644 a /srv/bin/a", "/srv/bin/a"),
    ("ln -s a /srv/link", "/srv/link"),
    ("rsync -a src/ /srv/mirror", "/srv/mirror"),
    ("cp -t /srv/tdir a b", "/srv/tdir"),
    ("mv --target-directory=/srv/tdir a", "/srv/tdir"),
    ("install -t /srv/tdir a", "/srv/tdir"),
    ("dd if=x of=/srv/img bs=1M", "/srv/img"),
    ("curl -o /srv/f https://h/x", "/srv/f"),
    ("curl --output /srv/f https://h/x", "/srv/f"),
    ("curl -sSL --output=/srv/f2 https://h/x", "/srv/f2"),
    ("wget -O /srv/f https://h/x", "/srv/f"),
    ("tar -x -C /srv/d -f a.tar", "/srv/d"),
    ("tar -xf a.tar -C /srv/d", "/srv/d"),
    ("unzip a.zip -d /srv/d", "/srv/d"),
    ("git clone https://h/r.git /srv/r", "/srv/r"),
    ("git worktree add /srv/wt", "/srv/wt"),
    ("git worktree add -b br /srv/wt2 HEAD", "/srv/wt2"),
    ("git init /srv/g", "/srv/g"),
    ("python3 -m venv /srv/venv", "/srv/venv"),
    ("pip install --target /srv/site pkg", "/srv/site"),
    ("pip install --target=/srv/site pkg", "/srv/site"),
    ("ssh-keygen -t ed25519 -f /srv/key", "/srv/key"),
    ("mktemp /srv/abs/XXXXXX", "/srv/abs/XXXXXX"),
    ("mktemp -p /srv/pdir", "/srv/pdir"),
    ("mktemp -d -p /srv/pdir", "/srv/pdir"),
]


@pytest.mark.parametrize("cmd,expected", VERBS)
def test_verb_table_yields_the_literal_target(cmd, expected):
    paths, _unprovable = _st(cmd)
    assert _has(paths, expected), "%r gave %r, wanted %r" % (cmd, paths, expected)


ASSIGN_NAMES = ["TMPDIR", "TMP", "TEMP"] + list(run_scratch.CACHE_VARS)


@pytest.mark.parametrize("name", ASSIGN_NAMES)
@pytest.mark.parametrize("form", ["{n}=/srv/t pytest -q", "export {n}=/srv/t",
                                  "env {n}=/srv/t pytest -q"])
def test_temp_and_cache_assignments_are_targets(name, form):
    paths, _ = _st(form.format(n=name))
    assert "/srv/t" in paths


def test_unrelated_assignment_is_not_a_target():
    assert _st("FOO=/srv/t pytest -q") == ([], [])


@pytest.mark.parametrize("cmd,expected", [
    ("touch ~/x", "/home/u/x"),
    ("touch $HOME/x", "/home/u/x"),
    ("touch ${HOME}/x", "/home/u/x"),
    ("touch $TMPDIR/x", "/srv/w/.tp-scratch/run/x"),
    ("touch rel/x", "/srv/w/rel/x"),
    ("echo a > ../up", "/srv/up"),
])
def test_home_tmpdir_and_relative_resolve_against_env_and_cwd(cmd, expected):
    paths, unprovable = _st(cmd)
    assert paths == [expected]
    assert unprovable == []


def test_literal_cd_moves_the_cwd_for_later_targets():
    tmp = os.path.join("/", "tmp")
    paths, _ = _st("cd %s && touch x" % tmp)
    assert paths == [os.path.join(tmp, "x")]


def test_relative_cd_then_redirect():
    paths, _ = _st("cd sub && echo a > f")
    assert paths == ["/srv/w/sub/f"]


def test_cd_to_an_expansion_makes_later_relative_targets_unprovable():
    paths, unprovable = _st('cd "$D" && touch x')
    assert paths == []
    assert unprovable


@pytest.mark.parametrize("cmd", ["touch $UNKNOWN/x", "echo a > ${NOPE}/f",
                                 "touch $(mktemp -u)", "touch `date`.log",
                                 'mkdir "$(pwd)/d"'])
def test_unknown_var_or_command_substitution_is_unprovable(cmd):
    paths, unprovable = _st(cmd)
    assert unprovable, "%r should be unprovable" % cmd
    assert not any("$" in p or "`" in p or "(" in p for p in paths)


def test_unknown_cwd_makes_a_relative_target_unprovable():
    paths, unprovable = shell_targets("touch x", None, dict(ENV))
    assert paths == []
    assert unprovable


@pytest.mark.parametrize("cmd,expected", [("echo a > /dev/null", "/dev/null"),
                                          ("make 2> /dev/stderr", "/dev/stderr")])
def test_dev_paths_are_returned_as_paths(cmd, expected):
    paths, _ = _st(cmd)
    assert expected in paths


@pytest.mark.parametrize("cmd", ['echo "a > b"', "echo 'a > b'", "printf '%s' 'x >> y'",
                                 "grep -n 'mkdir -p' f.md", "ls -la"])
def test_data_strings_and_single_quotes_yield_nothing(cmd):
    assert _st(cmd) == ([], [])


def test_stderr_dup_is_not_a_target():
    paths, unprovable = _st("make > out 2>&1")
    assert paths == ["/srv/w/out"]
    assert unprovable == []


def test_lexer_failure_is_unprovable():
    paths, unprovable = _st('echo "unterminated > f')
    assert paths == []
    assert unprovable


def test_nested_shell_string_is_read():
    paths, _ = _st("bash -c 'touch /srv/n'")
    assert "/srv/n" in paths


def test_inline_python_body_is_read():
    paths, _ = _st("python3 -c 'open(\"/srv/py\", \"w\")'")
    assert "/srv/py" in paths


@pytest.mark.parametrize("src,expected", [
    ('open("/srv/o", "w")', "/srv/o"),
    ('open("/srv/o", "a")', "/srv/o"),
    ('open("/srv/o", "x")', "/srv/o"),
    ('open("/srv/o", "wb")', "/srv/o"),
    ('open("/srv/o", mode="w")', "/srv/o"),
    ('from pathlib import Path\nPath("/srv/p").write_text("x")', "/srv/p"),
    ('from pathlib import Path\nPath("/srv/p").write_bytes(b"x")', "/srv/p"),
    ('from pathlib import Path\nPath("/srv/p").mkdir(parents=True)', "/srv/p"),
    ('import pathlib\npathlib.Path("/srv/p").touch()', "/srv/p"),
    ('from pathlib import Path\nq = Path("/srv/q")\nq.touch()', "/srv/q"),
    ('import os\nos.makedirs("/srv/m", exist_ok=True)', "/srv/m"),
    ('import os\nos.mkdir("/srv/m")', "/srv/m"),
])
def test_python_literal_create_targets(src, expected):
    paths, unprovable = python_targets(src)
    assert paths == [expected]
    assert unprovable == []


@pytest.mark.parametrize("src", ['open(name, "w")',
                                 'from pathlib import Path\nPath(f"{x}/y").touch()',
                                 'import os\nos.makedirs(base)'])
def test_python_non_literal_path_is_unprovable(src):
    paths, unprovable = python_targets(src)
    assert paths == []
    assert unprovable


@pytest.mark.parametrize("src", ['open("/srv/r")', 'open("/srv/r", "r")',
                                 'open("/srv/r", "rb")', 'print("open(\'/srv/x\', \'w\')")'])
def test_python_read_mode_and_data_yield_nothing(src):
    assert python_targets(src) == ([], [])


def test_python_syntax_error_is_unprovable():
    paths, unprovable = python_targets("open(")
    assert paths == []
    assert unprovable


@pytest.mark.parametrize("cmd", ["ls -la", "cat README.md", "pytest -q"])
def test_prefilter_false_for_plain_reads(cmd):
    assert has_create_verb(cmd) is False


@pytest.mark.parametrize("cmd", ["touch x", "echo a > f", "mkdir -p d",
                                 "TMPDIR=/srv/t pytest", "python3 -c 'open(1)'"])
def test_prefilter_true_for_create_commands(cmd):
    assert has_create_verb(cmd) is True
