"""Tests for round_scratch.py — round/angle dirs, manifest, replies, flush, safe_remove.

design: iterate-convergence-budget (Task 6.2)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402
import review_merge  # noqa: E402
import round_scratch as rs  # noqa: E402

PR = "https://github.com/o/r/pull/42"
CLEAN = '{"findings": []}'


def _prep(root, **kw):
    kw.setdefault("angles", angles.DEFAULT_ANGLES)
    return rs.prepare(root, PR, kw.pop("angles"), base="b0", head="h1", effort="high",
                      state_path=str(root / "iterate-state.42.v1.json"),
                      log_path=str(root / "iterate-log.42.md"), **kw)


def _envelope(round_dir, action="fix"):
    (round_dir / "tail").mkdir(exist_ok=True)
    (round_dir / "tail" / "envelope.json").write_text(
        json.dumps({"action": action}), encoding="utf-8")


def test_first_round_is_r1_with_angle_dirs(tmp_path):
    r = _prep(tmp_path)
    assert r == tmp_path / "rounds" / "42" / "r1"
    for a in angles.DEFAULT_ANGLES:
        assert (r / a["name"]).is_dir()
    assert (r / "tail").is_dir()


def test_manifest_shape(tmp_path):
    r = _prep(tmp_path)
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    assert m["pr_url"] == PR and m["round"] == 1 and m["ordinal"] == "r1"
    assert m["base"] == "b0" and m["head"] == "h1"
    assert m["paths"] == {"proof_root": str(tmp_path),
                          "state_path": str(tmp_path / "iterate-state.42.v1.json"),
                          "log_path": str(tmp_path / "iterate-log.42.md")}
    names = [e["name"] for e in m["angles"]]
    assert names == [a["name"] for a in angles.DEFAULT_ANGLES]
    e = m["angles"][0]
    assert e["role"] == "confirmer" and e["model"] == "opus" and e["tier"] == "claude"
    assert e["reply_path"] == str(r / e["name"] / "reply.md")
    assert e["reply_path"] in e["prompt"] and angles.REVIEW_BAR in e["prompt"]


def test_manifest_dispatch_model_alias(tmp_path):
    """M3: a `claude-<family>-…` id and a bare alias both dispatch as `opus`."""
    angles_list = [{"name": "a", "role": "confirmer", "model": "claude-opus-4-1",
                    "prompt": "p"},
                   {"name": "b", "role": "confirmer", "model": "Opus", "prompt": "p"}]
    r = _prep(tmp_path, angles=angles_list)
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    by_name = {e["name"]: e for e in m["angles"]}
    assert by_name["a"]["dispatch_model"] == "opus"
    assert by_name["b"]["dispatch_model"] == "opus"
    assert "skipped" not in by_name["a"]
    skipped = [{"name": "s", "role": "finder", "model": "qwen", "prompt": "p",
                "skipped": "local backend absent"}]
    m2 = json.loads((_prep(tmp_path / "s", angles=skipped) / "angles.json").read_text(encoding="utf-8"))
    assert m2["angles"][0]["skipped"] == "local backend absent"
    assert m2["angles"][0]["dispatch_model"] is None


def test_next_round_after_tail(tmp_path):
    r1 = _prep(tmp_path)
    _envelope(r1)
    r2 = _prep(tmp_path)
    assert r2.name == "r2" and r1.is_dir()
    assert json.loads((r2 / "angles.json").read_text(encoding="utf-8"))["round"] == 2


def test_round_number_from_dirs_not_memory(tmp_path):
    (tmp_path / "rounds" / "42" / "r7" / "tail").mkdir(parents=True)
    _envelope(tmp_path / "rounds" / "42" / "r7", "noop")
    assert _prep(tmp_path).name == "r8"


def test_rerun_review_makes_dot_one(tmp_path):
    r1 = _prep(tmp_path)
    _envelope(r1, "rerun-review")
    r = _prep(tmp_path)
    assert r.name == "r1.1"
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    assert m["round"] == 1 and m["ordinal"] == "r1.1"
    _envelope(r, "fix")
    assert _prep(tmp_path).name == "r2"


def test_second_rerun_raises(tmp_path):
    r1 = _prep(tmp_path)
    _envelope(r1, "rerun-review")
    r = _prep(tmp_path)
    _envelope(r, "rerun-review")
    with pytest.raises(rs.RerunLimit):
        _prep(tmp_path)


def test_missing_envelope_raises_tail_failed(tmp_path):
    _prep(tmp_path)
    with pytest.raises(rs.TailFailed):
        _prep(tmp_path)


def test_closed_without_envelope_gives_next_round(tmp_path):
    r1 = _prep(tmp_path)
    (r1 / "tail").mkdir(exist_ok=True)
    (r1 / "tail" / "closed.json").write_text("{}", encoding="utf-8")
    assert not (r1 / "tail" / "envelope.json").exists()
    assert _prep(tmp_path).name == "r2"


def test_invalid_envelope_raises_tail_failed(tmp_path):
    r1 = _prep(tmp_path)
    (r1 / "tail" / "envelope.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(rs.TailFailed):
        _prep(tmp_path)


def test_unsafe_angle_name_refused(tmp_path):
    bad = [{"name": "../x", "prompt": "p", "role": "confirmer", "model": "opus"}]
    with pytest.raises(ValueError):
        _prep(tmp_path, angles=bad)


def test_read_replies_clean(tmp_path):
    r = _prep(tmp_path)
    for a in angles.DEFAULT_ANGLES:
        (r / a["name"] / "reply.md").write_text(CLEAN, encoding="utf-8")
    assert review_merge.merge_codereview_angles(rs.read_replies(r)) == []


def test_skipped_local_finder_reads_clean(tmp_path):
    """L125: a skipped local finder is never dispatched, so its missing reply reads as
    clean in both readers, never as the sentinel that would block every round."""
    import reproduce
    loc = {"name": "loc", "role": "finder", "model": "qwen3-coder", "prompt": "p",
           "skipped": "local backend absent"}
    r = _prep(tmp_path, angles=[*angles.DEFAULT_ANGLES, loc])
    for a in angles.DEFAULT_ANGLES:
        (r / a["name"] / "reply.md").write_text(CLEAN, encoding="utf-8")
    assert review_merge.merge_codereview_angles(rs.read_replies(r)) == []
    entry = json.loads((r / "angles.json").read_text(encoding="utf-8"))["angles"][-1]
    assert reproduce._read_reply(r, entry) == angles.SKIPPED_REPLY


def test_clobbered_sibling_blocks(tmp_path):
    """Behavior 11: an angle deleting a sibling's dir yields a sentinel, not clean."""
    import shutil
    r = _prep(tmp_path)
    for a in angles.DEFAULT_ANGLES:
        (r / a["name"] / "reply.md").write_text(CLEAN, encoding="utf-8")
    shutil.rmtree(r / "edge-cases")
    findings = review_merge.merge_codereview_angles(rs.read_replies(r))
    assert review_merge.is_degraded_review(findings)


