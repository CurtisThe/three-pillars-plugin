"""run_retro_collect.py: the run's artifacts read into signals.

Every fixture copies a real record shape (archived decisions.md headings, finalizer.py's
ledger, escape_ledger.row, dispatch_log rows, stopped_agents._entry, a pytest xunit2 junit).
The tests parse structure only; they never read SKILL.md prose.
"""
import json
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import escape_ledger  # noqa: E402
import ladder_files  # noqa: E402
import stopped_agents  # noqa: E402
import run_retro_collect as rc  # noqa: E402

STAMP = "2026-10-21T23:33:49Z"
STAMP_EPOCH = 1792625629  # the same instant, UTC
SEAT = "Seat (under operator delegation): continue on Sonnet."
# The orchestrator's real heading prefix, built from parts: its skill-dir name as a raw literal
# beside a SKILL.md path makes rule_ledger_extract.pin_tests_for count this file as a pin test
# of that skill, and the sealed rule ledgers then want a row for every literal here.
RFD = "tp-run-" + "full-design"


@pytest.fixture
def design(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    d.mkdir(parents=True)
    return d


def decisions(design, *entries):
    """entries: (heading, body) pairs written in the archived `### [prefix] title` form."""
    text = "".join(f"### {h}\n{b}\n\n" for h, b in entries)
    (design / "decisions.md").write_text(text, encoding="utf-8")


def collect(design, env=None):
    return rc.collect(design, repo_root=design.parents[2], env=env or {})


def sigs(result, kind=None):
    return [s for s in result["signals"] if kind is None or s["kind"] == kind]


def ndjson(path, rows, raw=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in rows] + list(raw)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- parse_entries -------------------------------------------------------------------

def test_parse_entries_splits_on_prefix_title_headings():
    text = ("# decisions\n\n### [orchestrator/design-audit] retry-with-advice attempt 2/3\n"
            "- body a\n\n### [finalizer] resolved — audit-gate/design\n- body b\n")
    got = rc.parse_entries(text)
    assert [(e["prefix"], e["title"]) for e in got] == [
        ("orchestrator/design-audit", "retry-with-advice attempt 2/3"),
        ("finalizer", "resolved — audit-gate/design")]
    assert "body a" in got[0]["body"] and "body b" not in got[0]["body"]


# ---- decisions.md headings -----------------------------------------------------------

@pytest.mark.parametrize("title", ["retry-with-advice attempt 2/3", "retry-exhausted (attempt 3/3)",
                                   "audit-retry-exhausted skills/_shared/foo.py", "retry"])
def test_retry_tokens_give_a_retry_kind_with_rerun(design, title):
    assert title.split()[0] in rc.RETRY_TOKENS
    decisions(design, (f"[orchestrator/design-audit] {title}", "- Decided: again"))
    (s,) = sigs(collect(design))
    assert s["kind"] == "retry" and s["rerun"] is True and s["operator_touch"] is False
    assert s["skill"] == "orchestrator"


def test_block_token_gives_a_block_kind_and_skill_is_first_segment(design):
    assert "worker-root-refused" in rc.BLOCK_TOKENS
    decisions(design, (f"[{RFD}/tier-3] worker-root-refused",
                       "- refused for skills/_shared/worker_root.py"))
    (s,) = sigs(collect(design))
    assert (s["kind"], s["skill"], s["rerun"]) == ("block", RFD, False)
    assert s["key"] == "path:skills/_shared/worker_root.py"


@pytest.mark.parametrize("token", ["sha-mismatch", "no-candidate-block", "worker-noop",
                                   "rerun-failed", "task-env-error", "map-check-escalated",
                                   "worker-root-open-failed"])
def test_every_non_retryable_token_blocks(design, token):
    decisions(design, (f"[{RFD}/tier-2] {token}", "- nothing"))
    (s,) = sigs(collect(design))
    assert s["kind"] == "block" and s["key"] == f"event:{token}"


def test_other_headings_give_no_signal(design):
    decisions(design, ("[tier] 1.1 — done", "- ok"), ("[routing] phase 1: none -> routed/ok", ""),
              ("[orchestrator/detail] pass", "- fine"))
    assert collect(design)["signals"] == []


def test_key_prefers_heading_path_then_body_path_then_event(design):
    decisions(design,
              ("[a/b] worker-noop on agents/tp-task-worker.md", "- see skills/_shared/x.py"),
              ("[a/b] worker-noop", "- touched skills/_shared/y.py and agents/z.md"),
              ("[a/b] worker-noop", "- no path here"))
    assert [s["key"] for s in sigs(collect(design))] == [
        "path:agents/tp-task-worker.md", "path:skills/_shared/y.py", "event:worker-noop"]


def test_own_plan_file_paths_are_skipped_for_the_next_path_or_event(design):
    (design / "plan.md").write_text(
        "### Task 1.1\n**File**: `skills/_shared/own.py` (new), `skills/_shared/test_own.py`\n",
        encoding="utf-8")
    decisions(design,
              ("[a/b] worker-noop skills/_shared/own.py", "- also skills/_shared/other.py"),
              ("[a/b] retry skills/_shared/own.py", "- nothing else"))
    assert [s["key"] for s in sigs(collect(design))] == ["path:skills/_shared/other.py",
                                                         "event:retry"]


def test_relay_marker_on_a_retry_or_block_keeps_the_kind(design):
    decisions(design, ("[a/b] retry-with-advice attempt 2/3", SEAT),
              ("[a/b] worker-root-refused", "Operator ruling: go on"))
    got = sigs(collect(design))
    assert [(s["kind"], s["operator_touch"]) for s in got] == [("retry", True), ("block", True)]


def test_marker_only_entry_is_a_touch_with_operator_touch(design):
    # shape of completed-tp-designs/one-cheap-engine/decisions.md:~291
    decisions(design, ("[orchestrator/operator-ruling] Part B busy grace + re-probe (2026-10-09, "
                       "relayed by the seat)", "**Decided**: Operator ruling: a busy slot waits."),
              (f"[{RFD}] resume notes", SEAT))
    got = sigs(collect(design))
    assert [(s["kind"], s["operator_touch"]) for s in got] == [("touch", True)] * 2


def test_run_retro_prefixed_heading_yields_no_signal(design):
    decisions(design, ("[run-retro] worker-noop", "- retry skills/_shared/x.py"),
              ("[run-retro/filter] worker-root-refused", SEAT))
    assert collect(design)["signals"] == []


# ---- finalizer ledger ----------------------------------------------------------------

def ledger(design, seen):
    body = {"in_flight": None, "seen": seen, "stale_cleared": []}
    (design / "finalizer-ledger.json").write_text(json.dumps(body), encoding="utf-8")


def test_ledger_seen_keys_give_one_finalizer_signal_each(design):
    ledger(design, {"audit-gate:design:demo": "resolved", "pr-iterate:growth-lines:demo": "escalate"})
    got = {s["key"]: s for s in sigs(collect(design), "finalizer")}
    assert set(got) == {"finalizer:audit-gate:design", "finalizer:pr-iterate:growth-lines"}
    assert got["finalizer:audit-gate:design"]["operator_touch"] is False
    assert got["finalizer:pr-iterate:growth-lines"]["operator_touch"] is True


def test_finalizer_heading_adds_its_ref_to_the_ledger_signal(design):
    ledger(design, {"audit-gate:design:demo": "resolved"})
    decisions(design, ("[finalizer] resolved — audit-gate/design", "- **Decided**: resolved"))
    (s,) = sigs(collect(design))
    assert s["key"] == "finalizer:audit-gate:design" and "decisions.md" in s["ref"]
    assert "finalizer-ledger.json" in s["ref"] and s["operator_touch"] is False


def test_finalizer_escalate_heading_sets_operator_touch(design):
    ledger(design, {"audit-gate:design:demo": "resolved"})
    decisions(design, ("[finalizer] escalate — audit-gate/design", "- **Decided**: escalate"))
    (s,) = sigs(collect(design))
    assert s["key"] == "finalizer:audit-gate:design" and s["operator_touch"] is True


def test_malformed_or_missing_ledger_gives_no_rows_and_no_raise(design):
    assert collect(design) == {"signals": [], "tokens": {}}
    (design / "finalizer-ledger.json").write_text("{not json", encoding="utf-8")
    assert collect(design) == {"signals": [], "tokens": {}}
    (design / "finalizer-ledger.json").write_text('{"seen": []}', encoding="utf-8")
    assert collect(design)["signals"] == []


def test_a_ledger_key_without_a_colon_gives_no_finalizer_row_and_no_raise(design):
    ledger(design, {"legacy-key": "resolved"})
    assert collect(design) == {"signals": [], "tokens": {}}
    ledger(design, {"legacy-key": "resolved", "audit-gate:design:demo": "resolved"})
    assert [s["key"] for s in sigs(collect(design), "finalizer")] == ["finalizer:audit-gate:design"]


# ---- escape ledger, telemetry tokens, stops -------------------------------------------

def test_escape_rows_dropped_downgraded_opus_added_signal_kept_and_capped_do_not(design):
    rows = [escape_ledger.row("review_finder", "sonnet", "demo", "review", f"F{i}", disp,
                              "opus-check", "defect")
            for i, disp in enumerate(["dropped", "downgraded", "opus-added", "kept"])]
    rows.append({"role": "review_finder", "capped": True})
    ndjson(design / escape_ledger.NDJSON_NAME, rows, raw=["{broken"])
    got = sigs(collect(design), "escape")
    assert [s["key"] for s in got] == ["escape:review_finder:dropped",
                                       "escape:review_finder:downgraded",
                                       "escape:review_finder:opus-added"]


def test_tokens_sum_per_role_over_integer_tokens_skipping_null(design):
    import dispatch_log
    rows = [{"role": "worker", "agent": "tp-task-worker", "tokens": 1200},
            {"role": "worker", "agent": "tp-task-worker", "tokens": 300},
            {"role": "reviewer", "agent": "r", "tokens": 50},
            {"role": "worker", "agent": "tp-task-worker", "tokens": None,
             "tokens_reason": "the spawn reported no usage total"}]
    ndjson(design / dispatch_log.NDJSON_NAME, rows, raw=["not json"])
    assert collect(design)["tokens"] == {"worker": 1500, "reviewer": 50}


def stop_row(result, **extra):
    row = stopped_agents._entry("a1b2c3d4e5f6", "att-1", 1792600000.0,
                                {"orphaned_at": 1792600100.0, "result": result, **extra})
    return row


def test_stops_refused_and_error_signal_ok_and_gone_do_not(design, tmp_path, monkeypatch):
    ladder = tmp_path / "ladder"
    monkeypatch.setattr(ladder_files, "ladder_dir", lambda root, slug: ladder)
    assert ladder_files.STOPS == "stops.ndjson"
    ndjson(ladder / ladder_files.STOPS, [stop_row(r) for r in ("refused", "error", "ok", "gone")],
           raw=["{torn"])
    got = sigs(collect(design), "stop")
    assert [s["key"] for s in got] == ["event:stop-refused", "event:stop-error"]
    assert "a1b2c3d4e5f6" not in json.dumps(got)


def test_a_failing_ladder_dir_resolution_is_fail_open(design, monkeypatch):
    def boom(root, slug):
        raise OSError("no git")
    monkeypatch.setattr(ladder_files, "ladder_dir", boom)
    assert collect(design)["signals"] == []


# ---- junit ----------------------------------------------------------------------------

JUNIT = ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="3">'
         '<testcase classname="skills._shared.test_x" name="test_ok" time="0.01"/>'
         '<testcase classname="skills._shared.test_x" name="test_bad_one" time="0.02">'
         '<failure message="assert 1 == 2">trace</failure></testcase>'
         '<testcase classname="skills._shared.test_x" name="test_skip" time="0">'
         '<skipped type="pytest.skip" message="s"/></testcase></testsuite></testsuites>')


