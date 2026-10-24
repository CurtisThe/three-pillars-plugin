"""The post-merge docs compile must not run code from an unreviewed origin/tp/docs-compile tip.

Tier 7 round-1 reproducer (PR #364, living-doc-fragments). docs_compile_publish checks out whatever
origin/tp/docs-compile holds into a scratch worktree of the operator's repo and commits there, so the
repo's installed pre-commit hook (the shape of this repo's local hook `entry: ./framework-check.sh`)
would run the BRANCH's copy of framework-check.sh. Oracle: example; the assertion reads a marker file.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_docs_compile import TWO, git  # noqa: E402
from test_docs_compile_publish import BRANCH, Forge, publish, with_origin  # noqa: E402


def test_compile_does_not_execute_branch_hook_code(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    benign = root / "framework-check.sh"
    benign.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    benign.chmod(0o755)
    git(root, "add", "framework-check.sh")
    git(root, "commit", "-q", "-m", "benign framework-check")
    git(root, "push", "-q", "origin", "main")

    # A collaborator (push access to origin, no review) pushes the rolling compile branch.
    marker = tmp_path / "PWNED"
    evil = tmp_path / "evil"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(bare), str(evil)], check=True)
    git(evil, "config", "user.email", "x@example.com")
    git(evil, "config", "user.name", "x")
    git(evil, "checkout", "-q", "-b", BRANCH)
    script = evil / "framework-check.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    git(evil, "commit", "-q", "-am", "tweak")
    git(evil, "push", "-q", "origin", BRANCH)

    # The operator's repo has a pre-commit hook that runs the checked-out tree's ./framework-check.sh.
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\n[ -x ./framework-check.sh ] && exec ./framework-check.sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))

    publish(root, Forge(), prs=("alpha=1", "beta=2"))
    assert not marker.exists(), "the compile ran code from the unreviewed origin/tp/docs-compile tip"
