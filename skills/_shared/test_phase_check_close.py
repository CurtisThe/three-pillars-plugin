"""test_phase_check_close.py — the carry side of a phase check (task 8.4).

design: review-convergence (Phase 8, `SH/phase_check.py`)

Oracle: ``example`` — the replies are real files in a real scratch dir, parsed by the
same strict contract ``put`` writes under, so ``close`` is exercised on bytes rather than
on a mock. Every case is one contract line from the design companion: a fixed finding is
not carried, a disputed or unfixed one is (with ``reason`` only when disputed), a missing
worker reply leaves everything unfixed, a missing checker reply closes the phase with
nothing carried, a second ``close`` for a closed phase adds nothing, and a later phase
appends to the same top-level ``items`` list. The CLI block is the round trip the
orchestrator runs: ``prepare`` → ``put`` (stdin) → ``close`` → ``known``.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import phase_check
from attempt_fixture import commit, git

DD = "three-pillars-docs/tp-designs/demo"
CARRY = phase_check.CARRY

FINDINGS = [
    {"id": "f1", "file": "impl/a.py", "line_range": "3-9", "summary": "off by one",
     "blocking": True, "class": "bug", "fragility_class": "fragile"},
    {"id": "f2", "file": "impl/b.py", "line_range": "12", "summary": "dead branch",
     "blocking": False, "class": "quality", "fragility_class": "solid"},
    {"id": "f3", "file": "impl/c.py", "line_range": "1-4", "summary": "wide except",
     "blocking": True, "class": "bug", "fragility_class": "fragile"},
]

PLAN_TEXT = """# Demo plan

## Phase 1: demo phase

