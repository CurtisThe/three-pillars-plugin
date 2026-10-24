"""test_carry_check_handres.py — review-convergence 10.2, Behavior 15: a base-sync merge
whose ONLY hand-resolution is a living doc carries the review proof when the committed
config's key is true, and refuses (with the reason printed) when it is false.

Fixture: `attack_matrix.build_attack_case("attack2_hand_resolution", ...)` — RECLASSIFIED
carried-positive for the proof by Task 10.1. The carry config is committed ON TOP of the
merge (repo HEAD moves), so `carry_check` reads it from HEAD exactly as the loop does.
With HEAD moved off the base line, the oracle seam is re-pointed at the fixture's own
origin (a checkout of the trusted base line) — the documented `_oracle_code_dir` seam.

Run with: pytest skills/_shared/test_carry_check_handres.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "carry_check.py"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import review_proof  # noqa: E402
from attack_matrix import build_attack_case  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"
NOT_TRUE = ("carry off: review.approval_survives_safe_base_sync is not true "
            "in the committed config")


def _config(key_true: bool) -> dict:
    # The neutral merge carry (basesync-docs-only-carry) would carry this docs-only merge whatever
    # the base-sync key says, so it is off here: these cases isolate the base-sync key.
    return {"schema_version": 1,
            "review": {"approval_survives_safe_base_sync": key_true,
                       "base_sync_carry_max_chain": 2, "proof_neutral_carry": False}}


def _commit_config(scenario, cfg: dict) -> None:
    """Commit `.three-pillars/config.json` ON TOP of the fixture's merge commit —
    the design branch is checked back out first (`_seat` left the repo on base_ref)."""
    scenario.git("checkout", "--quiet", scenario.design_branch, check=True)
    cfg_dir = scenario.repo_dir / ".three-pillars"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    scenario.git("add", "--", ".three-pillars/config.json", check=True)
    scenario.git("commit", "-q", "-m", "fixture: commit carry config at HEAD", check=True)


def _digest_for(head: str) -> str:
    meta = {"base": "base000", "head": head, "files_changed": 3,
            "insertions": 5, "deletions": 1, "degraded": False, "reason": None}
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _build(tmp_path, monkeypatch, key_true: bool):
    """Returns `(scenario, head_oid, runners)` — the digest comment is built for THIS
    case's anchor, captured in the closure (no cross-case state)."""
    import base_sync_oracle
    scenario, head_oid, anchor = build_attack_case("attack2_hand_resolution",
                                                   tmp_path, monkeypatch)
    _commit_config(scenario, _config(key_true))
    # HEAD now carries the config commit, so the repo checkout is off the base line;
    # the oracle runs from the fixture's origin — a checkout OF the trusted base line.
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: scenario.origin_dir)
    runners = {
        "comments_fn": lambda _u, a=anchor: [{"author": AUTHOR, "body": _digest_for(a)}],
        "self_login_fn": lambda: AUTHOR,
        "derive_base_ref_fn": lambda _u, b=scenario.base_ref: b,
    }
    return scenario, head_oid, runners


def test_livingdoc_handres_merge_with_key_true_is_carried(tmp_path, monkeypatch):
    import carry_check
    scenario, head_oid, runners = _build(tmp_path, monkeypatch, key_true=True)

    out = carry_check.check(str(scenario.repo_dir), PR, head_oid, runners=runners)
    assert out["carried"] is True, out
    assert out["reason"] == "carry on"
    assert "proof comment carried across 1 certified base-sync merge(s)" in out["detail"]


def test_livingdoc_handres_merge_with_key_false_is_not_carried(tmp_path, monkeypatch):
    import carry_check
    scenario, head_oid, runners = _build(tmp_path, monkeypatch, key_true=False)

    out = carry_check.check(str(scenario.repo_dir), PR, head_oid, runners=runners)
    assert out["carried"] is False, out
    assert out["reason"] == NOT_TRUE
    assert out["detail"] == ""


def test_cli_prints_the_key_false_reason_with_exit_1(tmp_path, monkeypatch):
    scenario, _head_oid, _runners = _build(tmp_path, monkeypatch, key_true=False)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(scenario.repo_dir),
         "--pr-url", PR],
        capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert result.stdout.strip() == NOT_TRUE