def test_empty_reply_blocks(tmp_path):
    r = _prep(tmp_path)
    (r / "correctness-leak" / "reply.md").write_text("", encoding="utf-8")
    findings = review_merge.merge_codereview_angles(rs.read_replies(r))
    assert review_merge.is_degraded_review(findings)


def test_flush_log_appends_once_and_truncates(tmp_path):
    log, dec = tmp_path / "log.md", tmp_path / "decisions.md"
    dec.write_text("# decisions\n", encoding="utf-8")
    log.write_text("line one\nline two\n", encoding="utf-8")
    assert rs.flush_log(log, dec) == 2
    assert log.read_text(encoding="utf-8") == ""
    assert rs.flush_log(log, dec) == 0
    log.write_text("line three", encoding="utf-8")
    assert rs.flush_log(log, dec) == 1
    assert dec.read_text(encoding="utf-8") == "# decisions\nline one\nline two\nline three\n"


def test_flush_log_missing_log_is_noop(tmp_path):
    dec = tmp_path / "decisions.md"
    assert rs.flush_log(tmp_path / "absent.md", dec) == 0
    assert not dec.exists()


def test_safe_remove_round_dir(tmp_path):
    r = _prep(tmp_path)
    rs.safe_remove(r, tmp_path)
    assert not r.exists()


@pytest.mark.parametrize("which", ["sibling", "parent", "owner", "state", "angle"])
def test_safe_remove_refusals(tmp_path, which):
    owner = tmp_path / "proof"
    owner.mkdir()
    r = _prep(owner)
    state = owner / "iterate-state.42.v1.json"
    state.write_text("{}", encoding="utf-8")
    sibling = tmp_path / "r9"
    sibling.mkdir()
    target = {"sibling": sibling, "parent": tmp_path, "owner": owner, "state": state,
              "angle": r / "edge-cases"}[which]
    with pytest.raises(rs.RemoveRefused):
        rs.safe_remove(target, owner)
    assert target.exists()


def test_instructions_present_from_status(tmp_path):
    """8.3: the round prompt names the instructions file only when the repo has one."""
    token = ".github/review-instructions.md"
    with_repo = tmp_path / "repo"
    (with_repo / ".github").mkdir(parents=True)
    (with_repo / ".github" / "review-instructions.md").write_text("bar\n", encoding="utf-8")
    r = _prep(tmp_path / "root-with", repo=str(with_repo))
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    assert all(token in e["prompt"] for e in m["angles"])
    bare_repo = tmp_path / "repo-bare"
    bare_repo.mkdir()
    r2 = _prep(tmp_path / "root-bare", repo=str(bare_repo))
    m2 = json.loads((r2 / "angles.json").read_text(encoding="utf-8"))
    assert all(token not in e["prompt"] for e in m2["angles"])
    assert all(angles.REVIEW_BAR in e["prompt"] for e in m2["angles"])


def test_safe_remove_symlink_escape(tmp_path):
    owner = tmp_path / "proof"
    rounds = owner / "rounds" / "42"
    rounds.mkdir(parents=True)
    outside = tmp_path / "r5"
    outside.mkdir()
    link = rounds / "r5"
    os.symlink(outside, link)
    with pytest.raises(rs.RemoveRefused):
        rs.safe_remove(link, owner)
    assert outside.is_dir()
