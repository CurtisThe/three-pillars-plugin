"""Behavior 8: every terminal (flush with --root/--pr-url, stop) reaps to proof."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proof_reap  # noqa: E402
import proof_root  # noqa: E402
import round_scratch  # noqa: E402

URL = "https://github.com/o/r/pull/7"


def _round(root: Path, terminal, manifest_root=None) -> Path:
    rd = root / "rounds" / "7" / "r1"
    (rd / "a1").mkdir(parents=True)
    (rd / "tail").mkdir()
    mroot = str(manifest_root if manifest_root is not None else root)
    (rd / "angles.json").write_text(
        json.dumps({"paths": {"proof_root": mroot}, "angles": []}), encoding="utf-8")
    (rd / "a1" / "reply.md").write_text("reply", encoding="utf-8")
    (rd / "a1" / "scratch.bin").write_bytes(b"0" * 1024 * 1024)
    (rd / "tail" / "envelope.json").write_text(json.dumps({"terminal": terminal}), encoding="utf-8")
    return rd


def _files(tmp: Path):
    log, dec = tmp / "loop.md", tmp / "decisions.md"
    log.write_text("entry\n", encoding="utf-8")
    dec.write_text("", encoding="utf-8")
    return log, dec


def _assert_proof_only(rd: Path):
    assert not (rd / "a1" / "scratch.bin").exists()
    assert (rd / "a1" / "reply.md").exists()
    assert (rd / "angles.json").exists()
    assert (rd / "tail" / "envelope.json").exists()


def _flush(log, dec, *extra):
    return round_scratch.main(["flush", "--log", str(log), "--decisions", str(dec), *extra])


def _stop(log, dec, *extra):
    return round_scratch.main(["stop", "--pr-url", URL, "--log", str(log),
                               "--decisions", str(dec), *extra])


def test_flush_reaps_at_two_stable_and_budget_exhausted(tmp_path, capsys):
    for i, term in enumerate(("two-stable", "budget-exhausted")):
        root = tmp_path / f"root{i}"
        rd = _round(root, term)
        log, dec = _files(tmp_path)
        assert _flush(log, dec, "--root", str(root), "--pr-url", URL) == 0
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["appended"] == 1 and "pruned" in out
        _assert_proof_only(rd)


def test_flush_closes_the_open_round(tmp_path, capsys):
    root = tmp_path / "root"
    rd = _round(root, None)
    log, dec = _files(tmp_path)
    assert _flush(log, dec, "--root", str(root), "--pr-url", URL) == 0
    closed = json.loads((rd / "tail" / "closed.json").read_text(encoding="utf-8"))
    assert closed["closed_by"] == "flush" and closed["at"]
    assert not (rd / "a1" / "scratch.bin").exists()


def test_flush_without_root_only_flushes(tmp_path, capsys):
    root = tmp_path / "root"
    rd = _round(root, "two-stable")
    log, dec = _files(tmp_path)
    assert _flush(log, dec) == 0
    assert json.loads(capsys.readouterr().out) == {"appended": 1}
    assert (rd / "a1" / "scratch.bin").exists()


def test_flush_with_only_one_of_root_pr_url_refuses(tmp_path, capsys):
    root = tmp_path / "root"
    rd = _round(root, "two-stable")
    log, dec = _files(tmp_path)
    assert _flush(log, dec, "--root", str(root)) == 2
    assert _flush(log, dec, "--pr-url", URL) == 2
    assert (rd / "a1" / "scratch.bin").exists()


def test_stop_closes_an_open_round_and_reaps(tmp_path, capsys):
    root = tmp_path / "root"
    rd = _round(root, None)
    log, dec = _files(tmp_path)
    assert _stop(log, dec, "--root", str(root)) == 0
    _assert_proof_only(rd)
    closed = json.loads((rd / "tail" / "closed.json").read_text(encoding="utf-8"))
    assert closed["closed_by"] == "stop"


def test_migrated_root_repointed_and_pruned(tmp_path, capsys):
    new = tmp_path / "new"
    rd = _round(new, "two-stable", manifest_root=tmp_path / "old-gone")
    log, dec = _files(tmp_path)
    assert _flush(log, dec, "--root", str(new), "--pr-url", URL) == 0
    data = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    assert data["paths"]["proof_root"] == str(new)
    _assert_proof_only(rd)


def test_reap_while_open_leaves_scratch_then_stop_removes(tmp_path, capsys):
    root = tmp_path / "root"
    rd = _round(root, None)
    assert proof_reap.main(["prune", "--pr", "7", "--root", str(root)]) == 0
    assert (rd / "a1" / "scratch.bin").exists()
    log, dec = _files(tmp_path)
    assert _stop(log, dec, "--root", str(root)) == 0
    _assert_proof_only(rd)


def test_stop_without_root_uses_default_proof_root(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    rd = _round(root, None)
    monkeypatch.setattr(proof_root, "default_proof_root", lambda *a, **k: str(root))
    log, dec = _files(tmp_path)
    assert _stop(log, dec) == 0
    _assert_proof_only(rd)


def test_missing_rounds_dir_is_loud(tmp_path, capsys):
    res = proof_reap.close_and_prune(tmp_path / "nowhere", "7", closed_by="stop")
    assert "nowhere" in json.dumps(res)
    assert "nothing reaped" in capsys.readouterr().err
