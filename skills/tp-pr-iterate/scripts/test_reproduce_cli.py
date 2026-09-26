"""Tests for the `reproduce.py --round-dir` CLI and its scoped clean check.

design: iterate-convergence-budget (Task 5.3, Q1)

The CLI refuses (exit 2) unless HEAD equals `--head` and tracked code is clean.
The loop's own bookkeeping — `.three-pillars/config.json` (a raised limit) and
`three-pillars-docs/**` (a flushed decisions.md) — and untracked files never
count as dirty. A reproducer that dirties tracked code fails the post-check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402

SCRIPT = Path(__file__).parent / "reproduce.py"
_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}
PASSING = {"kind": "command", "argv": [sys.executable, "-c", "print('fine')"],
           "expect": {"exit": 0, "stdout_contains": "fine"}}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return out.stdout.strip()


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _finding(summary, repro, file="src/a.py"):
    return {"file": file, "line_range": [1, 1], "summary": summary, "class": "P",
            "blocking": True, "reproducer": repro}


def _reply(findings):
    return "```json\n" + json.dumps(findings) + "\n```\n"


@pytest.fixture()
def setup(tmp_path):
    repo = tmp_path / "wt"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, ".three-pillars/config.json", "{}\n")
    _write(repo, "three-pillars-docs/tp-designs/d/decisions.md", "# log\n")
    _write(repo, "src/a.py", "a = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    head = _git(repo, "rev-parse", "HEAD")
    rd = tmp_path / "proof" / "rounds" / "pr1" / "r2"
    log = tmp_path / "proof" / "iterate-log.1.md"
    manifest = {"pr_url": "https://github.com/o/r/pull/1", "round": 2, "ordinal": "r2",
                "base": "BASE", "paths": {"proof_root": str(tmp_path / "proof"),
                                          "state_path": str(tmp_path / "proof" / "s.json"),
                                          "log_path": str(log)},
                "angles": []}

    def with_replies(*replies):
        manifest["angles"] = []
        for i, text in enumerate(replies):
            rp = rd / f"angle{i}" / "reply.md"
            _write(rp.parent, rp.name, text)
            manifest["angles"].append({"name": f"angle{i}", "role": "confirmer",
                                       "model": "opus", "tier": "claude",
                                       "reply_path": str(rp)})
        _write(rd, "angles.json", json.dumps(manifest))
        return rd

    return repo, head, with_replies, log


def _main(rd, repo, head, capsys):
    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head])
    return rc, capsys.readouterr().out


def test_head_mismatch_exit_2(setup, capsys):
    repo, head, with_replies, _ = setup
    rd = with_replies(_reply([]))
    rc, out = _main(rd, repo, "0" * 40, capsys)
    assert rc == 2 and "head-mismatch" in out


def test_dirty_tracked_code_exit_2(setup, capsys):
    repo, head, with_replies, _ = setup
    _write(repo, "src/a.py", "a = 2\n")
    rc, out = _main(with_replies(_reply([])), repo, head, capsys)
    assert rc == 2 and "dirty-tracked-code" in out


def test_config_edit_accepted(setup, capsys):
    """[Q1] a raised round_cap in the REAL config does not block the re-run."""
    repo, head, with_replies, _ = setup
    _write(repo, ".three-pillars/config.json", '{"pdw": {"guards": {"round_cap": 7}}}\n')
    rc, _ = _main(with_replies(_reply([])), repo, head, capsys)
    assert rc == 0


def test_design_docs_and_untracked_accepted(setup, capsys):
    repo, head, with_replies, _ = setup
    _write(repo, "three-pillars-docs/tp-designs/d/decisions.md", "# log\nflushed\n")
    _write(repo, "stray.txt", "untracked\n")
    rc, _ = _main(with_replies(_reply([])), repo, head, capsys)
    assert rc == 0


def test_reproducer_dirtying_code_exit_2(setup, capsys):
    repo, head, with_replies, _ = setup
    dirty = {"kind": "command", "argv": [sys.executable, "-c",
                                         "open('src/a.py', 'w').write('z = 0\\n')"],
             "expect": {"exit": 0}}
    rc, out = _main(with_replies(_reply([_finding("dirties", dirty)])), repo, head, capsys)
    assert rc == 2 and "reproducer-dirtied-tree" in out


def test_outputs_findings_log_and_summary(setup, capsys):
    repo, head, with_replies, log = setup
    note = {"file": "src/a.py", "line_range": [2, 2], "summary": "style nit", "class": "C",
            "blocking": False}
    rd = with_replies(_reply([_finding("not real", PASSING), note]))
    rc, out = _main(rd, repo, head, capsys)
    assert rc == 0
    summary = json.loads(out)
    assert set(summary) == {"blocking", "downgraded", "inconclusive", "notes", "tally"}
    assert summary["blocking"] == 0 and summary["downgraded"] == 1
    assert summary["inconclusive"] == 0 and summary["notes"] == 1
    assert summary["tally"]["blocking"] == 0
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    assert [f["verdict"] for f in findings] == ["minor", "minor"]
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("[tp-pr-iterate/downgrade] round 2 not-reproduced src/a.py:1")
    assert lines[1].startswith("[tp-pr-iterate/note] round 2 C src/a.py:2")
    assert not _git(repo, "status", "--porcelain")


def test_log_appends_never_truncates(setup, capsys):
    repo, head, with_replies, log = setup
    _write(log.parent, log.name, "earlier line\n")
    rc, _ = _main(with_replies(_reply([_finding("not real", PASSING)])), repo, head, capsys)
    assert rc == 0
    assert log.read_text(encoding="utf-8").splitlines()[0] == "earlier line"


def test_missing_reply_is_fail_closed(setup, capsys):
    repo, head, with_replies, _ = setup
    rd = with_replies(_reply([]))
    Path(json.loads((rd / "angles.json").read_text(encoding="utf-8"))
         ["angles"][0]["reply_path"]).unlink()
    rc, out = _main(rd, repo, head, capsys)
    assert rc == 0 and json.loads(out)["tally"]["degraded"] == 1


def test_real_subprocess_failing_pytest_reproducer(setup):
    """One end-to-end run: a tiny failing pytest reproducer keeps the finding blocking."""
    repo, head, with_replies, _ = setup
    repro = {"kind": "test", "source": "def test_bug():\n    assert 1 == 2\n"}
    rd = with_replies(_reply([_finding("real defect", repro)]))
    proc = subprocess.run([sys.executable, str(SCRIPT), "--round-dir", str(rd), "--cwd",
                           str(repo), "--head", head], capture_output=True, text=True,
                          timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["blocking"] == 1 and summary["downgraded"] == 0
    assert (rd / "tail" / "repro_0.py").is_file()
