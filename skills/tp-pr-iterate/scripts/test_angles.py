"""Tests for angles.py — angles as data, the Opus rule, the confirmer rule, prompts.

design: iterate-convergence-budget (Task 6.1)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402

BAR = ("Only a demonstrated shipped-behaviour defect with a reproducer blocks; mutation "
       "survivors, test-tightening, exotic env, lint-guard bypasses, style and perf are "
       "non-blocking notes.")


def _cfg(*entries):
    return {"review": {"angles": list(entries)}}


def _angle(name="a", role="confirmer", model="opus", prompt="look"):
    return {"name": name, "prompt": prompt, "role": role, "model": model}


def test_default_angles_three_opus_confirmers():
    names = [a["name"] for a in angles.DEFAULT_ANGLES]
    assert names == ["correctness-leak", "edge-cases", "test-quality"]
    assert all(a["role"] == "confirmer" and a["model"] == "opus" for a in angles.DEFAULT_ANGLES)


def test_test_quality_reworded():
    tq = next(a for a in angles.DEFAULT_ANGLES if a["name"] == "test-quality")
    assert "a shipped behaviour no test guards, shown by a concrete failing input" in tq["prompt"]


def test_load_angles_default_when_absent():
    assert angles.load_angles(None) == angles.DEFAULT_ANGLES
    assert angles.load_angles({}) == angles.DEFAULT_ANGLES
    assert angles.load_angles({"review": {}}) == angles.DEFAULT_ANGLES


def test_load_angles_returns_copy():
    got = angles.load_angles({})
    got[0]["name"] = "mutated"
    assert angles.DEFAULT_ANGLES[0]["name"] == "correctness-leak"


def test_load_angles_custom():
    cfg = _cfg(_angle("x"), _angle("y", role="finder", model="local-llm"))
    assert [a["name"] for a in angles.load_angles(cfg)] == ["x", "y"]


@pytest.mark.parametrize("bad", [
    _angle(role="judge"),
    _angle(name=""),
    _angle(model=""),
    _angle(model="sonnet"),
    _angle(model="claude-sonnet-4-6"),
    _angle(model="haiku"),
    _angle(model="Claude-Haiku-4-5", role="finder"),
    _angle(model="local-llm", role="confirmer"),
])
def test_load_angles_rejects(bad):
    with pytest.raises(ValueError):
        angles.load_angles(_cfg(bad))


def test_load_angles_rejects_duplicates():
    with pytest.raises(ValueError):
        angles.load_angles(_cfg(_angle("a"), _angle("a")))


def test_load_angles_rejects_non_list():
    with pytest.raises(ValueError):
        angles.load_angles({"review": {"angles": "opus"}})


@pytest.mark.parametrize("model,expected", [
    ("opus", "claude"), ("sonnet", "claude"), ("haiku", "claude"),
    ("claude-opus-4-1", "claude"), ("Opus", "claude"), ("qwen-coder", "local"),
])
def test_tier(model, expected):
    assert angles.tier({"model": model}) == expected


def _manifest(tmp_path, entries):
    out = []
    for i, (role, model, reply) in enumerate(entries):
        path = tmp_path / f"a{i}" / "reply.md"
        if reply is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(reply, encoding="utf-8")
        out.append({"name": f"a{i}", "role": role, "model": model,
                    "tier": angles.tier({"model": model}), "reply_path": str(path)})
    return {"angles": out}


def test_confirmer_ran_true(tmp_path):
    m = _manifest(tmp_path, [("confirmer", "opus", "```json\n[]\n```")])
    assert angles.confirmer_ran(m) is True


def test_confirmer_ran_finder_only_false(tmp_path):
    m = _manifest(tmp_path, [("finder", "local-llm", "```json\n[]\n```"),
                             ("finder", "opus", "```json\n[]\n```")])
    assert angles.confirmer_ran(m) is False


def test_confirmer_ran_unparseable_reply_false(tmp_path):
    m = _manifest(tmp_path, [("confirmer", "opus", "no json here"),
                             ("confirmer", "opus", None)])
    assert angles.confirmer_ran(m) is False


def test_confirmer_ran_relative_reply_path(tmp_path):
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "reply.md").write_text("```json\n[]\n```", encoding="utf-8")
    m = {"angles": [{"name": "c", "role": "confirmer", "model": "opus", "tier": "claude",
                     "reply_path": "c/reply.md"}]}
    assert angles.confirmer_ran(m, round_dir=tmp_path) is True


def test_digest_labels():
    m = {"angles": [{"name": "edge", "role": "confirmer", "model": "opus"},
                    {"name": "scan", "role": "finder", "model": "qwen"}]}
    assert angles.digest_labels(m, {"edge": 2}) == [("edge[opus/confirmer]", 2),
                                                    ("scan[qwen/finder]", 0)]


def test_build_prompt_contents():
    a = angles.DEFAULT_ANGLES[0]
    p = angles.build_prompt(a, base="b0", head="h1", effort="max", reply_path="/r/x/reply.md")
    assert BAR in p
    assert "b0...h1" in p and "max" in p
    assert "/r/x/reply.md" in p and "touch nothing else" in p
    for key in ("file", "line_range", "summary", "class", "blocking", "reproducer"):
        assert key in p
    assert '{"angle","findings","blocking","reply_path"}' in p
    assert a["prompt"] in p
