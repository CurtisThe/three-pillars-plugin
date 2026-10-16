"""Tests for finder_round entry filters and aligned_replies (local-role-routing 6.3)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import angles  # noqa: E402
import finder_round  # noqa: E402


def _entry(name, **kw):
    return {"name": name, "role": "finder", "model": "local",
            "reply_path": f"{name}/reply.md", **kw}


def _manifest():
    return {"angles": [
        _entry("A", advisory=True),
        _entry("B", skipped="out-of-scope", advisory=True),
        _entry("C", advisory=True, unparseable=True),
        _entry("check", role="confirmer", model="opus"),
    ]}


def _names(entries):
    return [e["name"] for e in entries]


def test_parse_required_and_merge_entries():
    m = _manifest()
    assert _names(finder_round.parse_required(m)) == ["A", "check"]
    assert _names(finder_round.merge_entries(m)) == ["check"]


def test_claude_only_manifest_keeps_every_non_skipped():
    m = {"angles": [_entry("x"), _entry("y", skipped="out-of-scope"), _entry("z")]}
    assert _names(finder_round.parse_required(m)) == ["x", "z"]
    assert _names(finder_round.merge_entries(m)) == ["x", "z"]


def test_aligned_replies_in_manifest_order(tmp_path):
    m = _manifest()
    (tmp_path / "angles.json").write_text(json.dumps(m), encoding="utf-8")
    for n in ("A", "C", "check"):
        (tmp_path / n).mkdir()
        (tmp_path / n / "reply.md").write_text(f"reply-{n}", encoding="utf-8")
    pairs = finder_round.aligned_replies(tmp_path)
    assert [e["name"] for e, _ in pairs] == ["A", "B", "C", "check"]
    texts = [t for _, t in pairs]
    assert texts[0] == "reply-A"
    assert texts[1] == angles.SKIPPED_REPLY
    assert texts[2] == "reply-C"
    assert texts[3] == "reply-check"
