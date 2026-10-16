"""CLI tests for skills/_shared/lessons.py (fable-escalation 6.6 C3).

The seat's lesson round applies a proposal through the CLI: one JSON line per
call (the function's return dict), exit 0 even on a contradiction refusal,
exit 2 on bad args.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lessons  # noqa: E402

PROPOSAL = {
    "action": "add",
    "layer": "repo",
    "text": "Run the real-git test before trusting a git seam fake.",
    "applies_when": "a git seam fake answers any argument shape",
    "contradicts": [],
}
SOURCE = "demo-20261011-abcdef"


def _proposal_file(tmp_path, proposal):
    f = tmp_path / "proposal.json"
    f.write_text(json.dumps(proposal), encoding="utf-8")
    return f


def _add(tmp_path, path, capsys, proposal=None):
    pf = _proposal_file(tmp_path, proposal or PROPOSAL)
    return lessons.main(["add", "--path", str(path), "--proposal-file",
                         str(pf), "--source", SOURCE, "--today",
                         "2026-10-12"])


def test_add_writes_entry_and_prints_one_json_line(tmp_path, capsys):
    path = tmp_path / "lessons.md"
    assert _add(tmp_path, path, capsys) == 0
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    assert json.loads(printed[0]) == {"status": "added", "id": "L1"}
    entries = lessons.read(path)
    assert [e["id"] for e in entries] == ["L1"]
    assert entries[0]["lesson"] == PROPOSAL["text"]
    assert entries[0]["sources"] == [SOURCE]
    assert entries[0]["date"] == "2026-10-12"


def test_add_path_defaults_to_repo_rel_under_cwd(tmp_path, monkeypatch,
                                                 capsys):
    monkeypatch.chdir(tmp_path)
    pf = _proposal_file(tmp_path, PROPOSAL)
    rc = lessons.main(["add", "--proposal-file", str(pf), "--source", SOURCE,
                       "--today", "2026-10-12"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip())["status"] == "added"
    assert lessons.read(tmp_path / lessons.REPO_REL) != []


def test_remove_deletes_the_entry(tmp_path, capsys):
    path = tmp_path / "lessons.md"
    _add(tmp_path, path, capsys)
    capsys.readouterr()
    rc = lessons.main(["remove", "--path", str(path), "--id", "L1",
                       "--source", SOURCE])
    assert rc == 0
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    assert json.loads(printed[0]) == {"status": "removed", "id": "L1"}
    assert lessons.read(path) == []


def test_contradicting_proposal_prints_refusal_and_exits_0(tmp_path, capsys):
    path = tmp_path / "lessons.md"
    proposal = dict(PROPOSAL, contradicts=[{
        "doc": "vision.md", "section": "Principles",
        "quote": "lessons are never refused"}])
    assert _add(tmp_path, path, capsys, proposal) == 0
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    parsed = json.loads(out.strip())
    assert parsed["status"] == "refused-contradiction"
    assert "refused-contradiction" in out
    assert lessons.read(path) == []


def test_bad_args_exit_2(tmp_path, capsys):
    assert lessons.main([]) == 2
    assert lessons.main(["add"]) == 2
    assert lessons.main(["remove", "--path", str(tmp_path / "x.md"),
                         "--id", "L1"]) == 2
    assert lessons.main(["frobnicate"]) == 2
