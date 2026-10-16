"""The A/B shadow arm — one slot's prep shadowed, the Opus alias kept, and the
real `angles.json` bytes untouched.

design: cheap-tier-review-prep (Task 7.4)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_prep  # noqa: E402 — first: it puts skills/_shared on sys.path
import cheap_ab  # noqa: E402
import dispatch_log  # noqa: E402
import review_prep_ab as ab  # noqa: E402
import round_scratch as rs  # noqa: E402

PR = "https://github.com/o/r/pull/42"
A1, A2 = "correctness-leak", "edge-cases"
ANGLES = [
    {"name": A1, "role": "confirmer", "model": "opus",
     "prompt": "Hunt fail-closed/correctness leaks."},
    {"name": A2, "role": "finder", "model": "opus",
     "prompt": "Hunt edge cases in loop-added code."},
]
SLICE = {"hunks": [{"file": "a.py", "hunk": "@@ -1 +1 @@\n-a\n+b\n"}]}
REFS = {"refs": [{"path": "a.py", "line": 1, "note": "n"}]}
DIFF = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
SPECS = {"review_slice": {"rung": "local-medium"},
         "review_refs": {"rung": "local-medium"}}


def _round(tmp, skipped=None):
    angles = [dict(a) for a in ANGLES]
    for a in angles:
        if skipped and a["name"] in skipped:
            a["skipped"] = skipped[a["name"]]
    root = tmp / "proof"
    return rs.prepare(root, PR, angles, base="b0", head="h1", effort="high",
                      state_path=str(tmp / "s.json"), log_path=str(tmp / "l.md"))


def _work(tmp, accepted):
    adir = tmp / "W" / "accepted"
    adir.mkdir(parents=True, exist_ok=True)
    for name, obj in accepted.items():
        (adir / name).write_text(json.dumps(obj), encoding="utf-8")
    (tmp / "W" / "diff.patch").write_text(DIFF, encoding="utf-8")
    return tmp / "W"


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_prefixes_match_cheap_ab():
    assert ab.PAIR_PREFIX == cheap_ab.PAIR_PREFIX == "rp:"
    assert ab.DRAFT_PREFIX == cheap_ab.DRAFT_PREFIX == "rp-draft:"
    assert ab.SHADOW == "shadow"


def _pair(slot, angle):
    pid = f"rp:42:r1:{angle}"
    return [
        {"slot": slot, "ab_pair": pid, "ab_arm": "base", "oracle": "pass",
         "findings": {"n": 0, "classes": []}, "shape": "s", "tokens": 100},
        {"slot": slot, "ab_pair": pid, "ab_arm": "prep", "oracle": "pass",
         "findings": {"n": 0, "classes": []}, "shape": "s", "tokens": 50},
    ]


def test_pick_slot_rotation():
    busy = _pair("review_slice", A1)
    assert ab.pick_slot(busy, A1, ("review_slice", "review_refs")) == "review_refs"
    assert ab.pick_slot(busy, A1, ("review_slice", "repro_scaffold")) == "review_slice"
    assert ab.pick_slot([], A1, ("ci_log_triage", "review_refs")) == "review_refs"
    assert ab.pick_slot([], A1, ("repro_scaffold",)) is None
    assert ab.pick_slot([], A1, ()) is None


def test_shadow_keeps_opus_alias_and_leaves_real_manifest(tmp_path):
    r = _round(tmp_path)
    before = (r / "angles.json").read_bytes()
    w = _work(tmp_path, {f"review_slice--{A1}.json": SLICE,
                         "review_refs--_.json": REFS})
    specs = {
        "review_slice": {"rung": "local-medium", "agent_ref": "x:tp-drafter",
                         "model": "haiku"},
        "review_refs": {"rung": "local-medium", "agent_ref": "y:tp-drafter",
                        "model": "haiku"},
    }
    path = ab.shadow(r, w, specs, [])
    assert path == r / "prep" / "shadow" / "angles.json"
    assert (r / "angles.json").read_bytes() == before  # the real manifest is untouched
    real = {e["name"]: e for e in json.loads(before)["angles"]}
    man = json.loads(path.read_text(encoding="utf-8"))
    assert {man["pr_url"], man["round"], man["ordinal"], man["head"]} == \
        {PR, 1, "r1", "h1"}
    entries = {e["name"]: e for e in man["angles"]}
    assert set(entries) == {A1, A2}
    assert entries[A1]["slot"] == "review_slice"  # the first slot's order wins the tie
    assert entries[A2]["slot"] == "review_refs"
    for name, e in entries.items():
        assert e["agent"] == real[name]["agent"]
        assert e["agent_ref"] == real[name]["agent_ref"]  # never a `specs` field
        assert e["dispatch_model"] == real[name]["dispatch_model"]
        assert e["pair_id"] == f"rp:42:r1:{name}"
        shadow_dir = r / "prep" / "shadow"
        want = (real[name]["prompt"]
                .replace(f"--round-dir {r} ", f"--round-dir {shadow_dir} ")
                .replace(f"TP_SCRATCH: {r / name}\n", f"TP_SCRATCH: {shadow_dir / name}\n")
                .replace(real[name]["reply_path"], e["reply_path"])
                + review_prep.prompt_suffix(shadow_dir / f"{name}.md"))
        # Only the delivery (put line, scratch, reply path) is re-pointed, plus one prep line.
        assert e["prompt"] == want
        assert Path(e["reply_path"]).parent.is_dir()  # the reply dir exists, file not
        assert not Path(e["reply_path"]).exists()
    md1 = (r / "prep" / "shadow" / f"{A1}.md").read_text(encoding="utf-8")
    md2 = (r / "prep" / "shadow" / f"{A2}.md").read_text(encoding="utf-8")
    assert "## Hunks" in md1 and "## Refs" not in md1  # only the picked slot's items
    assert "## Refs" in md2 and "## Hunks" not in md2
    assert not w.exists()  # W was moved to R/prep/work
    assert (r / "prep" / "work" / "accepted" / "review_refs--_.json").is_file()
    assert not (r / "prep" / "shadow" / "_stage").exists()  # the stage dir is removed
    # A second call needs no `work` (already in place) and reuses the real manifest.
    again = ab.shadow(r, None, SPECS, [])
    assert (r / "angles.json").read_bytes() == before
    assert {e["name"] for e in json.loads(again.read_text(encoding="utf-8"))["angles"]} \
        == {A1, A2}


def test_shadow_skips_uncovered_angles(tmp_path):
    r = _round(tmp_path, skipped={A2: "local backend absent"})
    w = _work(tmp_path, {f"review_slice--{A1}.json": SLICE})
    man = json.loads(ab.shadow(r, w, {"review_slice": {"rung": "local-medium"}},
                               []).read_text(encoding="utf-8"))
    assert [e["name"] for e in man["angles"]] == [A1]
    assert not (r / "prep" / "shadow" / f"{A2}.md").exists()
    assert not (r / "prep" / "shadow" / A2).exists()


def test_candidates_gate_each_slot_on_its_own_file(tmp_path):
    # A round with CI logs but no shared refs: each angle's candidate slot must
    # come from its OWN accepted file, so an angle without a slice is not
    # wrongly covered by the ci slot's files (and thus does not lose its entry).
    r = _round(tmp_path)
    CI = {"quote": "E   assert 1 == 2", "step": "Run tests"}
    w = _work(tmp_path, {f"review_slice--{A1}.json": SLICE,
                         "ci_log_triage--build.json": CI})
    specs = {"review_slice": {"rung": "local-medium"},
             "review_refs": {"rung": "local-medium"},
             "ci_log_triage": {"rung": "local-medium"}}
    man = json.loads(ab.shadow(r, w, specs, []).read_text(encoding="utf-8"))
    active = ab._active_slots(specs)
    adir = r / "prep" / "work" / "accepted"
    entries = {e["name"]: e for e in man["angles"]}
    assert set(entries) == {A1, A2}  # A2 keeps its shadow entry
    assert entries[A2]["slot"] == "ci_log_triage"
    md2 = (r / "prep" / "shadow" / f"{A2}.md").read_text(encoding="utf-8")
    assert "## Failed CI checks" in md2 and "## Hunks" not in md2
    assert entries[A1]["slot"] == "review_slice"  # tie broken by REVIEW_PREP_SLOTS order
    assert ab._candidates_for(A2, active, adir) == ["ci_log_triage"]


def test_findings_of():
    reply = ("```json\n{\"findings\": [{\"file\": \"a.py\", \"class\": \"c1\"},\n"
             "{\"file\": \"b.py\", \"class\": \"c0\"}]}\n```")
    assert ab.findings_of(reply) == {"n": 2, "classes": [["a.py", "c1"], ["b.py", "c0"]]}
    assert ab.findings_of("```json\n{\"findings\": []}\n```") == {"n": 0, "classes": []}
    assert ab.findings_of("```json\n[]\n```") is None  # the pre-M27 bare list is unparseable
    assert ab.findings_of("Looks fine to me, no issues.") is None


def test_record_argv_and_roundtrip(tmp_path):
    r = _round(tmp_path)
    w = _work(tmp_path, {f"review_slice--{A1}.json": SLICE,
                         f"review_slice--{A2}.json": SLICE,
                         "review_refs--_.json": REFS})
    ab.shadow(r, w, SPECS, [])
    real = {e["name"]: e for e in json.loads(
        (r / "angles.json").read_text(encoding="utf-8"))["angles"]}
    shadow_man = json.loads(
        (r / "prep" / "shadow" / "angles.json").read_text(encoding="utf-8"))
    srep = {e["name"]: e for e in shadow_man["angles"]}
    base_reply = "```json\n{\"findings\": [{\"file\": \"a.py\", \"class\": \"c1\"}]}\n```\n"
    for name, e in srep.items():
        (r / name / "reply.md").write_text(base_reply, encoding="utf-8")
    Path(srep[A1]["reply_path"]).write_text("```json\n{\"findings\": []}\n```\n", encoding="utf-8")
    Path(srep[A2]["reply_path"]).write_text(
        "I cannot parse this one, sorry.", encoding="utf-8")
    ids = {A1: {"real": "agent-r1", "shadow": "agent-p1"},
           A2: {"real": "agent-r2"}}  # no shadow id → no argv for A2
    argvs = ab.record_argv(r, ids, tmp_path / "design")
    assert len(argvs) == 2  # A2 dropped: unparseable shadow reply AND missing id
    base, prep = argvs
    want = {
        "base": ("agent-r1", {"n": 1, "classes": [["a.py", "c1"]]}),
        "prep": ("agent-p1", {"n": 0, "classes": []}),
    }
    for row, arm in ((base, "base"), (prep, "prep")):
        assert row[0] == "record"
        assert _flag(row, "--role") == "review_prep_ab"
        assert _flag(row, "--outcome") == "done"
        assert _flag(row, "--slot") == srep[A1]["slot"]
        assert _flag(row, "--oracle") == "pass"
        assert _flag(row, "--rung") == "opus"  # on BOTH rows
        assert _flag(row, "--ab-arm") == arm
        assert _flag(row, "--agent-id") == want[arm][0]
        assert _flag(row, "--reason") == f"review-prep ab {arm}: {A1}"
        assert _flag(row, "--agent") == real[A1]["agent"]
        assert json.loads(_flag(row, "--findings")) == want[arm][1]
    assert _flag(base, "--ab-pair") == _flag(prep, "--ab-pair") == srep[A1]["pair_id"]
    real_man = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    diff_text = (r / "prep" / "work" / "diff.patch").read_text(encoding="utf-8")
    assert _flag(base, "--shape") == review_prep.shape(real_man, diff_text) == \
        _flag(prep, "--shape")
    # Round-trip: both argvs are accepted by dispatch_log and land as ndjson rows.
    design = tmp_path / "design"
    design.mkdir()
    for row in argvs:
        assert dispatch_log.main(row + ["--root", str(tmp_path)]) == 0
    lines = (design / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(x) for x in lines]
    assert [x["ab_arm"] for x in rows] == ["base", "prep"]
    for x in rows:
        assert x["rung"] == "opus" and x["model"] == "opus"
        assert isinstance(x["findings"], dict) and x["slot"] == srep[A1]["slot"]
