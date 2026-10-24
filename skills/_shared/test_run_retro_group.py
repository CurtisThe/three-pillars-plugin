"""run_retro_group.py: friction signals bucketed by their mechanism token.

Signals are built by running run_retro_collect.collect over a tmp design dir whose decisions.md
holds the archived `### [prefix] title` heading form, the way test_run_retro_collect.py builds
them. Every assertion reads the structured group dicts; none reads prose.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_retro_collect as rc  # noqa: E402
import run_retro_group as rg  # noqa: E402

SEAT = "Seat (under operator delegation): continue on Sonnet."
WORKER_ROOT = "skills/_shared/worker_root.py"


@pytest.fixture
def design(tmp_path):
    d = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    d.mkdir(parents=True)
    return d


def signals(design, *entries):
    """entries: (heading, body) pairs written in the archived `### [prefix] title` form."""
    text = "".join(f"### {h}\n{b}\n\n" for h, b in entries)
    (design / "decisions.md").write_text(text, encoding="utf-8")
    return rc.collect(design, repo_root=design.parents[2], env={})["signals"]


def test_two_retries_naming_one_path_give_one_group_with_both_refs(design):
    sigs = signals(design,
                   ("[orchestrator/design-audit] retry-with-advice attempt 1/3", f"- {WORKER_ROOT}"),
                   ("[orchestrator/design-audit] retry-with-advice attempt 2/3", f"- {WORKER_ROOT}"))
    (g,) = rg.group_signals(sigs)
    assert g["key"] == f"path:{WORKER_ROOT}"
    assert g["count"] == 2
    assert g["refs"] == [s["ref"] for s in sigs]
    assert g["kinds"] == ["retry"]


def test_retry_exhausted_naming_two_paths_give_two_groups(design):
    sigs = signals(design,
                   ("[orchestrator/tier-3] retry-exhausted (attempt 3/3)", "- skills/_shared/a.py"),
                   ("[orchestrator/tier-3] retry-exhausted (attempt 3/3)", "- skills/_shared/b.py"))
    groups = rg.group_signals(sigs)
    assert [g["key"] for g in groups] == ["path:skills/_shared/a.py", "path:skills/_shared/b.py"]
    assert [g["count"] for g in groups] == [1, 1]


def test_the_group_key_is_the_mechanism_never_the_kind(design):
    sigs = signals(design,
                   ("[a/b] retry-with-advice attempt 1/3", f"- {WORKER_ROOT}"),
                   ("[a/b] worker-root-refused", f"- {WORKER_ROOT}"))
    (g,) = rg.group_signals(sigs)
    assert g["count"] == 2
    assert len(g["kinds"]) == 2 and set(g["kinds"]) == {"block", "retry"}


def test_signals_sharing_one_event_key_group_together_by_that_key(design):
    sigs = signals(design, ("[a/b] worker-noop", "- no path"), ("[a/b] worker-noop", "- none"))
    (g,) = rg.group_signals(sigs)
    assert (g["key"], g["count"]) == ("event:worker-noop", 2)


def test_operator_touch_and_rerun_are_ored_and_rerun_count_counts_retry_signals(design):
    sigs = signals(design,
                   ("[a/b] worker-root-refused", f"- {WORKER_ROOT}\n{SEAT}"),
                   ("[a/b] retry-with-advice attempt 1/3", f"- {WORKER_ROOT}"),
                   ("[a/b] worker-noop", f"- {WORKER_ROOT}"))
    (g,) = rg.group_signals(sigs)
    assert (g["count"], g["operator_touch"], g["rerun"], g["rerun_count"]) == (3, True, True, 1)


def test_a_group_with_no_touch_and_no_retry_has_both_flags_false(design):
    (g,) = rg.group_signals(signals(design, ("[a/b] worker-noop", f"- {WORKER_ROOT}")))
    assert (g["operator_touch"], g["rerun"], g["rerun_count"]) == (False, False, 0)


def test_two_retries_have_rerun_count_two(design):
    sigs = signals(design, ("[a/b] retry", f"- {WORKER_ROOT}"), ("[a/b] retry", f"- {WORKER_ROOT}"))
    (g,) = rg.group_signals(sigs)
    assert g["rerun_count"] == 2 and g["rerun"] is True


def test_groups_come_out_in_first_seen_key_order(design):
    sigs = signals(design,
                   ("[a/b] worker-noop", "- skills/_shared/b.py"),
                   ("[a/b] worker-noop", "- skills/_shared/a.py"),
                   ("[a/b] worker-noop", "- skills/_shared/b.py"))
    groups = rg.group_signals(sigs)
    assert [(g["key"], g["count"]) for g in groups] == [("path:skills/_shared/b.py", 2),
                                                        ("path:skills/_shared/a.py", 1)]


def test_the_skill_is_the_signals_skill_segment(design):
    sigs = signals(design, ("[tp-run-full-design/tier-3] worker-root-refused", f"- {WORKER_ROOT}"))
    (g,) = rg.group_signals(sigs)
    assert g["skill"] == "tp-run-full-design"


def test_artifacts_name_the_files_the_refs_point_into(design):
    body = {"in_flight": None, "seen": {"audit-gate:design:demo": "resolved"}, "stale_cleared": []}
    (design / rc.LEDGER_NAME).write_text(json.dumps(body), encoding="utf-8")
    sigs = signals(design, ("[finalizer] resolved — audit-gate/design", "- **Decided**: resolved"))
    (g,) = rg.group_signals(sigs)
    assert g["key"] == "finalizer:audit-gate:design"
    assert sorted(g["artifacts"]) == sorted(["decisions.md", rc.LEDGER_NAME])


def test_no_signals_give_no_groups():
    assert rg.group_signals([]) == []
