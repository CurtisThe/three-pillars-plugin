"""proof_reap: strip, prune and size-check keep exactly the proof files."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proof_reap  # noqa: E402
import proof_root  # noqa: E402
from proof_reap import PROOF_FILES  # noqa: E402


def _w(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _round(root: Path, pr="7", name="r1", terminal=True, manifest_root=None):
    rd = root / "rounds" / pr / name
    mroot = str(manifest_root if manifest_root is not None else root)
    reply = f"{mroot}/rounds/{pr}/{name}/a1/reply.md"
    _w(rd / "angles.json", json.dumps({
        "paths": {"proof_root": mroot},
        "angles": [{"name": "a1", "reply_path": reply,
                    "prompt": f"write {reply} under {mroot}/x"}]}))
    _w(rd / "a1" / "reply.md", "reply")
    _w(rd / "a1" / "scratch.bin", "junk")
    _w(rd / "a1" / "sub" / "deep.txt", "junk")
    env = {"terminal": "clean"} if terminal else {"terminal": None}
    _w(rd / "tail" / "envelope.json", json.dumps(env))
    _w(rd / "tail" / "findings.json", "junk")
    return rd


def test_proof_files_defined_once():
    assert "reply.md" in PROOF_FILES["angle"]
    assert "angles.json" in PROOF_FILES["round"]
    assert "tail/envelope.json" in PROOF_FILES["round"]
    assert {"meta.json", "transcripts.json", "numstat.txt"} <= set(PROOF_FILES["head"])


def test_strip_angle_dir_keeps_only_reply_and_returns_removed(tmp_path):
    a = tmp_path / "a"
    _w(a / "reply.md")
    _w(a / "junk.txt")
    _w(a / "sub" / "deep.txt")
    removed = proof_reap.strip_angle_dir(a)
    assert (a / "reply.md").exists()
    assert not (a / "sub").exists() and not (a / "junk.txt").exists()
    assert {Path(p).name for p in removed} >= {"junk.txt", "deep.txt"}


def test_symlink_unlinked_and_target_survives(tmp_path):
    target = _w(tmp_path / "outside" / "secret.txt", "keep me")
    a = tmp_path / "a"
    a.mkdir()
    os.symlink(target, a / "reply.md")
    os.symlink(target.parent, a / "linkdir")
    proof_reap.strip_angle_dir(a)
    assert not os.path.lexists(a / "reply.md") and not os.path.lexists(a / "linkdir")
    assert target.read_text(encoding="utf-8") == "keep me"


def test_prune_keeps_exactly_proof_files(tmp_path):
    rd = _round(tmp_path)
    _w(rd / "stray.txt")
    res = proof_reap.prune_to_proof(tmp_path / "rounds" / "7")
    kept = sorted(str(p.relative_to(rd)) for p in rd.rglob("*") if p.is_file())
    assert kept == ["a1/reply.md", "angles.json", "tail/envelope.json", "tail/findings.json"]
    assert res["open"] is None and res["removed_files"] >= 3 and res["removed_bytes"] > 0
    assert res["kept"] == 4
    assert not (rd / "a1" / "sub").exists()


def test_prune_keeps_findings_of_latest_round_only(tmp_path):
    older = _round(tmp_path, name="r1")
    latest = _round(tmp_path, name="r2")
    proof_reap.prune_to_proof(tmp_path / "rounds" / "7")
    assert not (older / "tail" / "findings.json").exists()
    assert (latest / "tail" / "findings.json").read_text(encoding="utf-8") == "junk"


def test_prune_refuses_bad_pr_dir(tmp_path):
    with pytest.raises(ValueError):
        proof_reap.prune_to_proof(tmp_path / "elsewhere" / "7")
    with pytest.raises(ValueError):
        proof_reap.prune_to_proof(tmp_path / "rounds" / "notanumber")


def test_prune_leaves_open_pr_untouched(tmp_path, capsys):
    rd = _round(tmp_path, terminal=False)
    rc = proof_reap.main(["prune", "--pr", "7", "--root", str(tmp_path)])
    cap = capsys.readouterr()
    assert rc == 0
    assert (rd / "a1" / "scratch.bin").exists() and (rd / "tail" / "findings.json").exists()
    assert json.loads(cap.out)["open"] == "r1"
    assert "skipped open round" in cap.err


def test_closed_marker_makes_round_closed(tmp_path):
    rd = _round(tmp_path, terminal=False)
    assert proof_reap.is_open(tmp_path / "rounds" / "7")
    _w(rd / "tail" / "closed.json", "{}")
    assert not proof_reap.is_open(tmp_path / "rounds" / "7")
    assert proof_reap.latest_round(tmp_path / "rounds" / "7") == rd


def test_latest_round_orders_rerun_after_base(tmp_path):
    _round(tmp_path, name="r2")
    r21 = _round(tmp_path, name="r2.1")
    _round(tmp_path, name="r1")
    assert proof_reap.latest_round(tmp_path / "rounds" / "7") == r21
    assert proof_reap.latest_round(tmp_path / "rounds" / "99") is None
    assert not proof_reap.is_open(tmp_path / "rounds" / "99")


def test_migrated_root_open_round_repointed_not_reaped(tmp_path, capsys):
    old = tmp_path / "wt" / ".three-pillars" / "review-proof"
    new = tmp_path / "gitdir" / "three-pillars" / "review-proof"
    rd = _round(new, terminal=False, manifest_root=old)
    (rd / "scratch.bin").write_text("s", encoding="utf-8")
    proof_reap.main(["prune", "--pr", "7", "--root", str(new)])
    m = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    assert m["paths"]["proof_root"] == str(new)
    assert m["angles"][0]["reply_path"].startswith(str(new))
    assert str(old) not in json.dumps(m)
    assert Path(m["angles"][0]["reply_path"]).exists()
    assert (rd / "scratch.bin").exists() and (rd / "a1" / "scratch.bin").exists()
    assert "skipped open round" in capsys.readouterr().err


def test_migrated_root_closed_round_repointed_and_pruned(tmp_path):
    old = tmp_path / "wt" / ".three-pillars" / "review-proof"
    new = tmp_path / "gitdir" / "rp"
    rd = _round(new, terminal=True, manifest_root=old)
    res = proof_reap.prune_to_proof(new / "rounds" / "7")
    m = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    assert m["paths"]["proof_root"] == str(new)
    assert len(res["repointed"]) == 1
    assert not (rd / "a1" / "scratch.bin").exists() and (rd / "a1" / "reply.md").exists()


def test_size_check_skips_open_and_prunes_closed(tmp_path):
    open_rd = _round(tmp_path, pr="1", terminal=False)
    closed_rd = _round(tmp_path, pr="2", terminal=True)
    _w(open_rd / "stray.bin", "z" * 4000)
    _w(closed_rd / "stray.bin", "z" * 4000)
    res = proof_reap.size_check(tmp_path, max_mb=0)
    assert res["over_cap"] is True and len(res["open"]) == 1
    assert (open_rd / "stray.bin").exists() and not (closed_rd / "stray.bin").exists()
    assert (closed_rd / "angles.json").exists() and (closed_rd / "a1" / "reply.md").exists()
    assert res["after"] < res["before"]


def test_size_check_under_cap_removes_nothing(tmp_path):
    rd = _round(tmp_path)
    res = proof_reap.size_check(tmp_path, max_mb=5)
    assert res["over_cap"] is False and (rd / "a1" / "scratch.bin").exists()


def test_size_check_never_removes_head_proof(tmp_path):
    _round(tmp_path)
    for name in PROOF_FILES["head"]:
        _w(tmp_path / "abc123" / name, "p" * 3000)
    _w(tmp_path / "iterate-state.7.v1.json", "{}")
    proof_reap.size_check(tmp_path, max_mb=0)
    for name in PROOF_FILES["head"]:
        assert (tmp_path / "abc123" / name).exists()
    assert (tmp_path / "iterate-state.7.v1.json").exists()


def test_cli_prune_without_root_uses_resolver(tmp_path, monkeypatch, capsys):
    rd = _round(tmp_path)
    monkeypatch.setattr(proof_root, "default_proof_root", lambda *a, **k: tmp_path)
    assert proof_reap.main(["prune", "--pr", "7"]) == 0
    assert not (rd / "a1" / "scratch.bin").exists()
    assert json.loads(capsys.readouterr().out)["removed_files"] >= 1


def test_cli_size_check_and_refusal(tmp_path, monkeypatch, capsys):
    _round(tmp_path, pr="2")
    monkeypatch.setattr(proof_root, "default_proof_root", lambda *a, **k: tmp_path)
    assert proof_reap.main(["size-check", "--max-mb", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["over_cap"] is True
    assert proof_reap.main(["prune", "--pr", "../x", "--root", str(tmp_path)]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
