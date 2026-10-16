"""test_trace_ignore_completed.py — an archived design's `.trace/` stays ignored.

Post-converge fix F3 of archive-slimming: `/tp-design-complete`'s `git mv`
carries a `--record` run's `.trace/` into `completed-tp-designs/{slug}/`, so the
repo's `.gitignore` must ignore it under both roots. Behaviour check: a fixture
repo using the repo's real `.trace/` ignore lines, asked with `git
check-ignore`. The `.gitignore` is the dev repo's own (dev-repo only).

Run with: python3 -m pytest skills/_shared/test_trace_ignore_completed.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (_ROOT / ".gitignore").is_file(),
    reason="uses the dev repo's own .gitignore (dev-repo only)")


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.mark.parametrize("path, ignored", [
    ("three-pillars-docs/completed-tp-designs/x/.trace/run-1/trace.jsonl", True),
    ("three-pillars-docs/tp-designs/x/.trace/run-1/trace.jsonl", True),
    ("three-pillars-docs/completed-tp-designs/x/design.md", False),
])
def test_trace_dirs_ignored_under_both_roots(tmp_path, path, ignored):
    rules = [line for line in (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
             if ".trace/" in line and not line.startswith("#")]
    assert rules, "the repo .gitignore carries no .trace/ rule"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_env())
    (tmp_path / ".gitignore").write_text("\n".join(rules) + "\n", encoding="utf-8")
    f = tmp_path / path
    f.parent.mkdir(parents=True)
    f.write_text("{}\n", encoding="utf-8")
    r = subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "-q", "--", path],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == (0 if ignored else 1), r.stderr
