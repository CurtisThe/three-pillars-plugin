"""Tests for the context_scout CLI (design: local-role-routing, Task 5.3)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_scout  # noqa: E402


def _cited(n):
    return "\n".join(f"fact {i} (docs/file{i}.md:{i})" for i in range(n))


def _put(monkeypatch, out_dir, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    return context_scout.main(["put", "--out-dir", str(out_dir)])


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_prompt_prints_scout_prompt(tmp_path, capsys):
    rc = context_scout.main(["prompt", "--design-dir", str(tmp_path / "nodesign"),
                             "--base", "B1", "--head", "H1", "--out-dir", str(tmp_path / "O")])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == context_scout.prompt(str(tmp_path / "nodesign"), "B1", "H1",
                                               str(tmp_path / "O")).strip()
    assert "B1...H1" in out


def test_put_writes_pair_creating_dir(tmp_path, monkeypatch):
    out = tmp_path / "O"
    block = _cited(30)
    assert _put(monkeypatch, out, {"block": block, "files": ["a.py"]}) == 0
    assert _read(out / "rulings.md") == context_scout.trim(block)
    assert json.loads(_read(out / "rulings.json")) == {"files": ["a.py"]}
    assert sorted(p.name for p in out.iterdir()) == ["rulings.json", "rulings.md"]


def test_put_bad_payload_leaves_prior_pair_identical(tmp_path, monkeypatch):
    out = tmp_path / "O"
    assert _put(monkeypatch, out, {"block": _cited(3), "files": ["a.py"]}) == 0
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    for bad in ("not json", {"block": 5, "files": []}, {"block": "x", "files": "a.py"},
                {"block": "x", "files": [1]}, [1, 2], {"files": []}):
        assert _put(monkeypatch, out, bad) != 0
        assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_put_bad_payload_creates_nothing(tmp_path, monkeypatch):
    out = tmp_path / "O"
    assert _put(monkeypatch, out, "not json") != 0
    assert not out.exists() or not any(out.iterdir())


def test_needs_refresh_exit_codes(tmp_path, monkeypatch):
    out = tmp_path / "O"
    _put(monkeypatch, out, {"block": _cited(2), "files": ["a.py"]})
    meta = str(out / "rulings.json")
    assert context_scout.main(["needs-refresh", "--meta", meta, "--touched", "a.py,b.py"]) == 0
    assert context_scout.main(["needs-refresh", "--meta", meta, "--touched", "a.py"]) == 1


def test_needs_refresh_missing_or_malformed_meta_is_refresh(tmp_path):
    assert context_scout.main(["needs-refresh", "--meta", str(tmp_path / "none.json"),
                               "--touched", "a.py"]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert context_scout.main(["needs-refresh", "--meta", str(bad), "--touched", "a.py"]) == 0


def test_slot_lost_block_does_not_loop(tmp_path, monkeypatch):
    out = tmp_path / "O"
    assert _put(monkeypatch, out, {"block": "scout unavailable: slot-lost",
                                   "files": ["a.py"]}) == 0
    assert _read(out / "rulings.md") == "scout unavailable: slot-lost"
    assert json.loads(_read(out / "rulings.json")) == {"files": ["a.py"]}
    assert context_scout.main(["needs-refresh", "--meta", str(out / "rulings.json"),
                               "--touched", "a.py"]) == 1
