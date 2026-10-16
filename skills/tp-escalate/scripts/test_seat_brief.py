"""Tests for skills/tp-escalate/scripts/seat_brief.py.

design: fable-escalation 6.3 — the seat stop builder (fleet context) and the
relay line. Every seam (registry, porcelain, git) is injected: no real tmux
or registry is touched; one test drives a real throwaway git repo so the
``tp/<S>`` fallback is checked against what real git actually prints.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parents[1] / "_shared"))

import ruling_file as rf  # noqa: E402
import seat_brief as sb  # noqa: E402


def _write_ruling(root, scope, at, result=None):
    stop = {"source": "question", "signal": "decision", "target": scope,
            "detail": {"question": f"q {scope} {at}"}}
    key = f"question:decision:{scope}:abc12345"
    return rf.write(root, scope=scope, entry="seat", stop=stop, key=key,
                    result=result or {"outcome": "resolved"}, model="fable",
                    at=at).stem


def _porcelain(entries):
    lines = []
    for path, branch in entries:
        lines.append(f"worktree {path}")
        lines.append("HEAD 0000000000000000000000000000000000000000")
        if branch:
            lines.append(f"branch refs/heads/{branch}")
    return "\n".join(lines) + "\n"


def _stop(scope="demo", tmp_path=None, *, porcelain="", git=lambda a: "",
          registry=lambda: [], **kw):
    return sb.build_stop(scope, root=tmp_path, registry_fn=registry,
                         porcelain_fn=lambda: porcelain, git_fn=git, **kw)


def test_question_stop_shape(tmp_path):
    stop = _stop(tmp_path=tmp_path, question="which branch?", kind="decision")
    assert stop["source"] == "question"
    assert stop["signal"] == "decision"
    assert stop["target"] == "demo"
    assert stop["detail"]["question"] == "which branch?"
    fleet = stop["detail"]["fleet"]
    assert set(fleet) == {"registry", "handoff", "run_ruling"}
    assert fleet["registry"] == []
    assert fleet["handoff"] is None
    assert fleet["run_ruling"] is None


def test_registry_rows_pass_through(tmp_path):
    rows = [{"design": "demo", "branch": "tp/demo", "stale": False}]
    stop = _stop(tmp_path=tmp_path, question="q", kind="decision",
                 registry=lambda: rows)
    assert stop["detail"]["fleet"]["registry"] == rows


def test_registry_fail_open(tmp_path):
    def boom():
        raise RuntimeError("remote unreachable")

    stop = _stop(tmp_path=tmp_path, question="q", kind="decision", registry=boom)
    assert stop["detail"]["fleet"]["registry"] == []


def test_handoff_path_when_present_else_null(tmp_path):
    stop = _stop(tmp_path=tmp_path, question="q", kind="decision")
    assert stop["detail"]["fleet"]["handoff"] is None
    handoff = tmp_path / "three-pillars-docs/tp-designs/orchestration/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("# handoff\n", encoding="utf-8")
    stop = _stop(tmp_path=tmp_path, question="q", kind="decision")
    assert stop["detail"]["fleet"]["handoff"] == str(handoff)


def test_run_ruling_newest_from_run_worktree(tmp_path):
    wt = tmp_path / "wt"
    _write_ruling(wt, "demo", "2026-10-10T10:00:00Z")
    newest = _write_ruling(wt, "demo", "2026-10-11T10:00:00Z")
    porcelain = _porcelain([(str(tmp_path), "master"), (str(wt), "tp/demo")])
    stop = _stop(tmp_path=tmp_path, question="q", kind="decision",
                 porcelain=porcelain)
    rr = stop["detail"]["fleet"]["run_ruling"]
    assert rr is not None and rr["front"]["id"] == newest


def test_run_ruling_slug_matched_exactly(tmp_path):
    wt = tmp_path / "wt"
    demo = _write_ruling(wt, "demo", "2026-10-10T10:00:00Z")
    _write_ruling(wt, "demo-x", "2026-10-12T10:00:00Z")
    porcelain = _porcelain([(str(wt), "tp/demo")])
    stop = _stop(tmp_path=tmp_path, question="q", kind="decision",
                 porcelain=porcelain)
    assert stop["detail"]["fleet"]["run_ruling"]["front"]["id"] == demo


def test_run_ruling_from_tp_branch_via_git_seam(tmp_path):
    src = tmp_path / "src"
    rid = _write_ruling(src, "demo", "2026-10-10T10:00:00Z")
    text = (src / rf.RULINGS_REL / f"{rid}.md").read_text(encoding="utf-8")

    def git(args):
        # Real git answers the tree-ish:path form with bare names, one per
        # line — and rejects the two-argument form. A fake that answers any
        # ``ls-tree`` hides the bug the real-repo test below pins.
        if args[0] == "ls-tree":
            if args[1:] != ["--name-only", f"tp/demo:{rf.RULINGS_REL}"]:
                raise AssertionError(f"unexpected git args {args}")
            return f"{rid}.md\n"
        if args[0] == "show":
            if args[1:] != [f"tp/demo:{rf.RULINGS_REL}/{rid}.md"]:
                raise AssertionError(f"unexpected git args {args}")
            return text
        raise AssertionError(f"unexpected git args {args}")

    stop = _stop(tmp_path=tmp_path, question="q", kind="decision",
                 porcelain=_porcelain([(str(tmp_path), "master")]), git=git)
    assert stop["detail"]["fleet"]["run_ruling"]["front"]["id"] == rid


def _real_git(repo):
    def git(args):
        out = subprocess.run(["git", "-C", str(repo)] + list(args),
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr}")
        return out.stdout
    return git


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",
                        "-c", "user.email=t@example.com"] + list(args),
                       check=True, capture_output=True, text=True)

    run("init", "-b", "main")
    return repo, run


def test_run_ruling_newest_from_real_tp_branch(tmp_path):
    repo, run = _init_repo(tmp_path)
    _write_ruling(repo, "demo", "2026-10-10T10:00:00Z")
    newer = _write_ruling(repo, "demo", "2026-10-11T10:00:00Z")
    run("add", "-A")
    run("commit", "-m", "rulings")
    run("branch", "tp/demo")
    porcelain = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, encoding="utf-8").stdout
    stop = _stop(tmp_path=tmp_path, question="q", kind="decision",
                 porcelain=porcelain, git=_real_git(repo))
    rr = stop["detail"]["fleet"]["run_ruling"]
    assert rr is not None and rr["front"]["id"] == newer


def test_run_ruling_null_when_neither_worktree_nor_branch(tmp_path):
    def git(args):
        raise RuntimeError("not a branch")

    stop = _stop(tmp_path=tmp_path, question="q", kind="decision",
                 porcelain=_porcelain([(str(tmp_path), "master")]), git=git)
    assert stop["detail"]["fleet"]["run_ruling"] is None


def test_run_ruling_null_for_seat_scope(tmp_path):
    wt = tmp_path / "wt"
    _write_ruling(wt, "seat", "2026-10-11T10:00:00Z")
    stop = _stop("seat", tmp_path=tmp_path, question="q", kind="decision",
                 porcelain=_porcelain([(str(wt), "tp/seat")]))
    assert stop["detail"]["fleet"]["run_ruling"] is None


def test_stop_keeps_source_signal_target_wraps_detail(tmp_path):
    given = {"source": "halt", "signal": "env-error", "target": "demo",
             "detail": "git failed in /x"}
    stop = _stop(tmp_path=tmp_path, stop=given)
    assert stop["source"] == "halt"
    assert stop["signal"] == "env-error"
    assert stop["target"] == "demo"
    assert stop["detail"]["original"] == "git failed in /x"
    assert "fleet" in stop["detail"]


def test_stop_dict_detail_keeps_its_keys(tmp_path):
    given = {"source": "audit-gate", "signal": "tier-2", "target": "demo",
             "detail": {"reason": "audit rejected"}}
    stop = _stop(tmp_path=tmp_path, stop=given)
    assert stop["detail"]["reason"] == "audit rejected"
    assert "fleet" in stop["detail"]


def test_cli_build_question_file_writes_stop(tmp_path, monkeypatch, capsys):
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(sb, "_default_registry_rows", boom)
    monkeypatch.setattr(sb, "_default_porcelain", lambda: "")
    verdict = tmp_path / "verdict.txt"
    verdict.write_text("fleet trouble: run stalled at tier 2\n", encoding="utf-8")
    out = tmp_path / "stop.json"
    rc = sb.main(["build", "--scope", "demo", "--question-file", str(verdict),
                  "--kind", "decision", "--out", str(out)])
    assert rc == 0
    stop = json.loads(out.read_text(encoding="utf-8"))
    assert stop["source"] == "question"
    assert stop["signal"] == "decision"
    assert stop["target"] == "demo"
    assert stop["detail"]["question"].startswith("fleet trouble")
    assert stop["detail"]["fleet"]["registry"] == []
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    assert json.loads(printed[0])["out"] == str(out)


def _parsed_ruling(rid, label, desc):
    return {"front": {"id": rid, "slug": "demo"},
            "question": "q",
            "ruling": {"outcome": "resolved",
                       "ruling": {"options": [
                           {"id": "a", "label": label, "description": desc,
                            "recommended": True},
                           {"id": "b", "label": "other",
                            "description": "no"}]}},
            "feedback": []}


def test_relay_line_prefix(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    result = {"outcome": "resolved",
              "ruling": {"options": [
                  {"id": "a", "label": "keep going",
                   "description": "apply option a and re-run the tier",
                   "recommended": True}]}}
    rid = _write_ruling(tmp_path, "demo", "2026-10-11T10:00:00Z", result=result)
    rc = sb.main(["relay", "--id", rid])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == (f"Seat (under operator delegation): ruling {rid} resolved"
                   " — keep going: apply option a and re-run the tier; "
                   "apply it and continue.\n")


def test_relay_decided_capped():
    line = sb.relay_line(_parsed_ruling("demo-20261011-abcdef", "keep going",
                                        "d" * 400))
    assert line.startswith("Seat (under operator delegation): ruling "
                           "demo-20261011-abcdef resolved — ")
    decided = line.split("resolved — ", 1)[1].split("; apply it")[0]
    assert len(decided) <= 240
    assert decided.endswith("…")
