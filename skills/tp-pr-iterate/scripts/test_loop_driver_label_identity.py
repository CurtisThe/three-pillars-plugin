"""test_loop_driver_label_identity.py — the loop's label writes forward the round's config.

design: review-proof-ambient-gh-identity, Task 1.5 (behaviours B1, B2 at the loop driver)

`loop_driver._ensure_pr_label` / `_remove_pr_label` default `config=DISCOVER` and hand it to the
`label_manager` functions (which run the writes as the bot). `run_round`'s `_do_label` /
`_do_unlabel` pass the round's `config`; a `BotAuthUnavailable` is named in one printed line
(no token, no exception text) instead of being dropped silently, and the round still
completes (label hygiene stays fail-open). Hermetic: the `label_manager` functions are
monkeypatched recorders; no live `gh`.

Run with: pytest skills/tp-pr-iterate/scripts/test_loop_driver_label_identity.py -q
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent.parent / "tp-pr-fix" / "scripts", HERE.parent.parent / "_shared"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import automation_identity as ai  # noqa: E402
import label_manager  # noqa: E402
import loop_driver  # noqa: E402

PR = "https://github.com/owner/repo/pull/1"
BOT = "CurtisTheBot"
CFG = {"github": {"pr_author_account": BOT, "used_for": "all-prs"}}
ROUND_CFG = {**CFG, "review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}
READY = "tp:ready-for-human-merge"
ATTENTION = "tp:needs-human-attention"
DO_NOT_MERGE = "tp:do-not-merge-yet"


class Recorder:
    """A `label_manager` stand-in: records `(pr, label, config)`; optionally raises."""

    def __init__(self, exc=None):
        self.calls: list = []
        self.exc = exc

    def __call__(self, pr_url, label, config=ai.DISCOVER):
        self.calls.append((pr_url, label, config))
        if self.exc is not None:
            raise self.exc


# ------------------------------------------------------------ the wrappers forward the config


def test_the_ensure_wrapper_passes_its_config_to_label_manager(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(label_manager, "ensure_pr_label", rec)
    loop_driver._ensure_pr_label(PR, "x", config=CFG)
    assert rec.calls == [(PR, "x", CFG)]


def test_the_remove_wrapper_passes_its_config_to_label_manager(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(label_manager, "remove_pr_label", rec)
    loop_driver._remove_pr_label(PR, "x", config=CFG)
    assert rec.calls == [(PR, "x", CFG)]


def test_an_explicit_none_stays_the_ambient_path(monkeypatch):
    ens, rem = Recorder(), Recorder()
    monkeypatch.setattr(label_manager, "ensure_pr_label", ens)
    monkeypatch.setattr(label_manager, "remove_pr_label", rem)
    loop_driver._ensure_pr_label(PR, "x", config=None)
    loop_driver._remove_pr_label(PR, "x", config=None)
    assert ens.calls == [(PR, "x", None)] and rem.calls == [(PR, "x", None)]


def test_the_wrappers_default_to_discovery(monkeypatch):
    ens, rem = Recorder(), Recorder()
    monkeypatch.setattr(label_manager, "ensure_pr_label", ens)
    monkeypatch.setattr(label_manager, "remove_pr_label", rem)
    loop_driver._ensure_pr_label(PR, "x")
    loop_driver._remove_pr_label(PR, "x")
    assert ens.calls[0][2] is ai.DISCOVER and rem.calls[0][2] is ai.DISCOVER


# ------------------------------------------------------------ run_round forwards the round's config


def _converging_round(**kw):
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = {
        "phase": "awaiting-copilot", "iteration": 1, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": (now - timedelta(hours=1)).isoformat(),
        "transitions": [], "cumulative_diff_lines": 0, "original_diff_lines": 100,
        "consecutive_structural_rounds": 0, "last_loop_sha": None,
        "last_comment_seen_at": None, "last_verdict": "minor-only",
        "seen_thread_ids": [], "last_codereview_head_sha": "head1",
        "last_codereview_findings": [],
    }
    return loop_driver.run_round(
        state, head_sha="head1", codereview_findings=[], reviewed=None,
        unresolved_actionable=0, ci_rollup=[], now=now, pr_url=PR, **kw)


def test_run_round_forwards_its_config_to_both_label_calls(monkeypatch, tmp_path):
    ens, rem = Recorder(), Recorder()
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", ens)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", rem)
    result = _converging_round(config=ROUND_CFG, decisions_path=tmp_path / "decisions.md")
    assert result["terminal"] in ("two-stable [code-review-only]", "two-stable")
    assert ens.calls == [(PR, READY, ROUND_CFG)]
    assert rem.calls == [(PR, ATTENTION, ROUND_CFG), (PR, DO_NOT_MERGE, ROUND_CFG)]


def test_a_bot_auth_failure_is_named_in_one_line_per_label_and_the_round_completes(
        monkeypatch, tmp_path, capsys):
    boom = ai.BotAuthUnavailable("account tok-bot-secret is not available")
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", Recorder(exc=boom))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", Recorder(exc=boom))
    result = _converging_round(config=ROUND_CFG, decisions_path=tmp_path / "decisions.md")
    assert result["terminal"] in ("two-stable [code-review-only]", "two-stable")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 3
    assert READY in lines[0] and ATTENTION in lines[1] and DO_NOT_MERGE in lines[2]
    assert all("tok-bot-secret" not in ln for ln in lines)


def test_another_label_failure_stays_silent_and_fail_open(monkeypatch, tmp_path, capsys):
    boom = RuntimeError("gh exploded")
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", Recorder(exc=boom))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", Recorder(exc=boom))
    result = _converging_round(config=ROUND_CFG, decisions_path=tmp_path / "decisions.md")
    assert result["terminal"] in ("two-stable [code-review-only]", "two-stable")
    assert capsys.readouterr().out.strip() == ""


def test_an_injected_label_fn_still_wins_and_never_sees_a_config(tmp_path):
    seen: list = []
    _converging_round(
        config=ROUND_CFG, decisions_path=tmp_path / "decisions.md",
        label_fn=lambda pr, lbl: seen.append(("+", lbl)),
        unlabel_fn=lambda pr, lbl: seen.append(("-", lbl)))
    assert seen == [("+", READY), ("-", ATTENTION), ("-", DO_NOT_MERGE)]
