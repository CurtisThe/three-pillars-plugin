"""Tests: `reproduce.run_cli` merges only `merge_entries` (local-role-routing 6.6)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}
PASSING = {"kind": "command", "argv": [sys.executable, "-c", "print('fine')"],
           "expect": {"exit": 0, "stdout_contains": "fine"}}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env={**os.environ, **_ENV}, check=True).stdout.strip()


def _finding(summary, severity="high"):
    return {"file": f"src/{summary}.py", "line_range": [1, 1], "summary": summary, "class": "P",
            "severity": severity, "blocking": True, "reproducer": PASSING}


def _reply(*findings):
    return "```json\n" + json.dumps({"findings": list(findings)}) + "\n```\n"


def _round(tmp_path, entries):
    repo = tmp_path / "wt"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    head = _git(repo, "rev-parse", "HEAD")
    rd = tmp_path / "rd"
    angles = []
    for name, text, extra in entries:
        (rd / name).mkdir(parents=True)
        (rd / name / "reply.md").write_text(text, encoding="utf-8")
        angles.append({"name": name, "role": "finder", "model": "opus",
                       "reply_path": f"{name}/reply.md", **extra})
    manifest = {"round": 1, "paths": {"log_path": str(tmp_path / "log.md")}, "angles": angles}
    (rd / "angles.json").write_text(json.dumps(manifest), encoding="utf-8")
    return repo, head, rd


def _summaries(rd):
    data = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    return sorted(f.get("summary") for f in data if f.get("summary"))


def test_dropped_strata_finding_never_reaches_findings(tmp_path):
    repo, head, rd = _round(tmp_path, [
        ("security", _reply(_finding("strata-sec")), {"advisory": True, "model": "local"}),
        ("opus-check", _reply(_finding("kept-by-check")), {"role": "confirmer"}),
    ])
    reproduce.run_cli(rd, repo, head)
    assert _summaries(rd) == ["kept-by-check"]


def test_claude_only_round_merges_every_entry(tmp_path):
    repo, head, rd = _round(tmp_path, [
        ("a", _reply(_finding("one")), {}),
        ("b", _reply(_finding("two")), {}),
    ])
    reproduce.run_cli(rd, repo, head)
    assert _summaries(rd) == ["one", "two"]