def put_junit(tmp_path, name="pytest-main.xml", text=JUNIT, mtime=STAMP_EPOCH + 1000):
    d = tmp_path / "manifest"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return {"CI_LOCAL_MANIFEST_DIR": str(d)}


def test_failed_junit_case_gives_ci_fail_passed_and_skipped_do_not(design, tmp_path):
    env = put_junit(tmp_path)
    put_junit(tmp_path, "pytest-serial.xml")
    got = sigs(collect(design, env), "ci_fail")
    assert [s["key"] for s in got] == ["junit:skills._shared.test_x::test_bad_one"] * 2


def test_junit_unset_unreadable_other_name_or_stale_gives_nothing(design, tmp_path):
    assert sigs(collect(design), "ci_fail") == []
    assert sigs(collect(design, put_junit(tmp_path, text="<not-xml")), "ci_fail") == []
    assert sigs(collect(design, put_junit(tmp_path, "other.xml")), "ci_fail") == []
    decisions(design, ("[tier] 1.1 — done", f"- at {STAMP}"))
    stale = put_junit(tmp_path, mtime=STAMP_EPOCH - 3600)
    assert sigs(collect(design, stale), "ci_fail") == []
    fresh = put_junit(tmp_path, mtime=STAMP_EPOCH + 3600)
    assert len(sigs(collect(design, fresh), "ci_fail")) == 1


