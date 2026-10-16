"""Tests for posthoc_report: the report CLI's groups, reach, measured-run block, footer, archive.

design: cheap-tier-local-routing 8.1 (detailed-design-posthoc.md, posthoc_report; plan Task 8.1).
Runs `report --root <fixture>/repo --router-log <fixture>/router.log --utc-offset -06:00
--no-archive --json` in-process over the committed fixture excerpt (fixtures/posthoc/), with
XDG_STATE_HOME = the fixture dir (its one expired measurement window) and worktree discovery
confined to the given root, so no test reads the operator's state, router log, archive or
worktrees. Extra rows go into a tmp copy of the fixture repo. Pass rates, runaway causes,
attempts to pass and wall time: test_posthoc_report_rates.py.
"""
from __future__ import annotations

import datetime
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
import router_archive  # noqa: E402
import router_history  # noqa: E402

DESIGN = "fixture-design"
UTC = datetime.timezone.utc
# The fixture's one expired window (README §measure-windows.ndjson), router 11:55-12:35.
WINDOW = (datetime.datetime(2026, 10, 1, 17, 55, tzinfo=UTC), datetime.datetime(2026, 10, 1, 18, 35, tzinfo=UTC))
# router.log is one file, so coverage is one span: its first stamp to its last, at UTC-06:00.
COVERAGE = [["2026-09-30T17:49:15Z", "2026-10-01T18:33:30Z"]]
# Fixture row 5 (FTP-style): a local-medium PASS the router served upstream, its window lines 1-25.
FTP_ROW = {"agent": "tp-task-worker-local-medium", "attempt_key": "f7f7f7f7f7f7f7f7", "effort": "medium",
           "ended_at": "2026-09-30T17:50:12.819000Z", "model": "haiku", "outcome": "PASS", "phase": "8",
           "reason": "task_start", "role": "task", "route": "routed/ok", "rung": "local-medium",
           "served": {"local_requests": 0, "turns": 11}, "served_by": "fallback",
           "started_at": "2026-09-30T17:49:19.457000Z", "task_id": "8.2", "tokens": 4166, "wall_s": 53.4}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(FIX))
    monkeypatch.delenv("TP_LOCAL_LOG", raising=False)
    monkeypatch.setattr(cheap_ab_state, "worktree_roots", lambda root: [Path(root).resolve()])


def _report(capsys, root=REPO, log=LOG, *extra):
    argv = ["report", "--root", str(root), "--router-log", str(log), "--utc-offset", "-06:00",
            "--no-archive", "--json", *extra]
    code = posthoc_report.main(argv)
    out = capsys.readouterr().out
    assert code == 0
    return json.loads(out)


def _group(report, role, rung) -> dict:
    found = [g for g in report["groups"] if (g["role"], g["rung"]) == (role, rung)]
    assert len(found) == 1, report["groups"]
    return found[0]


def _copy(tmp_path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(REPO, dest)
    return dest


def _append(root, row, design=DESIGN) -> None:
    path = Path(root) / "three-pillars-docs" / "tp-designs" / design / "dispatch-telemetry.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _when(text) -> datetime.datetime:
    return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))


# --- groups and served-rung counts ---------------------------------------------------------

def test_groups_by_role_and_requested_rung(capsys):
    report = _report(capsys)
    keys = {(g["role"], g["rung"]) for g in report["groups"]}
    assert keys == {("task", "local-medium"), ("task", "sonnet-medium"), ("task", "local-xhigh"),
                    ("task", "sonnet-xhigh"), ("generator", None), ("reader", None)}
    assert sum(g["n"] for g in report["groups"]) == 11
    assert _group(report, "task", "local-medium")["n"] == 6


def test_served_rung_counts_and_fallback_reasons(capsys):
    report = _report(capsys)
    medium = _group(report, "task", "local-medium")
    assert medium["served"] == {"local": 2, "sonnet-mirror": 2, "never-spawned": 2}
    assert medium["fallbacks"] == {"local-busy": 2, "orphan-holds-gpu": 1, "refuse": 1}
    assert _group(report, "task", "local-xhigh")["served"] == {"never-spawned": 1}
    assert _group(report, "task", "sonnet-medium")["served"] == {"sonnet": 1}


def test_router_fallback_pass_row_counts_as_mirror_never_local(capsys, tmp_path):
    root = _copy(tmp_path)
    _append(root, FTP_ROW)
    medium = _group(_report(capsys, root), "task", "local-medium")
    assert medium["served"]["local"] == 2
    assert medium["served"]["sonnet-mirror"] == 3


# --- GPU reach ------------------------------------------------------------------------------

def test_gpu_reach_split_by_measure(capsys):
    reach = _report(capsys)["gpu_reach"]
    assert (reach["all"]["local"], reach["all"]["rows"]) == (2, 7)
    assert (reach["owner"]["local"], reach["owner"]["rows"]) == (1, 2)
    assert (reach["off"]["local"], reach["off"]["rows"]) == (1, 5)
    assert (reach["other"]["local"], reach["other"]["rows"]) == (0, 0)
    assert reach["owner"]["reach"] == pytest.approx(0.5)
    assert reach["other"]["reach"] is None


