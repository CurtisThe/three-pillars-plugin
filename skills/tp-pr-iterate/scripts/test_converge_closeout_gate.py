"""converge refuses an un-archived design head (`design-not-archived`).

design: closeout-before-pr-iterate (Task 2.1). Hermetic: injected run_git / repo_root.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import converge_rounddir  # noqa: E402

PR = "https://github.com/o/r/pull/7"


def _repo(tmp_path, *, archived):
    d = tmp_path / "repo" / "three-pillars-docs" / "tp-designs" / "demo"
    d.mkdir(parents=True)
    fm = "---\ncompleted: 2026-10-13\n---\n" if archived else "---\nstatus: draft\n---\n"
    (d / "design.md").write_text(fm + "# demo\n", encoding="utf-8")
    return tmp_path / "repo"


def _git(branch):
    def run(args):
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return 0, branch + "\n", ""
        return 0, "abc123\n", ""
    return run


def _converge(tmp_path, monkeypatch, repo, branch):
    angle = tmp_path / "a.txt"
    angle.write_text("```json\n" + json.dumps({"findings": []}) + "\n```\n", encoding="utf-8")
    finished, posts, rounds = [], [], []
    monkeypatch.setattr(converge, "_finish_clean", lambda **k: finished.append(k) or 0)
    out, err = io.StringIO(), io.StringIO()
    rc = converge.converge(
        base="b0", head="h1", pr_url=PR, config={}, angle_files=[str(angle)],
        post_fn=lambda *a, **k: posts.append(a), run_round_fn=lambda s: rounds.append(s) or {},
        run_git=_git(branch), repo_root=repo, out=out, err=err)
    return rc, out.getvalue(), finished, posts, rounds


def test_unarchived_head_refused(tmp_path, monkeypatch):
    rc, out, finished, posts, rounds = _converge(
        tmp_path, monkeypatch, _repo(tmp_path, archived=False), "tp/demo")
    # Order matters: a bypassed gate returns 0 with an empty stdout, so the rc and
    # seam checks come before the JSON parse (a crash there is no assertion).
    assert rc == 3, "converge must refuse an un-archived tp/ head"
    assert not finished and not posts and not rounds, \
        "refusal must not reach _finish_clean/post/run_round"
    lines = out.strip().splitlines()
    assert lines, "refusal must emit its JSON doc on stdout"
    doc = json.loads(lines[-1])
    assert doc["converged"] is False, "refusal doc must carry converged: false"
    assert doc["not_converged_reason"] == "design-not-archived", \
        "refusal doc must carry not_converged_reason design-not-archived"
    assert "tp-design-complete" in doc["remedy"], "remedy must name /tp-design-complete"


def test_archived_head_proceeds(tmp_path, monkeypatch):
    rc, _out, finished, _p, _r = _converge(
        tmp_path, monkeypatch, _repo(tmp_path, archived=True), "tp/demo")
    assert rc == 0 and len(finished) == 1


def test_non_tp_branch_skips_gate(tmp_path, monkeypatch):
    rc, _out, finished, _p, _r = _converge(
        tmp_path, monkeypatch, _repo(tmp_path, archived=False), "feature/x")
    assert rc == 0 and len(finished) == 1


def test_rounddir_refuses_without_evidence_accept(tmp_path, monkeypatch):
    manifest = {"head": "h1", "round": 1, "paths": {"state_path": "s", "proof_root": "p"}}
    monkeypatch.setattr(converge_rounddir, "_load", lambda r: manifest)
    monkeypatch.setattr(converge_rounddir, "_check", lambda *a: [])
    finished = []
    monkeypatch.setattr(converge, "_finish_clean", lambda **k: finished.append(k) or 0)
    out = io.StringIO()
    rc = converge_rounddir.run(
        tmp_path, config={},
        seams={"out": out, "err": io.StringIO(), "run_git": _git("tp/demo"),
               "repo_root": _repo(tmp_path, archived=False)})
    text = out.getvalue()
    assert rc == 3 and not finished
    assert "evidence-complete" not in text
    assert json.loads(text.strip().splitlines()[-1])["not_converged_reason"] == "design-not-archived"
