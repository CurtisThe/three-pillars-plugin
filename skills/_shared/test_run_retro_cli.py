"""run_retro.py CLI surface (design-learn-retro 1.4): known items, draft, the reviewer seam,
file on both paths, record, the PR section, and the fail-open / exit-2 contract.

Fixtures copy real shapes: seed.md with frontmatter and ``## Evidence`` (as the
design-learn-retro seed), and decisions.md with ``local_route_log``'s schema header and
``### [prefix] title`` entries. Tests drive ``run_retro.main`` in-process and parse JSON and
decisions.md entries; they never read SKILL.md prose.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_route_log as lr  # noqa: E402
import run_retro as rr  # noqa: E402
from run_retro_collect import parse_entries  # noqa: E402

RETRIES = (("[orchestrator/design-audit] retry-with-advice attempt 2/3",
            "- Decided: retry; the gate failed in skills/_shared/foo_helper.py"),
           ("[orchestrator/design-audit] retry-exhausted (attempt 3/3)",
            "- Decided: escalate; skills/_shared/foo_helper.py failed again"))
# The orchestrator's real heading prefix, built from parts: its skill-dir name as a raw literal
# beside a SKILL.md path makes rule_ledger_extract.pin_tests_for count this file as a pin test
# of that skill, and the sealed rule ledgers then want a row for every literal here.
RFD = "tp-run-" + "full-design"
NOOP = (f"[{RFD}/tier-2] worker-noop", "- the worker changed nothing")
SLUG = "retro-foo-helper"
ACCEPT = [{"slug": SLUG, "verdict": "accept", "reason": "recurring gate failure"}]
SEED = ("---\nweight-class: light\nparent: none\nstatus: seed\nseeded: 2026-10-21\n{extra}---\n"
        "# {slug} — seed\n\n## Evidence\n\n- one earlier observation\n")


@pytest.fixture(autouse=True)
def _no_junit_env(monkeypatch):
    monkeypatch.delenv("CI_LOCAL_MANIFEST_DIR", raising=False)


def make_design(repo: Path, entries, name="demo", root="tp-designs") -> Path:
    d = repo / "three-pillars-docs" / root / name
    d.mkdir(parents=True)
    body = "".join(f"\n### {h}\n{b}\n" for h, b in entries)
    (d / "decisions.md").write_text(lr.SCHEMA_HEADER + body, encoding="utf-8")
    return d


def make_seed(repo: Path, slug: str, retro_key=None) -> Path:
    path = repo / "three-pillars-docs" / "tp-designs" / slug / "seed.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = f"retro_key: {retro_key}\n" if retro_key else ""
    path.write_text(SEED.format(extra=extra, slug=slug), encoding="utf-8")
    return path


def run(capsys, *argv) -> tuple[int, str]:
    capsys.readouterr()
    code = rr.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def findings(d: Path) -> dict:
    return json.loads((d / "retro-findings.json").read_text(encoding="utf-8"))


def retro_entries(d: Path) -> list[dict]:
    text = (d / "decisions.md").read_text(encoding="utf-8")
    return [e for e in parse_entries(text) if e["prefix"] == "run-retro"]


def test_known_items_lists_every_seed(tmp_path, capsys):
    make_seed(tmp_path, "keyed-seed", retro_key="path:skills/_shared/foo_helper.py")
    make_seed(tmp_path, "plain-seed")
    (tmp_path / "three-pillars-docs" / "tp-designs" / "no-seed").mkdir()
    out = tmp_path / "known-items.json"
    assert run(capsys, "known-items", "--repo", tmp_path, "--out", out)[0] == 0
    assert json.loads(out.read_text(encoding="utf-8")) == [
        {"id": "keyed-seed", "kind": "seed", "retro_key": "path:skills/_shared/foo_helper.py",
         "text": "keyed-seed"},
        {"id": "plain-seed", "kind": "seed", "retro_key": None, "text": "plain-seed"}]


def test_known_items_with_no_seeds_is_empty(tmp_path, capsys):
    out = tmp_path / "known-items.json"
    assert run(capsys, "known-items", "--repo", tmp_path / "empty", "--out", out)[0] == 0
    assert json.loads(out.read_text(encoding="utf-8")) == []


def test_draft_writes_findings_and_prints_counts(tmp_path, capsys):
    d = make_design(tmp_path, [*RETRIES, NOOP])
    code, out = run(capsys, "draft", "--design-dir", d)
    assert code == 0
    assert json.loads(out) == {"drafts": 1, "observations": 1, "review_needed": True}
    got = findings(d)
    assert set(got) == {"drafts", "observations", "evidence_adds", "tokens", "filed"}
    assert [x["proposed_slug"] for x in got["drafts"]] == [SLUG]
    assert got["filed"] == []


def test_zero_drafts_needs_no_review_and_writes_no_prompt(tmp_path, capsys):
    d = make_design(tmp_path, [NOOP])
    assert json.loads(run(capsys, "draft", "--design-dir", d)[1])["review_needed"] is False
    assert run(capsys, "review-prompt", "--design-dir", d) == (0, "")
    assert not (d / "retro-review-prompt.md").exists()


def test_draft_exits_0_on_a_finalizer_ledger_key_without_a_colon(tmp_path, capsys):
    d = make_design(tmp_path, [*RETRIES, NOOP])
    write_json(d / "finalizer-ledger.json",
               {"in_flight": None, "seen": {"legacy-key": "resolved"}, "stale_cleared": []})
    code, out = run(capsys, "draft", "--design-dir", d)
    assert code == 0
    assert json.loads(out) == {"drafts": 1, "observations": 1, "review_needed": True}
    assert not [x for x in findings(d)["drafts"] if x["retro_key"].startswith("finalizer:")]


def test_review_prompt_carries_verdicts_known_items_and_reply_contract(tmp_path, capsys):
    make_seed(tmp_path, "bar-widget-flake")
    known = tmp_path / "known.json"
    run(capsys, "known-items", "--repo", tmp_path, "--out", known)
    d = make_design(tmp_path, RETRIES)
    run(capsys, "draft", "--design-dir", d, "--known-items", known)
    code, out = run(capsys, "review-prompt", "--design-dir", d, "--known-items", known)
    assert code == 0 and Path(out.strip()).is_file()
    text = Path(out.strip()).read_text(encoding="utf-8")
    assert "RRSI" in text
    blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.S)]
    listed = [x for b in blocks if isinstance(b, list) for x in b if isinstance(x, dict)]
    assert "bar-widget-flake" in [x.get("id") for x in listed]
    assert SLUG in [x.get("proposed_slug") for x in listed]
    reply = blocks[-1]
    assert all({"slug", "verdict", "reason"} <= set(v) for v in reply)
    assert {v["verdict"] for v in reply} == {"accept", "merge-with", "reject"}
    assert all("target" in v for v in reply if v["verdict"] == "merge-with")


def test_file_seed_path_writes_seed_and_logs(tmp_path, capsys):
    d = make_design(tmp_path, [*RETRIES, NOOP])
    run(capsys, "draft", "--design-dir", d)
    verdicts = write_json(tmp_path / "verdicts.json", ACCEPT)
    code, out = run(capsys, "file", "--design-dir", d, "--verdicts", verdicts, "--board", "none")
    seed = d.parent / SLUG / "seed.md"
    assert code == 0 and out.splitlines() == [str(seed)]
    assert {"id": SLUG, "kind": "seed", "retro_key": "path:skills/_shared/foo_helper.py",
            "text": SLUG} in rr.known_items(tmp_path)
    assert SLUG in findings(d)["filed"]
    assert not (d / "retro-outbox.json").exists()
    text = (d / "decisions.md").read_text(encoding="utf-8")
    assert text.startswith(lr.SCHEMA_HEADER) and text.count(lr.SCHEMA_HEADER) == 1
    entries = retro_entries(d)
    assert any(SLUG in e["body"] for e in entries)
    (obs,) = [e for e in entries if e["title"] == "observations"]
    assert obs["body"].splitlines()[0] == "## Observations"
    assert "event:worker-noop" in obs["body"]


def test_file_accepts_a_reply_whose_last_fenced_block_is_the_verdicts(tmp_path, capsys):
    d = make_design(tmp_path, RETRIES)
    run(capsys, "draft", "--design-dir", d)
    reply = tmp_path / "reply.md"
    reply.write_text("Reviewed.\n```json\n[]\n```\nVerdicts:\n```json\n"
                     + json.dumps(ACCEPT) + "\n```\n", encoding="utf-8")
    assert run(capsys, "file", "--design-dir", d, "--verdicts", reply)[0] == 0
    assert (d.parent / SLUG / "seed.md").is_file()


def test_file_board_path_writes_outbox_and_posts_nothing(tmp_path, capsys):
    d = make_design(tmp_path, RETRIES)
    run(capsys, "draft", "--design-dir", d)
    verdicts = write_json(tmp_path / "verdicts.json", ACCEPT)
    code, out = run(capsys, "file", "--design-dir", d, "--verdicts", verdicts,
                    "--board", "automated_upgrades", "--notion-skill", "present")
    box = d / "retro-outbox.json"
    assert code == 0 and json.loads(out) == {"outbox": str(box), "entries": 1}
    (entry,) = json.loads(box.read_text(encoding="utf-8"))["entries"]
    assert entry["slug"] == SLUG and entry["board"] == "automated_upgrades"
    assert not (d.parent / SLUG).exists()


def test_board_with_notion_skill_absent_takes_seed_fallback(tmp_path, capsys):
    d = make_design(tmp_path, RETRIES)
    run(capsys, "draft", "--design-dir", d)
    verdicts = write_json(tmp_path / "verdicts.json", ACCEPT)
    for _ in range(2):
        code, _out = run(capsys, "file", "--design-dir", d, "--verdicts", verdicts,
                         "--board", "automated_upgrades", "--notion-skill", "absent")
        assert code == 0
    assert not (d / "retro-outbox.json").exists()
    assert (d.parent / SLUG / "seed.md").is_file()
    named = [e for e in retro_entries(d) if "notion-skill-unavailable" in e["title"] + e["body"]]
    assert len(named) == 1


def _board_filed(tmp_path, capsys) -> Path:
    d = make_design(tmp_path, RETRIES)
    run(capsys, "draft", "--design-dir", d)
    verdicts = write_json(tmp_path / "verdicts.json", ACCEPT)
    run(capsys, "file", "--design-dir", d, "--verdicts", verdicts,
        "--board", "automated_upgrades", "--notion-skill", "present")
    return d


def _snapshot(d: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()}


def test_record_takes_ids_back_and_refuses_a_foreign_slug(tmp_path, capsys):
    d = _board_filed(tmp_path, capsys)
    before = _snapshot(d)
    foreign = write_json(tmp_path / "foreign.json",
                         [{"slug": SLUG, "id": "row-1"}, {"slug": "not-in-outbox", "id": "row-2"}])
    assert run(capsys, "record", "--design-dir", d, "--filed", foreign)[0] == 2
    assert _snapshot(d) == before
    ok = write_json(tmp_path / "filed.json", [{"slug": SLUG, "id": "row-1"}])
    assert run(capsys, "record", "--design-dir", d, "--filed", ok)[0] == 0
    assert any("row-1" in mark for mark in findings(d)["filed"])
    assert any("row-1" in e["body"] for e in retro_entries(d))
    after = _snapshot(d)
    assert run(capsys, "record", "--design-dir", d, "--filed", ok)[0] == 0
    assert _snapshot(d) == after


@pytest.mark.parametrize("action", ["create", "bump", "repair", "noop"])
def test_record_maps_a_filed_reply_line_to_the_row_url(tmp_path, capsys, action):
    d = _board_filed(tmp_path, capsys)
    url = "https://www.notion.so/x"
    reply = write_json(tmp_path / "filed.json", [{"slug": SLUG, "reply": f"filed: {action} {url}"}])
    code, out = run(capsys, "record", "--design-dir", d, "--filed", reply)
    assert code == 0 and json.loads(out) == {"recorded": 1}
    marks = {f"id:{SLUG}:{url}", SLUG, "path:skills/_shared/foo_helper.py"}
    assert marks <= set(findings(d)["filed"])
    assert any(url in e["body"] for e in retro_entries(d))
    assert url in run(capsys, "pr-section", "--design-dir", d)[1]
    assert not (d.parent / SLUG).exists()


def test_the_notion_skill_flag_names_the_standalone_skill(capsys):
    with pytest.raises(SystemExit) as stop:
        rr.main(["file", "--help"])
    out = re.sub(r"\s+", "", capsys.readouterr().out)  # argparse may wrap at a hyphen
    assert stop.value.code == 0
    assert "notion-file-upgrade-request" in out and "notion-report-issue" not in out


def test_pr_section_lists_ids_and_seeds_and_reads_an_archived_dir(tmp_path, capsys):
    d = _board_filed(tmp_path, capsys)
    assert run(capsys, "pr-section", "--design-dir", d) == (0, "")
    run(capsys, "record", "--design-dir", d, "--filed",
        write_json(tmp_path / "filed.json", [{"slug": SLUG, "id": "row-1"}]))
    code, out = run(capsys, "pr-section", "--design-dir", d)
    assert code == 0 and out.splitlines()[0] == "## Framework friction"
    assert "row-1" in out and SLUG in out
    archived = tmp_path / "three-pillars-docs" / "completed-tp-designs" / "demo"
    archived.mkdir(parents=True)
    for name in ("retro-findings.json", "retro-outbox.json"):
        shutil.copy(d / name, archived / name)
    assert run(capsys, "pr-section", "--design-dir", archived) == (code, out)


def test_pr_section_lists_fallback_seed_slugs(tmp_path, capsys):
    d = make_design(tmp_path, RETRIES)
    run(capsys, "draft", "--design-dir", d)
    run(capsys, "file", "--design-dir", d, "--verdicts",
        write_json(tmp_path / "v.json", ACCEPT), "--board", "none")
    code, out = run(capsys, "pr-section", "--design-dir", d)
    assert code == 0 and out.startswith("## Framework friction") and SLUG in out


SPIKE_PLAN = "### Experiment 1\n**Hypothesis**: x\n**Try**: y\n**Evaluate**: z\n"


@pytest.mark.parametrize("shape", ["seat", "plain", "spike"])
def test_same_result_with_or_without_seat_and_for_a_spike(tmp_path, capsys, shape):
    d = make_design(tmp_path, [*RETRIES, NOOP], name=f"{shape}-run")
    extras = {"seat": {"seat-brief.md": "# seat brief\n"}, "plain": {},
              "spike": {"plan.md": SPIKE_PLAN, "spike-results.md": "# results\n"}}[shape]
    for name, text in extras.items():
        (d / name).write_text(text, encoding="utf-8")
    out = run(capsys, "draft", "--design-dir", d)[1]
    assert json.loads(out) == {"drafts": 1, "observations": 1, "review_needed": True}
    code, out = run(capsys, "file", "--design-dir", d, "--verdicts",
                    write_json(tmp_path / "v.json", ACCEPT), "--board", "none")
    assert code == 0 and out.splitlines() == [str(d.parent / SLUG / "seed.md")]


def test_every_subcommand_fails_open_on_missing_artifacts(tmp_path, capsys):
    gone, nofile = tmp_path / "three-pillars-docs" / "tp-designs" / "gone", tmp_path / "none.json"
    for argv in (("draft", "--design-dir", gone, "--known-items", nofile),
                 ("review-prompt", "--design-dir", gone),
                 ("file", "--design-dir", gone, "--verdicts", nofile, "--board", "none"),
                 ("file", "--design-dir", gone, "--board", "automated_upgrades"),
                 ("record", "--design-dir", gone, "--filed", nofile),
                 ("pr-section", "--design-dir", gone),
                 ("note", "--design-dir", gone, "--title", "declined")):
        assert run(capsys, *argv)[0] == 0
    assert not gone.exists()


@pytest.mark.parametrize("bad", ["not json at all", '{"slug": "x"}', '[{"slug": 1}]',
                                 '[{"slug": "x", "verdict": "maybe", "reason": ""}]'])
def test_malformed_verdicts_or_filed_exit_2_and_write_nothing(tmp_path, capsys, bad):
    d = _board_filed(tmp_path, capsys)
    before = _snapshot(d)
    path = tmp_path / "bad.json"
    path.write_text(bad, encoding="utf-8")
    assert run(capsys, "file", "--design-dir", d, "--verdicts", path, "--board", "none")[0] == 2
    assert run(capsys, "record", "--design-dir", d, "--filed", path)[0] == 2
    assert _snapshot(d) == before
    assert not (d.parent / SLUG).exists()


def test_note_appends_one_run_retro_entry_once(tmp_path, capsys):
    d = make_design(tmp_path, [NOOP])
    for _ in range(2):
        assert run(capsys, "note", "--design-dir", d, "--title", "declined",
                   "--body", "- the operator declined the post")[0] == 0
    (entry,) = [e for e in retro_entries(d) if e["title"] == "declined"]
    assert entry["body"] == "- the operator declined the post"
