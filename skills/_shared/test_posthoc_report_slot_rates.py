"""Tests for posthoc_report's pass rate on cheap-slot rows (`slot` set): rated on `oracle`.

design: cheap-tier-local-routing 8.1 (detailed-design-posthoc.md, posthoc_report; impl-audit
retry). A cheap-slot row records its action (`accept` / `drop` / `escalate`) in `outcome` and its
pass/fail in `oracle` (cheap-dispatch.md step 4, `dispatch_log.SLOT_ORACLES`), the field
`cheap_ab_served` rates the same rows on. A `role: task` row (no `slot`) keeps `outcome == PASS`.
Same isolation as test_posthoc_report_rates.py: a tmp copy of the committed fixture repo,
`--utc-offset -06:00 --no-archive --json`, XDG_STATE_HOME = the fixture dir.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FIX = HERE / "fixtures" / "posthoc"
REPO = FIX / "repo"
LOG = FIX / "router.log"
pytestmark = pytest.mark.skipif(not REPO.is_dir(), reason="no posthoc fixture in this tree")

import cheap_ab_state  # noqa: E402
import posthoc_report  # noqa: E402
import posthoc_tables  # noqa: E402

DESIGN = "slot-design"
SLOT = "docs_draft"
_BASE = {"agent": "tp-drafter", "reason": f"cheap-tier {SLOT}", "role": SLOT, "slot": SLOT,
         "requested_rung": "local-medium", "lease_wait_s": 0, "escalated": False}
# One served local, two sonnet-mirror; two accept + oracle pass, one escalate + oracle fail.
SLOT_ROWS = [
    dict(_BASE, rung="local-medium", served_by="local", outcome="accept", oracle="pass",
         started_at="2026-10-03T10:00:00Z", ended_at="2026-10-03T10:01:00Z", wall_s=60.0),
    dict(_BASE, rung="sonnet-medium", served_by="sonnet", outcome="accept", oracle="pass",
         fallback="background-spawn-failed", started_at="2026-10-03T10:05:00Z"),
    dict(_BASE, rung="sonnet-medium", served_by="sonnet", outcome="escalate", oracle="fail",
         escalated=True, fallback="background-spawn-failed", started_at="2026-10-03T10:10:00Z"),
]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(FIX))
    monkeypatch.delenv("TP_LOCAL_LOG", raising=False)
    monkeypatch.setattr(cheap_ab_state, "worktree_roots", lambda root: [Path(root).resolve()])


def _report(capsys, root) -> dict:
    code = posthoc_report.main(["report", "--root", str(root), "--router-log", str(LOG),
                                "--utc-offset", "-06:00", "--no-archive", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    return json.loads(out)


def _repo_with(tmp_path, rows) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REPO, root)
    path = root / "three-pillars-docs" / "tp-designs" / DESIGN / "dispatch-telemetry.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    return root


def _slot_group(report) -> dict:
    found = [g for g in report["groups"] if g["role"] == SLOT]
    assert len(found) == 1, report["groups"]
    return found[0]


def _counts(rate) -> tuple:
    return rate["pass"], rate["n"]


def test_slot_rows_are_rated_on_oracle_not_outcome(capsys, tmp_path):
    group = _slot_group(_report(capsys, _repo_with(tmp_path, SLOT_ROWS)))
    assert (group["role"], group["rung"]) == (SLOT, "local-medium")
    assert (group["n"], group["spawned"]) == (3, 3)
    assert _counts(group["pass_rate"]["overall"]) == (2, 3)
    assert group["pass_rate"]["overall"]["rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert _counts(group["pass_rate"]["adjusted"]) == (2, 3)


@pytest.mark.parametrize("oracle", [None, "unrecorded"])
def test_a_slot_row_without_a_pass_oracle_is_never_a_pass(capsys, tmp_path, oracle):
    row = dict(SLOT_ROWS[0], outcome="pass")
    if oracle == "unrecorded":
        del row["oracle"]
    else:
        row["oracle"] = None
    group = _slot_group(_report(capsys, _repo_with(tmp_path, [row])))
    assert _counts(group["pass_rate"]["overall"]) == (0, 1)


# The action (`outcome`) and the pass (`oracle`) cross over: only `oracle == "pass"` passes.
_MISSING = object()
CROSSED = [("accept", "fail", 0), ("accept", None, 0), ("accept", _MISSING, 0),
           ("escalate", "pass", 1), ("drop", "pass", 1), ("drop", None, 0)]


@pytest.mark.parametrize("outcome, oracle, passes", CROSSED,
                         ids=[f"{o}-{'missing' if x is _MISSING else x}" for o, x, _ in CROSSED])
def test_a_slot_rows_pass_is_its_oracle_never_its_action(capsys, tmp_path, outcome, oracle,
                                                          passes):
    row = dict(SLOT_ROWS[0], outcome=outcome, oracle=oracle)
    if oracle is _MISSING:
        del row["oracle"]
    group = _slot_group(_report(capsys, _repo_with(tmp_path, [row])))
    got = _counts(group["pass_rate"]["overall"])
    assert got == (passes, 1), (
        f"slot pass not read from oracle: outcome={outcome} oracle={row.get('oracle')!r} "
        f"rung={row['rung']} rated {got}")


def test_crossed_rows_rate_on_oracle_in_every_column(capsys, tmp_path):
    """accept+fail, escalate+pass, accept+null: one oracle pass of three, whatever the action."""
    rows = [dict(SLOT_ROWS[0], outcome="accept", oracle="fail"),
            dict(SLOT_ROWS[1], outcome="escalate", oracle="pass"),
            dict(SLOT_ROWS[2], outcome="accept", oracle=None)]
    group = _slot_group(_report(capsys, _repo_with(tmp_path, rows)))
    got = tuple(_counts(group["pass_rate"][k]) for k in ("overall", "adjusted"))
    assert got == ((1, 3), (1, 3)), f"slot pass not read from oracle: rung=local-medium {got}"


def _enriched(row, label) -> dict:
    joined = {"label": label, "served_rung": row["served_by"], "router_output_tokens": 0, "fallback": None}
    return dict(row, design=DESIGN, joined=joined, spawned=True, cause=None, pre_198=False)


def test_clean_and_contended_read_the_oracle_too():
    rows = [_enriched(r, label) for r, label in zip(SLOT_ROWS, ("clean", "contended", "clean"))]
    (group,) = posthoc_tables.groups(rows)
    rates = group["pass_rate"]
    assert (_counts(rates["clean"]), _counts(rates["contended"])) == ((1, 2), (1, 1))


def test_a_task_row_keeps_outcome_pass():
    task = {"role": "task", "rung": "local-medium", "served_by": "local", "task_id": "9.9",
            "started_at": "2026-10-03T11:00:00Z"}
    rows = [_enriched(dict(task, outcome="PASS", oracle="fail"), "clean"),
            _enriched(dict(task, outcome="FAIL", oracle="pass"), "clean")]
    (group,) = posthoc_tables.groups(rows)
    assert _counts(group["pass_rate"]["overall"]) == (1, 2)
    assert posthoc_tables.attempts_to_pass(rows)["local-medium"]["passed"] == 1