def test_local_busy_measure_row_is_out_of_organic_reach(capsys, tmp_path):
    root = _copy(tmp_path)
    _append(root, {"role": "task", "rung": "local-medium", "outcome": "unavailable", "served_by": None,
                   "fallback": "local-busy-measure", "measure": "off", "task_id": "9.9", "phase": "9",
                   "started_at": "2026-09-30T05:00:00Z", "ended_at": "2026-09-30T05:00:05Z"})
    off = _report(capsys, root)["gpu_reach"]["off"]
    assert (off["local"], off["rows"]) == (1, 5)
    assert off["local_busy_measure"] == 1


# --- the measured-run block ----------------------------------------------------------------

def test_expired_window_yields_a_measured_run_block(capsys):
    runs = _report(capsys)["measured_runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run["design"] == DESIGN
    assert (_when(run["start"]), _when(run["end"])) == WINDOW
    assert run["rows"] == {"local-busy": 1, "clean": 1}
    # sess 880ace71 (FTP's) routes 21 `-> local` POSTs in the window and owns no row in the run.
    assert run["other_session_local_requests"] == 21
    assert run["foreign_local_requests"] == 21


def test_foreign_is_the_subset_from_sessions_outside_the_run(capsys, tmp_path):
    root = _copy(tmp_path)
    _append(root, {"role": "task", "rung": "local-medium", "outcome": "PASS", "served_by": "local",
                   "agent8": "a8a5f599", "task_id": "3.1", "phase": "3", "wall_s": 260.0,
                   "started_at": "2026-10-01T18:00:40Z", "ended_at": "2026-10-01T18:05:00Z"},
            design="ftp-design")
    run = _report(capsys, root)["measured_runs"][0]
    assert run["rows"] == {"local-busy": 1, "clean": 1}
    assert run["other_session_local_requests"] == 21
    assert run["foreign_local_requests"] == 0


def test_window_outside_the_range_prints_no_block(capsys):
    report = _report(capsys, REPO, LOG, "--until", "2026-10-01T12:00:00Z")
    assert report["measured_runs"] == []


# --- footer ---------------------------------------------------------------------------------

def test_footer_holds_coverage_uncovered_join_and_malformed(capsys):
    footer = _report(capsys)["footer"]
    assert footer["coverage"] == COVERAGE
    assert footer["uncovered"] == 1
    assert footer["join"] == {"window-exact": 3}
    assert footer["malformed"] == 0
    assert footer["archive"] is None


def test_footer_counts_a_malformed_router_line(capsys, tmp_path):
    log = tmp_path / "router.log"
    lines = LOG.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join([*lines[:30], "[2026-10-01 12:00:30] NOT-A-ROUTER-KIND x=1", *lines[30:]]) + "\n",
                   encoding="utf-8")
    footer = _report(capsys, REPO, log)["footer"]
    assert footer["malformed"] == 1
    assert footer["coverage"] == COVERAGE


# --- the table ------------------------------------------------------------------------------

def test_table_renders_every_group_and_window(capsys):
    report = _report(capsys)
    code = posthoc_report.main(["report", "--root", str(REPO), "--router-log", str(LOG),
                                "--utc-offset", "-06:00", "--no-archive"])
    text = capsys.readouterr().out
    assert code == 0
    for group in report["groups"]:
        assert group["role"] in text
        assert group["rung"] is None or group["rung"] in text
    assert DESIGN in text


# --- the archiver ---------------------------------------------------------------------------

@pytest.fixture
def live_log(tmp_path, monkeypatch):
    log = tmp_path / "router.log"
    shutil.copyfile(LOG, log)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("TP_LOCAL_LOG", str(log))
    return log


def test_archive_runs_first_and_feeds_the_history(capsys, live_log, monkeypatch):
    calls = []
    real_archive, real_load = router_archive.archive, router_history.load
    monkeypatch.setattr(router_archive, "archive", lambda *a, **k: calls.append("archive") or real_archive(*a, **k))
    monkeypatch.setattr(router_history, "load", lambda *a, **k: calls.append("history") or real_load(*a, **k))
    code = posthoc_report.main(["report", "--root", str(REPO), "--utc-offset", "-06:00", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls[:2] == ["archive", "history"]
    assert sorted((live_log.parent / "router-archive").glob("router-*.log"))
    assert report["footer"]["archive"]["archived"] > 0
    assert report["footer"]["coverage"] == COVERAGE


def test_archive_failure_does_not_fail_the_report(capsys, live_log, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("archive dir unwritable")

    monkeypatch.setattr(router_archive, "archive", boom)
    code = posthoc_report.main(["report", "--root", str(REPO), "--router-log", str(LOG),
                                "--utc-offset", "-06:00", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "archive dir unwritable" in json.dumps(report["footer"]["archive"])
    assert _group(report, "task", "local-medium")["n"] == 6


# --- exit codes -----------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [["--bogus"], ["--utc-offset", "6h"], ["--since", "not-a-date"],
                                   ["--until", "2026-13-45"]])
def test_bad_flag_exits_2(capsys, extra):
    code = posthoc_report.main(["report", "--root", str(REPO), "--router-log", str(LOG), "--no-archive", *extra])
    assert code == 2
    assert capsys.readouterr().out == ""


def test_missing_subcommand_exits_2(capsys):
    assert posthoc_report.main([]) == 2
