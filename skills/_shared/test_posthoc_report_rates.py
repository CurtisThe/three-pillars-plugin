"""Tests for posthoc_report's rates: pass rate, clean/contended split, runaways, attempts, wall time.

design: cheap-tier-local-routing 8.1 (detailed-design-posthoc.md, posthoc_report; plan Task 8.1).
Same isolation as test_posthoc_report.py: the committed fixture excerpt (fixtures/posthoc/) with
`--utc-offset -06:00 --no-archive --json`, XDG_STATE_HOME = the fixture dir, worktree discovery
confined to the given root; variants edit a tmp copy of the fixture repo. The fixture's
local-medium group holds four spawned rows (PASS 243.5 s, PASS 53.4 s router-fallback, FAIL
295.7 s router-fallback, FAIL 55.5 s local whose `[tier]` cause is a pre-#198
`runaway: generation client-reset`) and two never-spawned `unavailable` rows.
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

DESIGN = "fixture-design"
RESET = "runaway: generation client-reset mid-response"
ROW7_START, ROW7_END = "2026-10-01T18:32:22.316000Z", "2026-10-01T18:33:17.782000Z"
RUNAWAY_CAUSES = ("reset", "generation", "wall-clock", "runaway-other")
# A row of agent a8a5f599 across the ownership switch (router 12:22-12:25): a445337d's `-> local`.
SWITCH_ROW = {"role": "task", "rung": "local-medium", "outcome": "PASS", "served_by": "local",
              "agent8": "a8a5f599", "task_id": "4.1", "phase": "4", "wall_s": 196.0,
              "started_at": "2026-10-01T18:22:02Z", "ended_at": "2026-10-01T18:25:18Z"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(FIX))
    monkeypatch.delenv("TP_LOCAL_LOG", raising=False)
    monkeypatch.setattr(cheap_ab_state, "worktree_roots", lambda root: [Path(root).resolve()])


def _report(capsys, root=REPO) -> dict:
    code = posthoc_report.main(["report", "--root", str(root), "--router-log", str(LOG),
                                "--utc-offset", "-06:00", "--no-archive", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    return json.loads(out)


def _group(report, role="task", rung="local-medium") -> dict:
    found = [g for g in report["groups"] if (g["role"], g["rung"]) == (role, rung)]
    assert len(found) == 1, report["groups"]
    return found[0]


def _copy(tmp_path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(REPO, dest)
    return dest


def _design_file(root, name, design=DESIGN) -> Path:
    return Path(root) / "three-pillars-docs" / "tp-designs" / design / name


def _append(root, row, design=DESIGN) -> None:
    path = _design_file(root, "dispatch-telemetry.ndjson", design)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _edit(root, name, old, new) -> None:
    path = _design_file(root, name)
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def _counts(rate) -> tuple:
    return rate["pass"], rate["n"]


# --- pass rate: spawned rows only -----------------------------------------------------------

def test_pass_rate_counts_spawned_rows_only(capsys):
    rates = _group(_report(capsys))["pass_rate"]
    assert _counts(rates["overall"]) == (2, 4)
    assert rates["overall"]["rate"] == pytest.approx(0.5)
    never = _group(_report(capsys), rung="local-xhigh")["pass_rate"]["overall"]
    assert _counts(never) == (0, 0)
    assert never["rate"] is None


def test_unavailable_rows_never_move_the_rate(capsys, tmp_path):
    before = _group(_report(capsys))["pass_rate"]
    root = _copy(tmp_path)
    for n in range(3):
        _append(root, {"role": "task", "rung": "local-medium", "outcome": "unavailable", "served_by": None,
                       "fallback": "local-busy", "task_id": f"6.{n}", "phase": "6",
                       "started_at": f"2026-09-30T06:0{n}:00Z", "ended_at": f"2026-09-30T06:0{n}:09Z"})
    after = _group(_report(capsys, root))
    assert after["pass_rate"] == before
    assert after["served"]["never-spawned"] == 5


# --- clean / contended split ----------------------------------------------------------------

def test_clean_and_contended_split(capsys, tmp_path):
    base = _group(_report(capsys))["pass_rate"]
    assert _counts(base["clean"]) == (0, 1)
    assert _counts(base["contended"]) == (0, 0)
    root = _copy(tmp_path)
    _append(root, SWITCH_ROW, design="switch-design")
    rates = _group(_report(capsys, root))["pass_rate"]
    assert _counts(rates["contended"]) == (1, 1)
    assert _counts(rates["clean"]) == (0, 1)
    assert _counts(rates["overall"]) == (3, 5)


# --- pre-#198 reset FAILs and runaway causes ------------------------------------------------

def test_pre_198_reset_fail_is_excluded_only_from_the_adjusted_rate(capsys):
    group = _group(_report(capsys))
    assert _counts(group["pass_rate"]["overall"]) == (2, 4)
    assert _counts(group["pass_rate"]["adjusted"]) == (2, 3)
    assert group["pass_rate"]["adjusted"]["rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert group["runaways"] == {"reset": 1, "generation": 0, "wall-clock": 0, "runaway-other": 0}


def test_a_reset_fail_after_198_stays_in_the_adjusted_rate(capsys, tmp_path):
    root = _copy(tmp_path)
    for old in (ROW7_START, ROW7_END):
        _edit(root, "dispatch-telemetry.ndjson", old, old.replace("2026-10-01", "2026-10-02"))
    group = _group(_report(capsys, root))
    assert group["runaways"]["reset"] == 1
    assert _counts(group["pass_rate"]["adjusted"]) == _counts(group["pass_rate"]["overall"]) == (2, 4)


@pytest.mark.parametrize("cause_text, cause", [
    ("runaway: wall-clock 1800s elapsed", "wall-clock"),
    ("runaway: generation stop_reason=max_tokens", "generation"),
    ("runaway: tool-call loop", "runaway-other"),
])
def test_genuine_runaways_stay_in_the_rate_and_count_by_cause(capsys, tmp_path, cause_text, cause):
    root = _copy(tmp_path)
    _edit(root, "decisions.md", RESET, cause_text)
    group = _group(_report(capsys, root))
    assert group["runaways"] == {c: int(c == cause) for c in RUNAWAY_CAUSES}
    assert _counts(group["pass_rate"]["adjusted"]) == _counts(group["pass_rate"]["overall"]) == (2, 4)


# --- attempts to pass -----------------------------------------------------------------------

def test_attempts_to_pass_per_task_keyed_by_start_rung(capsys):
    attempts = _report(capsys)["attempts_to_pass"]
    # local-medium starts tasks 1.2 (1 attempt), 8.1 (1) and 2.1 (FAIL, FAIL, then sonnet-xhigh PASS: 3);
    # task 1.4's local-medium rows never spawned, so its first spawned attempt is sonnet-medium.
    assert set(attempts) == {"local-medium", "sonnet-medium"}
    medium = attempts["local-medium"]
    assert (medium["tasks"], medium["passed"], medium["unpassed"]) == (3, 3, 0)
    assert medium["mean"] == pytest.approx(5 / 3, abs=1e-3)
    assert (medium["median"], medium["max"]) == (1, 3)
    sonnet = attempts["sonnet-medium"]
    assert (sonnet["tasks"], sonnet["passed"], sonnet["mean"], sonnet["max"]) == (1, 1, 1, 1)


def test_a_task_with_no_pass_is_unpassed_not_averaged(capsys, tmp_path):
    root = _copy(tmp_path)
    _edit(root, "dispatch-telemetry.ndjson", '"outcome": "PASS", "phase": "2"', '"outcome": "FAIL", "phase": "2"')
    medium = _report(capsys, root)["attempts_to_pass"]["local-medium"]
    assert (medium["tasks"], medium["passed"], medium["unpassed"]) == (3, 2, 1)
    assert (medium["mean"], medium["max"]) == (1, 1)


def test_attempts_are_counted_per_design(capsys, tmp_path):
    root = _copy(tmp_path)
    _append(root, SWITCH_ROW, design="switch-design")
    medium = _report(capsys, root)["attempts_to_pass"]["local-medium"]
    assert (medium["tasks"], medium["passed"]) == (4, 4)


# --- wall time and tokens -------------------------------------------------------------------

def test_wall_s_median_and_p90_over_spawned_rows(capsys):
    report = _report(capsys)
    wall = _group(report)["wall_s"]
    assert wall["median"] == pytest.approx(149.5)  # (55.5 + 243.5) / 2; the unavailable 11.0 and 18.0 are out
    assert wall["p90"] == pytest.approx(295.7)  # nearest rank: the 4th of 4
    for group in report["groups"]:
        if group["wall_s"]["median"] is not None:
            assert group["wall_s"]["median"] <= group["wall_s"]["p90"]


def test_tokens_and_router_output_tokens(capsys):
    group = _group(_report(capsys))
    assert group["tokens"]["sum"] == 215519 + 4166 + 68041 + 51889
    # a277fee1's six LOCAL-STATS in fixture row 7's window (router 12:32:20-12:33:19).
    assert group["router_output_tokens"] == 355 + 348 + 333 + 162 + 405 + 223
