"""test_child_prompt_corpus.py — a child spawn's prompt file is always inside the tree it works in.

design: child-spawn-isolated-ladder-write (task 1.3)

An isolated ``--local`` dispatcher (a worktree-isolated ``tp-worker``) cannot Write outside its own
tree: the harness refuses the path. So every ``child_spawn.py start --prompt-file`` the docs tell an
agent to prepare names a path inside the tree its ``--cwd`` points at — a relative scratch path, the
per-attempt path ``task_verify.py open`` prints, or the protocol doc's generic file placeholder — and
never the ladder dir under the git common dir.

Parsed structure only: commands are extracted the way ``test_local_dispatch_literal`` extracts them
(fenced shell lines plus whitespace-normalized inline code spans, fences removed) and the rule runs on
the parsed operand. No doc wording is pinned (``skills/_shared/test-fragility.md``); the
``<child_prompt>`` placeholder is accepted only because the attempt-open CLI really prints that key —
proved by running it in a ``make_seat`` fixture, not by reading a doc. Real tmp repos only (M23).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from attempt_fixture import DD, IDENTITY, git, make_seat  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402

CORPUS = ("local-dispatch.md", "child-spawn.md", "cheap-dispatch.md", "strata-spawn.md")
TASK_VERIFY = str(HERE / "task_verify.py")
TASK_ID = "1.3"

# An operand passes when it is relative scratch, the protocol doc's generic file placeholder, or the
# per-attempt placeholder `open` prints (proved by test_open_prints_the_child_prompt_key).
RELATIVE_SCRATCH = re.compile(r"\.tp-scratch/(?:\S*/)*[\w.<>{}-]+\.md\Z")
GENERIC_PLACEHOLDER = "<file>"
OPEN_PLACEHOLDER = "<child_prompt>"


def docs() -> dict[str, str]:
    return {name: (HERE / name).read_text(encoding="utf-8") for name in CORPUS}


def documented_commands(doc: str) -> list[str]:
    """Each fenced ``bash``/``sh``/untagged line naming a helper, plus every inline code span with
    the fences removed first (so a span may cross a newline), whitespace-normalized."""
    cmds = []
    for lang, body in re.findall(r"```(\w*)\n(.*?)```", doc, re.S):
        if lang in ("bash", "sh", ""):
            cmds += [" ".join(ln.split()) for ln in body.splitlines() if ".py" in ln]
    prose = re.sub(r"```.*?```", "", doc, flags=re.S)
    cmds += [" ".join(s.split()) for s in re.findall(r"`([^`]+)`", prose)]
    return cmds


def prompt_file_operands(doc: str) -> list[str]:
    """Every ``--prompt-file`` operand parsed out of one doc's commands."""
    out = []
    for cmd in documented_commands(doc):
        out += re.findall(r"--prompt-file (\S+)", cmd)
    return out


def spans(doc: str) -> list[str]:
    """Every inline code span, fences removed, whitespace-normalized."""
    prose = re.sub(r"```.*?```", "", doc, flags=re.S)
    return [" ".join(s.split()) for s in re.findall(r"`([^`]+)`", prose)]


def open_json(wt: Path) -> dict:
    """One ``task_verify.py open`` in the fixture worktree ``wt`` -> the JSON it prints."""
    proc = subprocess.run([sys.executable, TASK_VERIFY, "open", "--task", TASK_ID,
                           "--design-dir", DD, "--root", str(wt)], cwd=str(wt),
                          capture_output=True, text=True, env=clean_git_env(**IDENTITY),
                          timeout=300)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def common_dir(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()


def test_open_prints_the_child_prompt_key(tmp_path: Path) -> None:
    """The `<child_prompt>` placeholder names a key the attempt-open CLI really prints, in-tree."""
    _seat, wt = make_seat(tmp_path)
    att = open_json(wt)
    assert "child_prompt" in att, att
    printed = Path(att["child_prompt"])
    assert printed.is_relative_to(Path(att["attempt_dir"]).resolve())
    assert not printed.is_relative_to(common_dir(wt))


def test_prompt_file_operands_stay_in_tree(tmp_path: Path) -> None:
    """Every documented `--prompt-file` operand is an in-tree path, never one under the ladder dir."""
    operands = {name: prompt_file_operands(text) for name, text in docs().items()}
    found = [op for ops in operands.values() for op in ops]
    assert len(found) >= 4, operands
    assert all(ops for name, ops in operands.items()), operands

    _seat, wt = make_seat(tmp_path)
    att = open_json(wt)
    assert "child_prompt" in att, att
    adir = Path(att["attempt_dir"]).resolve()
    common = common_dir(wt)

    for name, ops in operands.items():
        for op in ops:
            if op in (OPEN_PLACEHOLDER, GENERIC_PLACEHOLDER):
                continue  # the key `open` printed (asserted above) / the protocol's generic file
            assert RELATIVE_SCRATCH.match(op), (name, op)
            assert not op.startswith("/"), (name, op)
            resolved = (adir / op).resolve()
            assert resolved.is_relative_to(adir), (name, op)
            assert not resolved.is_relative_to(common), (name, op)


def test_no_path_under_ladder_dir() -> None:
    """No code span in the corpus is a path rooted at the ladder dir an agent cannot Write into."""
    rooted = {name: [s for s in spans(text) if s.startswith("<L>/")] for name, text in docs().items()}
    assert {n: v for n, v in rooted.items() if v} == {}
