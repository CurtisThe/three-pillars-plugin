"""cheap_fix live-tree guard and discard idempotency (cheap-tier-offload PR #191 review r1).

The drafter's cwd is the fix worktree, so `scratch` snapshots that tree and `adopt`
escalates `drafter-wrote-live-tree` on any change there, undoing only those paths.
`discard` is idempotent, a refused remove never replaces the verdict, and the CLI
always prints its one JSON line.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_fix  # noqa: E402
import cheap_fix_cli  # noqa: E402
from test_cheap_fix import GREEN, _finding, _git, _gone, _head, repo  # noqa: E402,F401


def test_a_drafter_that_wrote_the_live_tree_escalates_and_only_its_paths_are_undone(repo):
    (repo / "wip.txt").write_text("the operator's\n", encoding="utf-8")
    path = cheap_fix.scratch(repo, _head(repo))
    (path / "a.py").write_text("fixed", encoding="utf-8")  # a proper scratch fix
    (repo / "a.py").write_text("fixed", encoding="utf-8")  # ...and a stray live copy
    (repo / "test_old.py").write_text("def test_old():\n    assert 1\n", encoding="utf-8")
    (repo / "test_stray.py").write_text("def test_s():\n    pass\n", encoding="utf-8")
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["ok"] is False and v["action"] == "escalate", v
    assert v["reason"].startswith("drafter-wrote-live-tree: "), v
    assert v["files"] == ["a.py", "test_old.py", "test_stray.py"]
    assert _gone(repo, path)
    assert _git(repo, "status", "--porcelain", "-uall") == "?? wip.txt"
    assert (repo / "a.py").read_text(encoding="utf-8") == "broken"
    assert (repo / "wip.txt").read_text(encoding="utf-8") == "the operator's\n"


def test_discard_is_idempotent(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    cheap_fix.discard(path)
    cheap_fix.discard(path)  # a second discard is a no-op
    cheap_fix.discard(repo / "nowhere" / "r1")
    assert _gone(repo, path) and (repo / "a.py").exists()


def test_a_refused_remove_never_replaces_the_verdict(repo, tmp_path, monkeypatch):
    path = cheap_fix.scratch(repo, _head(repo))

    def refuse(target, owner):
        raise cheap_fix.round_scratch.RemoveRefused("refused")

    monkeypatch.setattr(cheap_fix.round_scratch, "safe_remove", refuse)
    v = cheap_fix.adopt(path, repo, _finding(), test_argv=GREEN)
    assert v["action"] == "escalate" and "no change" in v["reason"], v
    monkeypatch.undo()
    cheap_fix.discard(path)


def test_cli_adopt_on_a_missing_scratch_prints_its_json_line(tmp_path):
    proc = subprocess.run([sys.executable, str(Path(cheap_fix_cli.__file__)), "adopt",
                           "--scratch", str(tmp_path / "cheap-fix-x" / "r1"),
                           "--fix-worktree", str(tmp_path), "--finding",
                           str(tmp_path / "finding.json")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["action"] == "escalate"


@pytest.mark.parametrize("finding", [None, "ok"])
def test_cli_adopt_rerun_after_a_discard_escalates(repo, tmp_path, capsys, finding):
    path = cheap_fix.scratch(repo, _head(repo))
    cheap_fix.discard(path)
    f = tmp_path / "finding.json"
    if finding:
        f.write_text(json.dumps(_finding()), encoding="utf-8")
    assert cheap_fix_cli.main(["adopt", "--scratch", str(path), "--fix-worktree", str(repo),
                               "--finding", str(f)]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "escalate"
