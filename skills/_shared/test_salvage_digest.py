"""Tests for salvage_digest.digest (design: ladder-diagnose-and-size-pins, task 1.3)."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import salvage_digest  # noqa: E402

TEST_CMD = "python3 -m pytest skills/_shared/test_x.py"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], check=True, capture_output=True)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    (repo / "b.py").write_text("y = 2\n" * 495)
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-qm", "beyond")
    (repo / "a.py").write_text("x = 2\n")  # uncommitted edit
    return repo, base


def _use(i, name, inp):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}}


def _res(i, text):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": text}]}}


def _transcript(tmp_path):
    out = "\n".join(f"line {n}" for n in range(60))
    recs = [_use(1, "Bash", {"command": TEST_CMD}), _res(1, out),
            _use(2, "Edit", {"file_path": "/r/a.py", "old_string": "a", "new_string": "b"}),
            _res(2, "ok")]
    for i in range(3, 15):
        recs += [_use(i, "Bash", {"command": f"echo {i}"}), _res(i, "x")]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return path


def test_digest_full(tmp_path):
    repo, base = _repo(tmp_path)
    d = salvage_digest.digest(_transcript(tmp_path), repo, base, TEST_CMD)
    assert d["test"]["command"] == TEST_CMD
    tail = d["test"]["output_tail"].splitlines()
    assert len(tail) == 40 and tail[-1] == "line 59"
    rows = {r["path"]: r for r in d["files"]}
    assert set(rows) == {"a.py", "b.py"}
    assert rows["b.py"]["lines"] == 495 and rows["b.py"]["at_cap"] is True
    assert rows["a.py"]["at_cap"] is False
    assert len(d["calls"]) == 10
    assert d["calls"][-1]["name"] == "Bash" and "echo 14" in d["calls"][-1]["summary"]
    assert "echo 5" in d["calls"][0]["summary"]


def test_pytest_fallback_without_command(tmp_path):
    repo, base = _repo(tmp_path)
    d = salvage_digest.digest(_transcript(tmp_path), repo, base)
    assert "pytest" in d["test"]["command"]


def test_missing_transcript_never_raises(tmp_path):
    repo, base = _repo(tmp_path)
    d = salvage_digest.digest(tmp_path / "nope.jsonl", repo, base, TEST_CMD)
    assert d["test"] == {"command": "", "output_tail": ""}
    assert d["calls"] == []
    assert {r["path"] for r in d["files"]} == {"a.py", "b.py"}