The demo phase must keep the behaviour of `impl/a.py`.
"""


def _json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _design(tmp_path: Path, phases: dict, items: list | None = None) -> Path:
    dd = tmp_path / "design"
    dd.mkdir()
    carry: dict = {"phases": {k: dict(v) for k, v in phases.items()}}
    if items is not None:
        carry["items"] = list(items)
    _json(dd / CARRY, carry)
    return dd


def _open(tmp_path: Path) -> Path:
    return _design(tmp_path, {"1": {"status": "open", "base": "b", "head": "h"}})


def _scratch(tmp_path: Path, name: str = "scratch", findings=FINDINGS) -> Path:
    s = tmp_path / name
    s.mkdir()
    if findings is not None:
        _json(s / "checker.reply.json", {"findings": findings})
    return s


def _carry(dd: Path) -> dict:
    return json.loads((dd / CARRY).read_text(encoding="utf-8"))


def test_fixed_is_not_carried_and_the_others_are(tmp_path):
    dd = _open(tmp_path)
    scratch = _scratch(tmp_path)
    reply = _json(tmp_path / "worker.json",
                  {"fixed": ["f1"], "disputed": [{"id": "f2", "reason": "x"}]})

    res = phase_check.close(dd, 1, scratch=scratch, worker_reply_path=reply)
    assert res["carried"] == 2 and res["fixed"] == 1

    carry = _carry(dd)
    assert carry["phases"]["1"]["status"] == "closed"
    items = carry["items"]
    assert [i["id"] for i in items] == ["f2", "f3"]
    assert items[0]["status"] == "disputed" and items[0]["reason"] == "x"
    assert items[1]["status"] == "unfixed" and "reason" not in items[1]
    for item in items:
        assert item["phase"] == "1"
        assert item["file"] and item["line_range"] and item["summary"]
        assert "blocking" in item

    known = phase_check.known_items(dd)
    assert [i["id"] for i in known] == ["f2", "f3"]
    assert phase_check.known_items(tmp_path / "no-such-design") == []


def test_no_worker_reply_leaves_every_finding_unfixed(tmp_path):
    dd = _open(tmp_path)
    res = phase_check.close(dd, 1, scratch=_scratch(tmp_path),
                            worker_reply_path=tmp_path / "absent.json")
    assert (res["carried"], res["fixed"]) == (3, 0)
    assert [i["status"] for i in phase_check.known_items(dd)] == ["unfixed"] * 3


def test_a_second_close_adds_nothing(tmp_path):
    dd = _open(tmp_path)
    scratch = _scratch(tmp_path)
    phase_check.close(dd, 1, scratch=scratch)

    again = phase_check.close(dd, 1, scratch=scratch)
    assert again["carried"] == 0 and again["fixed"] == 0
    assert [i["id"] for i in phase_check.known_items(dd)] == ["f1", "f2", "f3"]
    assert _carry(dd)["phases"]["1"]["status"] == "closed"


def test_a_missing_checker_reply_closes_with_nothing_carried(tmp_path):
    dd = _open(tmp_path)
    res = phase_check.close(dd, 1, scratch=_scratch(tmp_path, findings=None))
    assert res["carried"] == 0 and res["fixed"] == 0
    assert _carry(dd)["phases"]["1"]["status"] == "closed"
    assert phase_check.known_items(dd) == []


def test_a_later_phase_appends_to_the_same_items_list(tmp_path):
    dd = _design(tmp_path, {"1": {"status": "open"}, "2": {"status": "open"}})
    phase_check.close(dd, 1, scratch=_scratch(tmp_path, "s1"))
    phase_check.close(dd, 2, scratch=_scratch(tmp_path, "s2", findings=FINDINGS[:1]))

    known = phase_check.known_items(dd)
    assert [(i["phase"], i["id"]) for i in known] == [("1", "f1"), ("1", "f2"),
                                                      ("1", "f3"), ("2", "f1")]
    assert _carry(dd)["phases"] == (
        {"1": {"status": "closed"}, "2": {"status": "closed"}})


def test_the_cli_round_trips_prepare_put_close_known(tmp_path, capsys, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    base = commit(repo, {"README.md": "demo\n", f"{DD}/plan.md": PLAN_TEXT}, "base")
    head = commit(repo, {"impl/a.py": "A = 1\n"}, "work")
    dd = repo / DD

    rc = phase_check.main(["prepare", "--design-dir", str(dd), "--phase", "1",
                           "--base", base, "--head", head, "--repo", str(repo),
                           "--plan", str(dd / "absent-plan.md")])
    assert rc == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["status"] == "ready"
    scratch = Path(prepared["scratch"])
    assert scratch.is_dir()

    monkeypatch.setattr("sys.stdin", io.StringIO("not a reply"))
    rc = phase_check.main(["put", "--scratch", str(scratch), "--slot", "checker"])
    assert rc == 1
    assert "error" in json.loads(capsys.readouterr().out)

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"findings": FINDINGS})))
    rc = phase_check.main(["put", "--scratch", str(scratch), "--slot", "checker"])
    assert rc == 0
    assert Path(json.loads(capsys.readouterr().out)["path"]) == (
        scratch / "checker.reply.json")

    reply = _json(tmp_path / "worker.json",
                  {"fixed": ["f1"], "disputed": [{"id": "f2", "reason": "x"}]})
    rc = phase_check.main(["close", "--design-dir", str(dd), "--phase", "1",
                           "--scratch", str(scratch), "--worker-reply", str(reply)])
    assert rc == 0
    closed = json.loads(capsys.readouterr().out)
    assert closed["carried"] == 2 and closed["fixed"] == 1

    rc = phase_check.main(["known", "--design-dir", str(dd)])
    assert rc == 0
    assert [i["id"] for i in json.loads(capsys.readouterr().out)] == ["f2", "f3"]

    rc = phase_check.main(["prepare", "--design-dir", str(dd), "--phase", "1",
                           "--base", base, "--head", head, "--repo", str(repo),
                           "--plan", str(dd / "absent-plan.md")])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"status": "skip",
                                                   "reason": "already-checked"}
