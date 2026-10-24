"""Tests for run_retro_file.py (design-learn-retro 1.3): outbox, seed fallback, leak backstop."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_retro_file as rf  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

FIELDS = ("package", "type", "source_run", "design", "root_cause_group", "evidence",
          "reviewer_verdict", "version", "recurrence", "rrsi_flags")
MANIFEST = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
# secret-looking strings are built by concatenation so this file trips no scanner
ENV_LEAK = "API_" + "KEY=" + "abc123def456"
GH_LEAK = "gh" + "p_" + "A" * 24
SK_LEAK = "s" + "k-" + "B" * 20

FOREIGN_SEED = """---
weight-class: light
parent: none
status: seed
seeded: 2026-10-21
---
# foreign — seed

## Evidence

- one earlier observation

## Rulings

- none
"""


def draft(key="block:permission-card", slug="retro-permission-card", **over) -> dict:
    d = {"retro_key": key, "proposed_slug": slug, "skill": "tp-phase-implement",
         "type": "Bug", "shapes": [key, "permission-card"],
         "evidence": ["decisions.md#L10", "decisions.md#L40"], "count": 3,
         "operator_touch": True, "rerun": False, "candidates": []}
    d.update(over)
    return d


def verdict(slug="retro-permission-card", v="accept", reason="real", **over) -> dict:
    out = {"slug": slug, "verdict": v, "reason": reason}
    out.update(over)
    return out


@pytest.fixture()
def design_dir(tmp_path):
    d = tmp_path / "tp-designs" / "this-design"
    d.mkdir(parents=True)
    return d


def outbox(design_dir):
    p = design_dir / "retro-outbox.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_accept_lands_in_outbox_with_exact_payload_keys(design_dir):
    res = rf.file_drafts([draft()], [verdict()], board="automated_upgrades", design_dir=design_dir)
    box = outbox(design_dir)
    assert box["board"] == "automated_upgrades"
    (entry,) = box["entries"]
    assert set(entry) == {"slug", "retro_key", "board", "payload"}
    assert tuple(entry["payload"]) == rf.BOARD_FIELDS == FIELDS
    assert entry["payload"]["design"] == "this-design"
    assert entry["payload"]["recurrence"] == 3
    assert entry["retro_key"] == "block:permission-card"  # ours, beside the payload
    assert "retro_key" not in entry["payload"] and "root_cause" not in entry["payload"]
    assert res["filed_marks"] == []  # F1: only a recorded row marks an outbox entry filed
    assert res["seeds"] == []


def test_payload_carries_the_shapes_the_upgrade_skill_takes(design_dir):
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    both = draft(operator_touch=True, rerun=True)
    rf.file_drafts([both, draft(key="k:i", slug="s-idea", type="Idea", operator_touch=False)],
                   [verdict(), verdict("s-idea")], board="automated_upgrades",
                   design_dir=design_dir)
    bug, idea = (e["payload"] for e in outbox(design_dir)["entries"])
    assert (bug["package"], bug["type"], idea["type"]) == ("three-pillars", "Bug", "Idea")
    assert bug["version"] == version == rf.plugin_version()
    assert bug["root_cause_group"] == "block:permission-card, permission-card"
    assert bug["source_run"] == "this-design" and bug["reviewer_verdict"].startswith("accept")
    assert bug["rrsi_flags"] == ["operator-touch", "rerun"]  # the skill takes [a-z0-9-] tokens
    assert idea["rrsi_flags"] == []
    typeless = {k: v for k, v in draft().items() if k != "type"}
    assert rf.to_payload(typeless, verdict(), "d")["type"] == "Idea"


def test_plugin_version_fails_open_to_unknown(tmp_path):
    assert rf.plugin_version(tmp_path / "missing.json") == "unknown"
    for body in ("not json", "[]", '{"version": 3}', "{}"):
        bad = tmp_path / "plugin.json"
        bad.write_text(body, encoding="utf-8")
        assert rf.plugin_version(bad) == "unknown", body
    bad.write_text('{"version": "9.9.9"}', encoding="utf-8")
    assert rf.plugin_version(bad) == "9.9.9"


@pytest.mark.parametrize("action", ["create", "bump", "repair", "noop"])
def test_a_filed_reply_maps_to_its_row_url(action):
    url = "https://www.notion.so/x"
    assert rf.parse_reply(f"filed: {action} {url}") == ("filed", url)
    assert rf.parse_reply(f"Refused once.\nfiled: {action} {url}\n") == ("filed", url)


def test_a_not_filed_reply_maps_to_its_reason_and_anything_else_to_none():
    assert rf.parse_reply("not filed: automated upgrades are off") == (
        "not filed", "automated upgrades are off")
    for bad in ("", "filed: create", "filed: merge https://www.notion.so/x", "error: boom",
                "filed: create https://a.b/c extra"):
        assert rf.parse_reply(bad) is None, bad


def test_feedback_board_raises_and_writes_nothing(design_dir):
    with pytest.raises(ValueError):
        rf.file_drafts([draft()], [verdict()], board="feedback", design_dir=design_dir)
    assert outbox(design_dir) is None


def test_no_board_writes_seed_not_outbox(design_dir):
    res = rf.file_drafts([draft()], [verdict()], board=None, design_dir=design_dir)
    assert outbox(design_dir) is None
    seed = design_dir.parent / "retro-permission-card" / "seed.md"
    text = seed.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    for needle in ("status: seed", "origin: run-retro", "upstream: three-pillars",
                   "weight-class: light", "retro_key: block:permission-card", "## Evidence",
                   "decisions.md#L10"):
        assert needle in text
    assert res["seeds"] == [str(seed)]
    assert str(seed) in res["modified_seeds"]
    assert "retro-permission-card" in res["filed_marks"]


def test_fallback_seed_is_stamped_light_and_keeps_its_other_frontmatter(design_dir):
    rf.file_drafts([draft()], [verdict()], board=None, design_dir=design_dir)
    seed = design_dir.parent / "retro-permission-card" / "seed.md"
    assert parse_frontmatter(seed.read_text(encoding="utf-8")) == {
        "weight-class": "light", "status": "seed", "origin": "run-retro",
        "upstream": "three-pillars", "retro_key": "block:permission-card", "type": "Bug",
        "skill": "tp-phase-implement", "recurrence": "3"}


def test_fallback_reason_is_returned(design_dir):
    res = rf.file_drafts([draft()], [verdict()], board=None, design_dir=design_dir,
                         fallback_reason="notion-skill-unavailable")
    assert res["fallback_reason"] == "notion-skill-unavailable"
    assert len(res["seeds"]) == 1


@pytest.mark.parametrize("leak", [ENV_LEAK, GH_LEAK, SK_LEAK, "xo" + "xb-" + "1234567890"])
def test_leaky_draft_is_refused_even_when_accepted(design_dir, leak):
    assert rf.leaks({"evidence": ["ok", f"note {leak}"]})
    bad = draft(evidence=[f"note {leak}"])
    res = rf.file_drafts([bad], [verdict()], board="automated_upgrades", design_dir=design_dir)
    assert len(res["refused"]) == 1
    assert (outbox(design_dir) or {"entries": []})["entries"] == []
    res = rf.file_drafts([bad], [verdict()], board=None, design_dir=design_dir)
    assert len(res["refused"]) == 1 and res["seeds"] == []
    assert not (design_dir.parent / "retro-permission-card").exists()


def test_leaks_clean_draft_is_empty():
    assert not rf.leaks(draft())


def test_reject_is_never_filed_and_keeps_reason(design_dir):
    res = rf.file_drafts([draft()], [verdict(v="reject", reason="one-off")],
                         board="automated_upgrades", design_dir=design_dir)
    assert res["rejected"][0]["reason"] == "one-off"
    assert outbox(design_dir)["entries"] == []


def test_missing_verdict_is_not_filed(design_dir):
    res = rf.file_drafts([draft()], [], board="automated_upgrades", design_dir=design_dir)
    assert outbox(design_dir)["entries"] == []
    assert len(res["rejected"]) == 1


def test_merge_with_adds_evidence_not_entry(design_dir):
    other = design_dir.parent / "known-seed"
    other.mkdir()
    (other / "seed.md").write_text(FOREIGN_SEED, encoding="utf-8")
    res = rf.file_drafts([draft()], [verdict(v="merge-with", target="known-seed")],
                         board=None, design_dir=design_dir)
    assert res["seeds"] == []
    assert not (design_dir.parent / "retro-permission-card").exists()
    assert res["evidence_adds"][0]["seed"] == "known-seed"
    text = (other / "seed.md").read_text(encoding="utf-8")
    assert "- evidence (run-retro): block:permission-card decisions.md#L10 decisions.md#L40" in text


def test_existing_slug_becomes_evidence(design_dir):
    existing = design_dir.parent / "retro-permission-card"
    existing.mkdir()
    (existing / "seed.md").write_text(FOREIGN_SEED, encoding="utf-8")
    res = rf.file_drafts([draft()], [verdict()], board=None, design_dir=design_dir)
    assert res["seeds"] == []
    assert res["evidence_adds"][0]["seed"] == "retro-permission-card"
    assert (existing / "seed.md").read_text(encoding="utf-8").count("evidence (run-retro)") == 1
    with pytest.raises(FileExistsError):
        rf.write_seed(draft(), design_dir)


def test_already_filed_skips_draft(design_dir):
    res = rf.file_drafts([draft()], [verdict()], board="automated_upgrades",
                         design_dir=design_dir, already_filed=["block:permission-card"])
    assert outbox(design_dir)["entries"] == []
    res = rf.file_drafts([draft()], [verdict()], board=None, design_dir=design_dir,
                         already_filed=["retro-permission-card"])
    assert res["seeds"] == []


def _foreign(design_dir):
    foreign = design_dir.parent / "foreign"
    foreign.mkdir()
    (foreign / "seed.md").write_text(FOREIGN_SEED, encoding="utf-8")
    return foreign / "seed.md"


ADD = {"seed": "foreign", "kind": "Bug", "retro_key": "block:x", "evidence": ["a#1", "b#2"], "count": 2}


def test_evidence_add_is_idempotent_on_foreign_seed(design_dir):
    path = _foreign(design_dir)
    first = rf.file_drafts([], [], board=None, design_dir=design_dir, evidence_adds=[ADD])
    line = "- evidence (run-retro): block:x a#1 b#2"
    text = path.read_text(encoding="utf-8")
    assert text.count(line) == 1
    assert text.index("## Evidence") < text.index(line) < text.index("## Rulings")
    assert first["modified_seeds"] == [str(path)]
    assert first["filed_marks"] == ["evidence:foreign@block:x"]
    again = rf.file_drafts([], [], board=None, design_dir=design_dir, evidence_adds=[ADD],
                           already_filed=first["filed_marks"])
    assert again["modified_seeds"] == []
    assert path.read_text(encoding="utf-8").count(line) == 1
    rf.file_drafts([], [], board=None, design_dir=design_dir, evidence_adds=[ADD])
    assert path.read_text(encoding="utf-8").count(line) == 1


def test_evidence_not_written_on_board_path(design_dir):
    path = _foreign(design_dir)
    res = rf.file_drafts([], [], board="automated_upgrades", design_dir=design_dir,
                         evidence_adds=[ADD])
    assert path.read_text(encoding="utf-8") == FOREIGN_SEED
    assert res["evidence_adds"][0]["seed"] == "foreign"
    assert res["modified_seeds"] == []


def test_outbox_never_holds_rejected_refused_or_feedback(design_dir):
    drafts = [draft(key="k:ok", slug="s-ok"), draft(key="k:no", slug="s-no"),
              draft(key="k:leak", slug="s-leak", evidence=[ENV_LEAK]),
              draft(key="k:nov", slug="s-nov")]
    verdicts = [verdict("s-ok"), verdict("s-no", "reject"), verdict("s-leak")]
    rf.file_drafts(drafts, verdicts, board="automated_upgrades", design_dir=design_dir)
    slugs = [e["slug"] for e in outbox(design_dir)["entries"]]
    assert slugs == ["s-ok"]
    assert all(e["board"] != "feedback" for e in outbox(design_dir)["entries"])


def test_a_slug_outside_a_z_0_9_hyphen_is_refused_and_creates_no_directory(design_dir):
    bad_slugs = ["retro-test-b[../../x]", "-rf", "retro-", "a--b"]
    for bad in bad_slugs:
        res = rf.file_drafts([draft(slug=bad)], [verdict(slug=bad)], board=None,
                             design_dir=design_dir)
        why = f"slug {bad!r} under test; refused slugs under test: {bad_slugs}; result: {res}"
        assert [r["slug"] for r in res["refused"]] == [bad], why
        assert res["seeds"] == [] and res["modified_seeds"] == [], why
        assert sorted(p.name for p in design_dir.parent.iterdir()) == ["this-design"], why
    good = "retro-good-1"
    res = rf.file_drafts([draft(slug=good)], [verdict(slug=good)], board=None,
                         design_dir=design_dir)
    why = f"accepted slug {good!r}; refused slugs under test: {bad_slugs}; result: {res}"
    assert res["refused"] == [], why
    assert [Path(p).parent.name for p in res["seeds"]] == [good], why


def test_a_leaking_verdict_reason_is_refused_from_the_outbox(design_dir):
    # F2: the reason lands in payload.reviewer_verdict, so leaks() runs over the built entry
    reason = f"{ENV_LEAK} and {GH_LEAK}"
    assert not rf.leaks(draft())
    res = rf.file_drafts([draft()], [verdict(reason=reason)], board="automated_upgrades",
                         design_dir=design_dir)
    assert [r["slug"] for r in res["refused"]] == ["retro-permission-card"]
    assert res["outbox"] == [] and res["filed_marks"] == []
    assert outbox(design_dir)["entries"] == []
    assert "abc123def456" not in (design_dir / "retro-outbox.json").read_text(encoding="utf-8")
    clean = rf.file_drafts([draft()], [verdict(reason="recurs across three runs")],
                           board="automated_upgrades", design_dir=design_dir)
    assert clean["refused"] == []
    (entry,) = outbox(design_dir)["entries"]
    assert entry["payload"]["reviewer_verdict"] == "accept: recurs across three runs"


@pytest.mark.parametrize("board", [None, "automated_upgrades"])
def test_merge_with_an_unsafe_target_is_refused_and_writes_nothing(tmp_path, board):
    # F3: the target becomes a path under tp-designs, so it must fullmatch SAFE_SLUG
    design_dir = tmp_path / "deep" / "tp-designs" / "this-design"
    design_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "seed.md").write_text(FOREIGN_SEED, encoding="utf-8")

    def tree():
        return sorted(p for p in tmp_path.rglob("*") if p.name != "retro-outbox.json")

    before = tree()
    for target in ("../../outside", "Known_Seed", "a/b", ""):
        res = rf.file_drafts([draft()], [verdict(v="merge-with", target=target)], board=board,
                             design_dir=design_dir)
        why = f"target {target!r}; result: {res}"
        assert [r["slug"] for r in res["refused"]] == ["retro-permission-card"], why
        assert res["evidence_adds"] == [] and res["modified_seeds"] == [], why
        assert res["seeds"] == [] and res["outbox"] == [], why
        assert (outside / "seed.md").read_text(encoding="utf-8") == FOREIGN_SEED, why
        assert tree() == before, why
    known = design_dir.parent / "known-seed"
    known.mkdir()
    (known / "seed.md").write_text(FOREIGN_SEED, encoding="utf-8")
    res = rf.file_drafts([draft()], [verdict(v="merge-with", target="known-seed")], board=board,
                         design_dir=design_dir)
    assert res["refused"] == [] and res["evidence_adds"][0]["seed"] == "known-seed"
    text = (known / "seed.md").read_text(encoding="utf-8")
    assert ("- evidence (run-retro): block:permission-card" in text) == (board is None)


def test_two_drafts_with_separate_verdicts_write_two_seeds(design_dir):
    a, b = ("path:skills/tp-design/SKILL.md", "retro-tp-design-skill"), (
        "path:skills/tp-spike/SKILL.md", "retro-tp-spike-skill")
    res = rf.file_drafts([draft(k, s) for k, s in (a, b)], [verdict(s) for _, s in (a, b)],
                         board=None, design_dir=design_dir)
    assert sorted(Path(p).parent.name for p in res["seeds"]) == [a[1], b[1]]
    assert res["evidence_adds"] == []