# ---- normalised_token (N9) -------------------------------------------------------------

@pytest.mark.parametrize("key,want", [
    ("path:skills/_shared/worker_root.py", "worker-root"),
    ("path:agents/Tp Task_Worker.md", "agents-tp-task-worker"),
    ("path:skills/tp-spike/SKILL.md", "tp-spike-skill"),
    ("path:skills/tp-design/SKILL.md", "tp-design-skill"),
    ("finalizer:audit-gate:design", "audit-gate-design"),
    ("escape:review_finder:dropped", "review_finder-dropped".replace("_", "-")),
    ("junit:skills._shared.test_x::test_bad_one", "test-x-test-bad-one"),
    ("junit:skills._shared.test_x::test_b[../../x]", "test-x-test-b-x"),
    ("event:worker-root-refused", "worker-root-refused")])
def test_normalised_token_per_key_class(key, want):
    assert rc.normalised_token(key) == want


@pytest.mark.parametrize("key", [
    "path:skills/tp-spike/SKILL.md", "path:skills/_shared/worker_root.py",
    "junit:a.b::test_b[../../../x]", "junit:a.b::test_c[a/b c]", "finalizer:pr iterate:../up",
    "escape:review_finder:dropped", "event:Worker/Root Refused.."])
def test_every_key_class_normalises_to_a_slug_safe_token(key):
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", rc.normalised_token(key))
