"""test_archive_allowlist_explainer.py — the archive prune keeps the explainer's files.

Task 10.4 of explainer-agent: `brief.md` (the PR brief the explainer drafted) and
`rulings.ndjson` (its auto-ruling ledger) are allowlisted like
`escape-ledger.ndjson`, so the step-6e2 prune keeps both even when nothing in the
repo names them.

Run with: python3 -m pytest skills/_shared/test_archive_allowlist_explainer.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from archive_allowlist import ALLOWLIST, apply, plan_prune

DD = "three-pillars-docs/completed-tp-designs/x"
EXPLAINER_FILES = ["brief.md", "rulings.ndjson"]


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c",
                    "user.email=f@t", *args], capture_output=True,
                   text=True, check=True, env=env)


def _archived_repo(root: Path) -> Path:
    """A committed archive dir holding the explainer's two files plus junk."""
    _git(root, "init", "-q", "-b", "master")
    d = root / DD
    d.mkdir(parents=True)
    (d / "design.md").write_text("d\n", encoding="utf-8")
    (d / "brief.md").write_text("# Why this change\n\nBecause.\n", encoding="utf-8")
    (d / "rulings.ndjson").write_text('{"q":"auto"}\n', encoding="utf-8")
    (d / "junk.txt").write_text("j\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "archive x")
    return root


def test_explainer_files_are_allowlisted():
    for name in EXPLAINER_FILES:
        assert name in ALLOWLIST


def test_plan_keeps_brief_and_rulings(tmp_path):
    root = _archived_repo(tmp_path)
    plan = plan_prune(DD, root)
    for name in EXPLAINER_FILES:
        assert f"{DD}/{name}" in plan.keep, name
        assert f"{DD}/{name}" not in plan.drop, name
    assert f"{DD}/junk.txt" in plan.drop


def test_apply_removes_junk_and_keeps_explainer_files(tmp_path):
    root = _archived_repo(tmp_path)
    apply(plan_prune(DD, root), root)
    for name in EXPLAINER_FILES:
        assert (root / DD / name).exists(), name
    assert not (root / DD / "junk.txt").exists()
