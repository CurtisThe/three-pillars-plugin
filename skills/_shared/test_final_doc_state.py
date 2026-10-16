"""Tests for final_doc_state: `close` (row move, then pending flip) and `check`.

Oracles: example (the exact payloads the plan names) and property (every path
`close` reports is a living doc or its archive), per
skills/_shared/test-fragility.md. Assertions read the JSON payload fields, not
rendered prose. Hermetic: tmp-dir fixture repos, no git, no network.

design: design-complete-final-doc-state
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import final_doc_state
import living_doc_archive
import verify_moves

DOCS = "three-pillars-docs"
RM = f"{DOCS}/product_roadmap.md"
ARCH = f"{DOCS}/product_roadmap_archive.md"
KI = f"{DOCS}/known_issues.md"
SLUG, OTHER = "slug", "other"
DONE = f"{DOCS}/completed-tp-designs/{SLUG}"
LIVING = {*living_doc_archive.ARCHIVES, *living_doc_archive.ARCHIVES.values()}
PENDING, NUMBERLESS = "Completion PR pending", "Done (completion PR)"
TOOLS = 'python3 "$TP_ROOT"/skills/_shared'
INV_FIX = f"{TOOLS}/inventory_archive.py --slug {SLUG} --apply --json"
PRE_FIX = f"{TOOLS}/reconcile_docs.py --slug {SLUG} --pre-merge --apply --json"
CITE_FIX = f"{TOOLS}/reconcile_docs.py --archive-cites --slug {SLUG} --apply --json"
VERIFIED = {"verdict": "verified", "rows": [], "pending": [], "cites": [], "fix": []}
ROW = f"| {SLUG} | Fixture. | design | {PENDING} — [design]({DONE}/design.md) | Docs |"
STATE = f"- State bullet (`{SLUG}`, 2026-09-28; {PENDING})."
LEGACY_KI = (f"- ~~Tokens exclude cache~~: **resolved 2026-09-29** by `{SLUG}` "
             "(awaiting PR); the bullet moved to [known_issues_resolved.md](known_issues_resolved.md).")
UNATTR = [f"- Prose (`{SLUG}` with `{OTHER}`; {PENDING}).",
          f"- Prose naming `{SLUG}` and `{OTHER}`; awaiting PR."]
TWICE = f"- `{SLUG}` is {PENDING}, then {PENDING} again."
# The live inventory-row shape: a plain first cell leads the row, and the token's
# parenthetical names another slug, so the two documented placements disagree.
CONFLICT_ROW = f"| {SLUG} | Fixture. | design | Done; ({PENDING}, follow-on of `{OTHER}`) | Docs |"
DECISIONS = f"- `{SLUG}` ({PENDING}).\n"  # a design-dir file: never a living doc


def roadmap(extra_state=()):
    bullets = [f"- **`{SLUG}`** — Implemented, {PENDING} (2026-09-28) — [design]({DONE}/design.md)"]
    bullets += [f"- **`old{i}`** — merged (2026-09-0{i})" for i in (4, 3, 2, 1)]
    return "\n".join([
        "# Product Roadmap", "", "## Current Focus — seeds", "", "### Recent completions", *bullets, "",
        "## Current State", "", STATE, *extra_state, "",
        "## Design Inventory", "", "### Active (arc)", "",
        "| Name | What | Type | Status | Track |", "|---|---|---|---|---|",
        "| unrelated | Stays live. | design | Seed | Docs |", ROW, "",
        "## Roadmap History", "", "- **2026-09-01** — seeded the roadmap.", "",
    ])


def repo(root: Path, *, extra_state=(), files=None, designs=(SLUG,)) -> Path:
    for s in designs:
        (root / DOCS / "completed-tp-designs" / s).mkdir(parents=True, exist_ok=True)
    (root / DONE / "decisions.md").write_text(DECISIONS, encoding="utf-8")
    (root / RM).write_text(roadmap(extra_state), encoding="utf-8")
    for rel, text in (files or {}).items():
        (root / rel).write_text(text, encoding="utf-8")
    return root


def run(capsys, verb, root, slug=SLUG):
    code = final_doc_state.main([verb, "--slug", slug, "--repo-root", str(root), "--json"])
    return code, json.loads(capsys.readouterr().out)


def read(root, rel=RM):
    return (root / rel).read_text(encoding="utf-8")


def line_no(root, needle, rel=RM):
    return next(i for i, ln in enumerate(read(root, rel).splitlines(), 1) if needle in ln)


def snapshot(root):
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def closed(root, capsys):
    assert run(capsys, "close", root)[0] == 0
    return root


def test_close_moves_the_row_then_flips_every_copy(tmp_path, capsys):
    root = repo(tmp_path)
    code, out = run(capsys, "close", root)
    assert code == 0
    assert sorted(out.pop("paths")) == sorted([ARCH, RM])  # the plan fixes the set, not the order
    assert out == {"moved": 2, "flipped": 3, "skipped": [], "refused": None}
    live, archive = read(root).splitlines(), read(root, ARCH).splitlines()
    done_row = ROW.replace(PENDING, NUMBERLESS)
    assert ROW not in live and done_row not in live and archive.count(done_row) == 1
    assert STATE.replace(PENDING, NUMBERLESS) in live
    assert PENDING not in read(root) + read(root, ARCH)
    assert read(root, f"{DONE}/decisions.md") == DECISIONS


def test_second_close_reports_zero_and_writes_nothing(tmp_path, capsys):
    root = closed(repo(tmp_path), capsys)
    before = snapshot(root)
    code, out = run(capsys, "close", root)
    assert code == 0
    assert out == {"moved": 0, "flipped": 0, "skipped": [], "paths": [], "refused": None}
    assert snapshot(root) == before


def test_check_after_close_is_verified(tmp_path, capsys):
    assert run(capsys, "check", closed(repo(tmp_path), capsys)) == (0, VERIFIED)


def test_check_before_close_reports_rows_pending_and_both_fix_lines(tmp_path, capsys):
    root = repo(tmp_path)
    code, out = run(capsys, "check", root)
    assert code == 1 and out["verdict"] == "drift"
    assert out["rows"] == [ROW] and out["cites"] == []
    want = {(RM, line_no(root, needle)) for needle in (STATE, "Implemented,", ROW)}
    assert {(p["file"], p["line"]) for p in out["pending"]} == want
    assert {(p["form"], p["owner"]) for p in out["pending"]} == {("canonical", SLUG)}
    assert sorted(out["fix"]) == sorted([INV_FIX, PRE_FIX])


def test_dead_living_doc_cite_is_drift_with_the_archive_cites_fix(tmp_path, capsys):
    cite = f"- See {DOCS}/tp-designs/{SLUG}/decisions.md for the log."
    root = closed(repo(tmp_path, extra_state=[cite]), capsys)
    code, out = run(capsys, "check", root)
    assert code == 1 and out["verdict"] == "drift"
    assert [(c["file"], c["line"]) for c in out["cites"]] == [(RM, line_no(root, cite))]
    assert out["rows"] == [] and out["pending"] == [] and out["fix"] == [CITE_FIX]


def test_cites_match_the_fix_scope_history_fence_and_live_design_dir(tmp_path, capsys):
    root = closed(repo(tmp_path), capsys)
    path = f"{DOCS}/tp-designs/{SLUG}/decisions.md"
    with open(root / RM, "a", encoding="utf-8") as fh:
        fh.write(f"- See [decisions](tp-designs/{SLUG}/decisions.md)\n\n```\n{path}\n```\n")
    assert run(capsys, "check", root) == (0, VERIFIED)
    with open(root / RM, "a", encoding="utf-8") as fh:
        fh.write(f"\n## Notes\n\n- See {path}.\n")
    (root / DOCS / "tp-designs" / SLUG).mkdir(parents=True)  # not yet a dead cite
    assert run(capsys, "check", root) == (0, VERIFIED)


def test_legacy_form_stays_after_close_and_needs_a_hand_edit(tmp_path, capsys):
    root = closed(repo(tmp_path, files={KI: f"# Known issues\n\n{LEGACY_KI}\n"}), capsys)
    n = line_no(root, "awaiting PR", KI)
    code, out = run(capsys, "check", root)
    assert code == 1 and out["verdict"] == "drift"
    assert out["pending"] == [{"file": KI, "line": n, "form": "legacy", "owner": SLUG}]
    assert out["fix"] == [f"hand-edit {KI}:{n}"]


def test_unattributable_tokens_are_skipped_by_close_and_drift_for_both_slugs(tmp_path, capsys):
    root = repo(tmp_path, extra_state=UNATTR, designs=(SLUG, OTHER))
    code, out = run(capsys, "close", root)
    n1, n2 = (line_no(root, text) for text in UNATTR)
    assert code == 0 and out["skipped"] == [{"file": RM, "line_no": n1, "reason": "unattributable"}]
    assert read(root).splitlines()[n1 - 1] == UNATTR[0]
    for slug in (SLUG, OTHER):
        code, out = run(capsys, "check", root, slug)
        assert code == 1 and out["verdict"] == "drift" and out["rows"] == []
        assert {(p["line"], p["form"], p["owner"]) for p in out["pending"]} == {
            (n1, "canonical", None), (n2, "legacy", None)}
        assert sorted(out["fix"]) == sorted([f"hand-edit {RM}:{n1}", f"hand-edit {RM}:{n2}"])


def test_plain_cell_row_whose_paren_names_another_slug_is_skipped_and_drift(tmp_path, capsys):
    root = repo(tmp_path, designs=(SLUG, OTHER))
    (root / RM).write_text(read(root).replace(ROW, CONFLICT_ROW), encoding="utf-8")
    code, out = run(capsys, "close", root)
    n = line_no(root, CONFLICT_ROW, ARCH)  # moved verbatim, token untouched
    assert code == 0 and out["refused"] is None
    assert out["skipped"] == [{"file": ARCH, "line_no": n, "reason": "unattributable"}]
    assert CONFLICT_ROW not in read(root).splitlines()
    for slug in (SLUG, OTHER):
        code, out = run(capsys, "check", root, slug)
        assert code == 1 and out["verdict"] == "drift" and out["rows"] == []
        assert out["pending"] == [{"file": ARCH, "line": n, "form": "canonical", "owner": None}]
        assert out["fix"] == [f"hand-edit {ARCH}:{n}"]


@pytest.mark.parametrize("line", [
    f"- **2026-10-01** — Fixture — [design]({DONE}/design.md) — {PENDING}",
    f"- Landed **{SLUG}** ({PENDING}).",
    f"- The {SLUG} fix shipped: {PENDING}",
])
def test_unattributable_token_on_a_line_mentioning_the_slug_unticked_is_drift(
        tmp_path, capsys, line):
    root = repo(tmp_path, extra_state=[line])
    out = run(capsys, "close", root)[1]
    n = line_no(root, line)
    assert out["skipped"] == [{"file": RM, "line_no": n, "reason": "unattributable"}]
    code, out = run(capsys, "check", root)
    assert code == 1 and out["verdict"] == "drift"
    assert out["pending"] == [{"file": RM, "line": n, "form": "canonical", "owner": None}]
    assert out["fix"] == [f"hand-edit {RM}:{n}"]


def test_check_never_verifies_a_living_doc_it_cannot_decode(tmp_path, capsys):
    root = closed(repo(tmp_path), capsys)
    (root / KI).write_bytes(f"# Known issues\n\ncaf\xe9\n\n- `{SLUG}` — {PENDING}\n"
                            .encode("utf-8").replace(b"\xc3\xa9", b"\xe9"))
    out = run(capsys, "close", root)[1]
    assert out["skipped"] == [{"file": KI, "line_no": 0, "reason": "decode-failure"}]
    code, out = run(capsys, "check", root)
    assert code == 1 and out["verdict"] == "drift"
    assert out["pending"] == [{"file": KI, "line": 0, "form": "decode-failure", "owner": None}]
    assert out["fix"] == [f"hand-edit {KI}:0"]

def test_two_tokens_on_one_line_are_a_hand_edit_not_the_pre_merge_fix(tmp_path, capsys):
    root = repo(tmp_path, extra_state=[TWICE])
    out = run(capsys, "close", root)[1]
    n = line_no(root, TWICE)
    assert out["skipped"] == [{"file": RM, "line_no": n, "reason": "ambiguous-multi-match"}]
    code, out = run(capsys, "check", root)
    assert code == 1 and out["verdict"] == "drift"
    assert sorted(p["line"] for p in out["pending"]) == [n, n]
    assert out["fix"] == [f"hand-edit {RM}:{n}"]


def test_verifier_refusal_makes_close_exit_1_and_writes_nothing(tmp_path, capsys, monkeypatch):
    root = repo(tmp_path)
    before = snapshot(root)
    monkeypatch.setattr(verify_moves, "verify_move", lambda *a, **k: ["lost: boom"])
    code, out = run(capsys, "close", root)
    assert code == 1 and "boom" in out["refused"]
    assert (out["moved"], out["flipped"], out["paths"]) == (0, 0, [])
    assert snapshot(root) == before


def test_repo_without_a_roadmap_is_a_clean_noop(tmp_path, capsys):
    (tmp_path / DOCS).mkdir()
    code, out = run(capsys, "close", tmp_path)
    assert code == 0
    assert out == {"moved": 0, "flipped": 0, "skipped": [], "paths": [], "refused": None}
    assert run(capsys, "check", tmp_path) == (0, VERIFIED)


SCENARIOS = {
    "plain": lambda r: repo(r),
    "legacy": lambda r: repo(r, files={KI: f"# Known issues\n\n{LEGACY_KI}\n"}),
    "unattributable": lambda r: repo(r, extra_state=UNATTR, designs=(SLUG, OTHER)),
    "two-tokens": lambda r: repo(r, extra_state=[TWICE]),
    "no-roadmap": lambda r: (r / DOCS).mkdir() or r,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_close_paths_are_only_living_docs_and_their_archives(tmp_path, capsys, name):
    root = SCENARIOS[name](tmp_path)
    for _ in range(2):  # the idempotent second run holds to the property too
        assert set(run(capsys, "close", root)[1]["paths"]) <= LIVING


def test_cli_entry_point_exit_codes(tmp_path):
    script = str(Path(final_doc_state.__file__))
    usage = subprocess.run([sys.executable, script, "close"], capture_output=True, text=True)
    assert usage.returncode == 2
    (tmp_path / DOCS).mkdir()
    ok = subprocess.run([sys.executable, script, "check", "--slug", SLUG, "--repo-root",
                         str(tmp_path), "--json"], capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(ok.stdout)["verdict"] == "verified"
