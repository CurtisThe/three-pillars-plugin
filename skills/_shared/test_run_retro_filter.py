"""run_retro_filter.py: the RRSI bar over grouped signals.

Groups come from run_retro_collect.collect (run over a tmp design dir with decisions.md in the
archived `### [prefix] title` form) through run_retro_group.group_signals. known_items are the
`{id, kind, retro_key, text}` dicts the CLI builds from open seeds. Assertions read structured
fields only; none reads prose.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import escape_ledger  # noqa: E402
import run_retro_collect as rc  # noqa: E402
import run_retro_filter as rf  # noqa: E402
import run_retro_group as rg  # noqa: E402

SEAT = "Seat (under operator delegation): continue on Sonnet."
# The orchestrator's real heading prefix, built from parts: its skill-dir name as a raw literal
# beside a SKILL.md path makes rule_ledger_extract.pin_tests_for count this file as a pin test
# of that skill, and the sealed rule ledgers then want a row for every literal here.
RFD = "tp-run-" + "full-design"
WORKER_ROOT = "skills/_shared/worker_root.py"
WORKER_ROOT_KEY = f"path:{WORKER_ROOT}"
DRAFT_SCHEMA = {"retro_key", "proposed_slug", "skill", "type", "shapes", "evidence", "count",
                "operator_touch", "rerun", "candidates"}
RESULT_SCHEMA = {"drafts", "observations", "evidence_adds"}
JUNIT = ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="1">'
         '<testcase classname="skills._shared.test_x" name="test_bad_one" time="0.02">'
         '<failure message="assert 1 == 2">trace</failure></testcase></testsuite></testsuites>')


@pytest.fixture
def design(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    d.mkdir(parents=True)
    return d


def collected(design, *entries, env=None):
    if entries:
        text = "".join(f"### {h}\n{b}\n\n" for h, b in entries)
        (design / "decisions.md").write_text(text, encoding="utf-8")
    return rc.collect(design, repo_root=design.parents[2], env=env or {})["signals"]


def grouped(design, *entries, env=None):
    return rg.group_signals(collected(design, *entries, env=env))


def two_retries(design, path=WORKER_ROOT):
    return grouped(design,
                   ("[orchestrator/design-audit] retry-with-advice attempt 1/3", f"- {path}"),
                   ("[orchestrator/design-audit] retry-with-advice attempt 2/3", f"- {path}"))


def item(id_, text="", retro_key=None, kind="seed"):
    return {"id": id_, "kind": kind, "retro_key": retro_key, "text": text}


# ---- the bar --------------------------------------------------------------------------

def test_result_has_exactly_the_three_buckets(design):
    assert set(rf.apply_rrsi([], [])) == RESULT_SCHEMA
    assert rf.apply_rrsi([], []) == {"drafts": [], "observations": [], "evidence_adds": []}


def test_a_recurred_path_group_with_no_known_match_becomes_a_draft(design):
    result = rf.apply_rrsi(two_retries(design), [])
    (d,) = result["drafts"]
    assert d["retro_key"] == WORKER_ROOT_KEY and d["count"] == 2
    assert result["observations"] == [] and result["evidence_adds"] == []


def test_a_one_occurrence_group_with_an_operator_touch_becomes_a_draft(design):
    groups = grouped(design, ("[a/b] worker-noop", f"- {WORKER_ROOT}\n{SEAT}"))
    (d,) = rf.apply_rrsi(groups, [])["drafts"]
    assert d["count"] == 1 and d["operator_touch"] is True


def test_a_one_occurrence_group_with_no_touch_and_no_rerun_is_an_observation(design):
    groups = grouped(design, ("[a/b] worker-noop", f"- {WORKER_ROOT}"))
    result = rf.apply_rrsi(groups, [])
    assert result["drafts"] == []
    assert [o["retro_key"] for o in result["observations"]] == [WORKER_ROOT_KEY]


def test_a_single_retry_naming_a_path_is_an_observation_not_a_draft(design):
    groups = grouped(design, ("[orchestrator/tier-3] retry-with-advice attempt 1/3",
                              f"- {WORKER_ROOT}"))
    (g,) = groups
    assert (g["count"], g["rerun_count"], g["operator_touch"]) == (1, 1, False)
    result = rf.apply_rrsi(groups, [])
    assert result["drafts"] == []
    assert [o["retro_key"] for o in result["observations"]] == [WORKER_ROOT_KEY]


def test_an_event_keyed_group_is_an_observation_whatever_its_count(design):
    groups = grouped(design, *[("[a/b] worker-noop", f"- try {n}\n{SEAT}") for n in range(3)])
    (g,) = groups
    assert g["key"] == "event:worker-noop" and g["count"] == 3 and g["operator_touch"]
    result = rf.apply_rrsi(groups, [])
    assert result["drafts"] == []
    assert [o["retro_key"] for o in result["observations"]] == ["event:worker-noop"]


def test_two_retry_exhausted_paths_give_two_one_occurrence_observations(design):
    groups = grouped(design,
                     ("[a/b] retry-exhausted (attempt 3/3)", "- skills/_shared/a.py"),
                     ("[a/b] retry-exhausted (attempt 3/3)", "- skills/_shared/b.py"))
    result = rf.apply_rrsi(groups, [])
    assert [o["retro_key"] for o in result["observations"]] == [
        "path:skills/_shared/a.py", "path:skills/_shared/b.py"]


def test_the_recurrence_threshold_is_a_module_level_constant_read_per_call(design, monkeypatch):
    assert rf.MIN_RECURRENCE == 2
    groups = grouped(design, ("[a/b] worker-noop", f"- {WORKER_ROOT}"),
                     ("[a/b] worker-noop", f"- {WORKER_ROOT}"))
    assert len(rf.apply_rrsi(groups, [])["drafts"]) == 1
    monkeypatch.setattr(rf, "MIN_RECURRENCE", 3)
    assert rf.apply_rrsi(groups, [])["drafts"] == []


# ---- the draft ------------------------------------------------------------------------

def test_a_draft_carries_exactly_the_schema_fields(design):
    (d,) = rf.apply_rrsi(two_retries(design), [])["drafts"]
    assert set(d) == DRAFT_SCHEMA


def test_a_draft_is_built_from_the_groups_structured_fields(design):
    groups = two_retries(design)
    (g,) = groups
    (d,) = rf.apply_rrsi(groups, [])["drafts"]
    assert d["proposed_slug"] == "retro-worker-root"
    assert d["skill"] == "orchestrator" and d["type"] == "Bug"
    assert d["evidence"] == g["refs"] and d["rerun"] is True and d["candidates"] == []
    assert WORKER_ROOT_KEY in d["shapes"] and "worker-root" in d["shapes"]
    assert "decisions.md" in d["shapes"]


def test_no_entry_body_text_is_copied_into_a_draft(design):
    marker = "SECRETVALUE0123"
    groups = grouped(design,
                     ("[a/b] retry-with-advice attempt 1/3", f"- {WORKER_ROOT} API_KEY={marker}"),
                     ("[a/b] retry-with-advice attempt 2/3", f"- {WORKER_ROOT} API_KEY={marker}"))
    (d,) = rf.apply_rrsi(groups, [])["drafts"]
    assert marker not in json.dumps(d)


def test_the_standalone_relay_entry_draft_is_an_idea(design):
    groups = grouped(design, (f"[orchestrator/operator-ruling] busy grace for {WORKER_ROOT} "
                              "(relayed by the seat)", "**Decided**: Operator ruling: wait."))
    (g,) = groups
    assert g["kinds"] == ["touch"]
    (d,) = rf.apply_rrsi(groups, [])["drafts"]
    assert d["type"] == "Idea" and d["operator_touch"] is True


def test_an_escalated_finalizer_group_drafts_an_idea_with_a_finalizer_slug(design):
    body = {"in_flight": None, "seen": {"pr-iterate:growth-lines:demo": "escalate"},
            "stale_cleared": []}
    (design / rc.LEDGER_NAME).write_text(json.dumps(body), encoding="utf-8")
    (d,) = rf.apply_rrsi(grouped(design), [])["drafts"]
    assert d["retro_key"] == "finalizer:pr-iterate:growth-lines"
    assert d["type"] == "Idea" and d["proposed_slug"] == "retro-pr-iterate-growth-lines"


def test_a_recurring_escape_group_drafts_a_bug(design):
    rows = [escape_ledger.row("review_finder", "sonnet", "demo", "review", f"F{i}", "dropped",
                              "opus-check", "defect") for i in range(2)]
    (design / escape_ledger.NDJSON_NAME).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (d,) = rf.apply_rrsi(grouped(design), [])["drafts"]
    assert d["retro_key"] == "escape:review_finder:dropped" and d["type"] == "Bug"


def test_a_failed_junit_case_in_both_reports_drafts_a_bug(design, tmp_path):
    manifest = tmp_path / "manifest"
    manifest.mkdir()
    for name in rc.JUNIT_FILES:
        (manifest / name).write_text(JUNIT, encoding="utf-8")
    (d,) = rf.apply_rrsi(grouped(design, env={"CI_LOCAL_MANIFEST_DIR": str(manifest)}), [])["drafts"]
    assert d["retro_key"] == "junit:skills._shared.test_x::test_bad_one"
    assert d["type"] == "Bug" and d["count"] == 2


# ---- covered by a known item ------------------------------------------------------------

def test_a_group_with_a_known_seeds_retro_key_adds_evidence_and_drafts_nothing(design):
    groups = two_retries(design)
    (g,) = groups
    known = [item("unrelated-seed", "docs cleanup"),
             item("worker-root-fix", "words", retro_key=WORKER_ROOT_KEY)]
    result = rf.apply_rrsi(groups, known)
    assert result["drafts"] == [] and result["observations"] == []
    (line,) = result["evidence_adds"]
    assert line["seed"] == "worker-root-fix" and line["retro_key"] == WORKER_ROOT_KEY
    assert line["evidence"] == g["refs"] and line["count"] == 2


def test_a_group_whose_mechanism_token_is_in_a_known_slug_matches_the_same_way(design):
    known = [item("retro-worker-root-fix", "retro-worker-root-fix")]
    result = rf.apply_rrsi(two_retries(design), known)
    assert result["drafts"] == []
    assert [e["seed"] for e in result["evidence_adds"]] == ["retro-worker-root-fix"]


def test_a_near_miss_stays_a_draft_with_the_near_miss_listed_as_a_candidate(design):
    known = [item("seed-pool", "worker-pool"), item("seed-net", "networker-root"),
             item("seed-docs", "docs-cleanup")]
    result = rf.apply_rrsi(two_retries(design), known)
    (d,) = result["drafts"]
    assert d["candidates"] == ["seed-pool", "seed-net"]
    assert result["evidence_adds"] == []


def test_an_exact_retro_key_match_wins_over_an_earlier_token_match(design):
    known = [item("by-token", "worker-root"), item("by-key", "x", retro_key=WORKER_ROOT_KEY)]
    (line,) = rf.apply_rrsi(two_retries(design), known)["evidence_adds"]
    assert line["seed"] == "by-key"


# ---- matches (N9) -------------------------------------------------------------------------

@pytest.fixture
def worker_root_group(design):
    (g,) = two_retries(design)
    return g


@pytest.mark.parametrize("text", ["retro-worker-root-fix", "Worker Root", "worker_root",
                                  "fix worker-root now", "worker-root", "x-worker-root"])
def test_a_text_holding_the_full_token_hyphen_bounded_matches(worker_root_group, text):
    assert rf.matches(worker_root_group, item("i", text)) is True


@pytest.mark.parametrize("text", ["worker-pool", "networker-root", "worker", "worker-roots",
                                  "root-worker", "", None])
def test_a_text_sharing_only_a_prefix_or_inside_a_longer_word_does_not_match(
        worker_root_group, text):
    assert rf.matches(worker_root_group, item("i", text)) is False


def test_matches_by_retro_key_equality_needs_no_text(worker_root_group):
    assert rf.matches(worker_root_group, item("i", "", retro_key=WORKER_ROOT_KEY)) is True
    assert rf.matches(worker_root_group, item("i", "", retro_key="path:skills/_shared/other.py")
                      ) is False


# ---- two paths that share a file name (phase-check C1/C3) ---------------------------------

def noop_groups(design):
    entries = [(f"[{RFD}/tier-3] worker-noop", f"- touched skills/{d}/SKILL.md")
               for d in ("tp-design", "tp-design", "tp-spike", "tp-spike")]
    return grouped(design, *entries)


def test_two_paths_sharing_a_file_name_give_two_drafts_with_distinct_slugs(design):
    drafts = rf.apply_rrsi(noop_groups(design), [])["drafts"]
    assert sorted(d["retro_key"] for d in drafts) == [
        "path:skills/tp-design/SKILL.md", "path:skills/tp-spike/SKILL.md"]
    assert sorted(d["proposed_slug"] for d in drafts) == ["retro-tp-design-skill",
                                                          "retro-tp-spike-skill"]


def test_a_seed_for_one_of_two_same_named_paths_covers_only_that_path(design):
    known = [item("retro-tp-design-skill", "retro-tp-design-skill")]
    result = rf.apply_rrsi(noop_groups(design), known)
    assert [d["retro_key"] for d in result["drafts"]] == ["path:skills/tp-spike/SKILL.md"]
    assert [e["retro_key"] for e in result["evidence_adds"]] == [
        "path:skills/tp-design/SKILL.md"]
