"""angle_tree — one private `git archive` copy of the reviewed head per review angle.

design: pr-iterate-angle-isolation

Why: review angles run side by side. If they share the worktree, one angle's
mutation, test run or `__pycache__` corrupts a sibling's measurement. `prepare`
gives each angle `<exec_dir>/tree`, a tracked-files-only copy of the reviewed
commit, and `note` tells the angle to work only there. Fail-open: when the head
is not a commit or the archive fails, the angle gets no copy and the note tells
it to make one itself. Stdlib only; `task_scope._git_env` is the shipped git-env
scrub (`git_env` is dev-only and never ships).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import task_scope  # noqa: E402 — stdlib-only sibling: the shipped git-env scrub

_RULES = (
    "Run tests, mutations and repros only inside that copy; never edit, run a mutating "
    "command in, or run a suite from the shared worktree. The copy holds the head's "
    "tracked tree only: a file missing from it (untracked or generated) is not a finding. "
    "Before each run `export PYTHONDONTWRITEBYTECODE=1` and run python -B so no "
    "bytecode cache appears (the copy starts with none; the delete guards refuse deletes "
    "here, so never try to clear one). Never set GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_COMMON_DIR, "
    "GIT_OBJECT_DIRECTORY or GIT_CONFIG*; to test an env hypothesis, `git init` inside "
    "the copy.\n")


def head_commit(repo, head) -> str | None:
    """The commit `head` names in `repo`, or None (any failure, never raises)."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
                            f"{head}^{{commit}}"], capture_output=True, text=True,
                           env=task_scope._git_env(), check=False, timeout=60)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def _plain_members(tf):
    for m in tf:
        parts = Path(m.name).parts
        if (m.isfile() or m.isdir()) and not Path(m.name).is_absolute() and ".." not in parts:
            yield m


def make_tree(repo, rev, exec_dir) -> str | None:
    """Extract `git archive rev` into `<exec_dir>/tree` → that path, or None (fail-open)."""
    tree = Path(exec_dir) / "tree"
    proc = None
    try:
        proc = subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", rev],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=task_scope._git_env())
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tree, filter="data")
            else:  # older Python: keep plain files and dirs inside the tree only
                tf.extractall(tree, members=_plain_members(tf))
        if proc.wait(timeout=60) != 0:
            raise RuntimeError(f"git archive exited {proc.returncode}")
    except Exception as exc:  # noqa: BLE001 — a missing copy never fails the round
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        shutil.rmtree(tree, ignore_errors=True)
        why = " ".join(f"{type(exc).__name__}: {exc}".split())
        print(f"angle tree not made {exec_dir}: {why}", file=sys.stderr)
        return None
    return str(tree)


def note(exec_dir, tree_dir) -> str:
    """The prompt paragraph that sends the angle to its private copy."""
    if tree_dir:
        where = f"Your private copy of the reviewed head is `{tree_dir}`. "
    else:
        where = (f"No private copy was made. Make your own from the repo checkout first: "
                 f"`mkdir -p {exec_dir}/tree && git archive REV | tar -x -C {exec_dir}/tree`, "
                 f"where REV is the head named above. ")
    return "\n" + where + _RULES
