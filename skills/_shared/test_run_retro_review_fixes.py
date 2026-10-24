"""run-retro fixes from PR review round 1 (design-learn-retro): an archived design's seeds land
under ``tp-designs/``, each finalizer halt counts once, and refs are pointers, never titles.

Each test failed on the reviewed head and passes after the fix. Tests drive the modules and
the ``run_retro.main`` CLI in-process under ``tmp_path``.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_retro as rr  # noqa: E402
import run_retro_collect as rc  # noqa: E402
import run_retro_file as rf  # noqa: E402
import run_retro_filter as rfl  # noqa: E402
import run_retro_group as rg  # noqa: E402

DRAFT = {"retro_key": "path:skills/_shared/worker_root.py", "proposed_slug": "retro-worker-root",
         "type": "Bug", "shapes": ["path:skills/_shared/worker_root.py", "worker-root"],
         "evidence": ["decisions.md:L1"], "count": 2}
ACCEPT = [{"slug": "retro-worker-root", "verdict": "accept", "reason": "recurs"}]
HALT = "finalizer:halt:base-sync-deferred"
RESOLVED = "### [finalizer] resolved — halt/base-sync-deferred\n- **Decided**: resolved\n\n"


def _archived(tmp_path) -> Path:
    design = tmp_path / "three-pillars-docs" / "completed-tp-designs" / "already-done"
    design.mkdir(parents=True)
    return design


def _active(tmp_path) -> Path:
    design = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    design.mkdir(parents=True)
    return design


def _ledger(design: Path, seen: dict) -> None:
    body = {"in_flight": None, "stale_cleared": [], "seen": seen}
    (design / "finalizer-ledger.json").write_text(json.dumps(body), encoding="utf-8")


def _halt_group(design: Path, tmp_path) -> dict:
    groups = rg.group_signals(rc.collect(design, repo_root=tmp_path, env={})["signals"])
    (group,) = [g for g in groups if g["key"] == HALT]
    return group


# ---- an archived design's fallback seed -----------------------------------------------

def test_fallback_seed_from_an_archived_design_lands_under_tp_designs(tmp_path):
    design = _archived(tmp_path)
    res = rf.file_drafts([DRAFT], ACCEPT, board=None, design_dir=design)
    want = tmp_path / "three-pillars-docs" / "tp-designs" / "retro-worker-root" / "seed.md"
    assert res["seeds"] == [str(want)] and want.is_file()
    assert not (design.parent / "retro-worker-root").exists()
    assert [i["id"] for i in rr.known_items(tmp_path)] == ["retro-worker-root"]


def test_an_archived_design_adds_evidence_to_the_existing_tp_designs_seed(tmp_path):
    design = _archived(tmp_path)
    rf.file_drafts([DRAFT], ACCEPT, board=None, design_dir=design)
    again = {**DRAFT, "retro_key": "path:skills/_shared/worker_root.py#2"}
    res = rf.file_drafts([again], ACCEPT, board=None, design_dir=design)
    seed = tmp_path / "three-pillars-docs" / "tp-designs" / "retro-worker-root" / "seed.md"
    assert res["seeds"] == [] and res["modified_seeds"] == [str(seed)]
    assert "worker_root.py#2" in seed.read_text(encoding="utf-8")


def test_an_active_design_still_seeds_beside_itself(tmp_path):
    design = _active(tmp_path)
    res = rf.file_drafts([DRAFT], ACCEPT, board=None, design_dir=design)
    assert res["seeds"] == [str(design.parent / "retro-worker-root" / "seed.md")]


def test_pr_section_path_is_the_seed_written_for_an_archived_design(tmp_path, capsys):
    design = _archived(tmp_path)
    marks = {"drafts": [DRAFT], "observations": [], "evidence_adds": [], "filed": []}
    (design / "retro-findings.json").write_text(json.dumps(marks), encoding="utf-8")
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps(ACCEPT), encoding="utf-8")
    assert rr.main(["file", "--design-dir", str(design), "--verdicts", str(verdicts)]) == 0
    capsys.readouterr()
    assert rr.main(["pr-section", "--design-dir", str(design)]) == 0
    shown = re.search(r"three-pillars-docs/tp-designs/[\w.-]+/seed\.md",
                      capsys.readouterr().out).group(0)
    assert (tmp_path / shown).is_file(), shown


# ---- each finalizer halt is its own signal --------------------------------------------

def test_two_halts_of_one_signal_in_one_run_count_as_a_recurrence(tmp_path):
    design = _active(tmp_path)
    _ledger(design, {"halt:base-sync-deferred:demo:585fe025": "resolved",
                     "halt:base-sync-deferred:demo:9c1d2e3f": "resolved"})
    (design / "decisions.md").write_text(RESOLVED * 2, encoding="utf-8")
    group = _halt_group(design, tmp_path)
    assert group["count"] == 2, group
    drafts = rfl.apply_rrsi([group], [])["drafts"]
    assert [d["retro_key"] for d in drafts] == [HALT]


def test_one_ledger_key_logged_twice_in_decisions_counts_two(tmp_path):
    design = _active(tmp_path)
    _ledger(design, {"halt:base-sync-deferred:demo:585fe025": "resolved"})
    (design / "decisions.md").write_text(RESOLVED * 2, encoding="utf-8")
    assert _halt_group(design, tmp_path)["count"] == 2


def test_one_halt_with_one_decisions_entry_stays_one_signal(tmp_path):
    design = _active(tmp_path)
    _ledger(design, {"halt:base-sync-deferred:demo:585fe025": "resolved"})
    (design / "decisions.md").write_text(RESOLVED, encoding="utf-8")
    group = _halt_group(design, tmp_path)
    assert group["count"] == 1
    assert group["artifacts"] == ["decisions.md", "finalizer-ledger.json"]


def test_finalizer_count_is_independent_of_entry_order_without_a_ledger(tmp_path):
    escalate = "### [finalizer] escalate — halt/base-sync-deferred\n- **Decided**: escalate\n\n"
    counts = []
    for order in (RESOLVED + escalate, escalate + RESOLVED):
        design = _active(tmp_path / str(len(counts)))
        (design / "decisions.md").write_text(order, encoding="utf-8")
        counts.append(_halt_group(design, tmp_path)["count"])
    assert counts[0] == counts[1], counts


# ---- refs are pointers, never a heading's free text -----------------------------------

def test_board_outbox_carries_no_heading_free_text(tmp_path):
    d = _active(tmp_path)
    (d / "decisions.md").write_text(
        "# Decisions\n\n"
        "### [orchestrator/tier-3] retry-exhausted skills/_shared/foo.py: db password hunter2"
        " on db7.acme-internal.corp\n- failed\n\n"
        "### [orchestrator/tier-3] retry-exhausted skills/_shared/foo.py: customer AcmeCorp"
        " invoice 4471\n- failed again\n", encoding="utf-8")
    known = tmp_path / "known.json"
    known.write_text("[]", encoding="utf-8")
    assert rr.main(["draft", "--design-dir", str(d), "--known-items", str(known),
                    "--repo", str(tmp_path)]) == 0
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps([{"slug": "retro-foo", "verdict": "accept",
                                     "reason": "recurs"}]), encoding="utf-8")
    assert rr.main(["file", "--design-dir", str(d), "--verdicts", str(verdicts),
                    "--board", "automated_upgrades", "--notion-skill", "present"]) == 0
    box = json.loads((d / "retro-outbox.json").read_text(encoding="utf-8"))
    assert box["entries"], "the accepted draft reaches the sealed outbox"
    sent = json.dumps([e["payload"] for e in box["entries"]])
    for value in ("hunter2", "acme-internal", "AcmeCorp", "4471"):
        assert value not in sent, f"run free text {value!r} is in the board payload"
    assert box["entries"][0]["payload"]["evidence"] == ["decisions.md:L3", "decisions.md:L6"]


def test_a_finalizer_ref_points_at_its_line_and_carries_no_title(tmp_path):
    design = _active(tmp_path)
    _ledger(design, {"halt:base-sync-deferred:demo:585fe025": "resolved"})
    (design / "decisions.md").write_text("# Decisions\n\n" + RESOLVED, encoding="utf-8")
    (ref,) = _halt_group(design, tmp_path)["refs"]
    assert ref == ("finalizer-ledger.json: halt:base-sync-deferred:demo:585fe025; "
                   "decisions.md:L3")
