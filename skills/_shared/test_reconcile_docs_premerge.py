"""Tests for the pre-merge surface: pending_flip.scan and reconcile_docs --pre-merge.

scan reports the pending tokens that remain for one slug (canonical and the
frozen legacy forms), sharing flip's token iterator and attribution rule. The
CLI `--pre-merge` mode drives pending_flip.flip with the standard JSON payload.

Oracles: example (the plan header's line shapes) and schema (the report dict
keys, the CLI payload keys), per skills/_shared/test-fragility.md. Hermetic:
tmp-dir fixture repos, no git, no network.

design: design-complete-final-doc-state
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pending_flip
from reconcile_docs import main

DOCS = "three-pillars-docs"
RM = f"{DOCS}/product_roadmap.md"
KI = f"{DOCS}/known_issues.md"
RMA = f"{DOCS}/product_roadmap_archive.md"
SLUGS = ("s1", "s2")
SLUGS3 = ("cheap-tier-offload", "cheap-tier-review-prep", "task-worker-sonnet")
LEGACY_FORMS = ["awaiting PR", "Awaiting PR", "PR pending", "PR (pending)"]
FTP = (
    "3. **`s1`** (**implemented**, PR pending; Parts A–F). Its Part G "
    "proof-root work was **split back out to `s2`** (operator, 2026-09-30); FTP "
    "skips Phase 11."
)
FOLLOW = (
    "**Follow-on:** `cheap-tier-offload` (awaiting PR) built the Sonnet task path "
    "as its opt-in task lever; its A/B runs, `cheap-tier-review-prep` and the M46 "
    "fix are owed (Active inventory)."
)
ISSUE = (
    "- ~~Tokens exclude cache~~: **resolved 2026-09-29** by `task-worker-sonnet` "
    "(awaiting PR); the bullet moved to [known_issues_resolved.md]"
    "(known_issues_resolved.md) §L139."
)
ROW = "| s1 | x | design | Completion PR pending — [design](…) | Docs |"
CITE = "# three-pillars-docs/tp-designs/s1/design.md\n"


def repo(root: Path, files: dict, slugs=SLUGS) -> Path:
    for s in slugs:
        (root / DOCS / "completed-tp-designs" / s).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def scan_doc(root, text, slug="s1", rel=RM, slugs=SLUGS):
    repo(root, {rel: text}, slugs)
    return pending_flip.scan(root, slug)


def scan_line(root, line, slug="s1", rel=RM, slugs=SLUGS):
    """scan() over a fixture doc whose only content is `line` (file line 3)."""
    return scan_doc(root, f"# Doc\n\n{line}\n", slug, rel, slugs)


def hit(form, owner, rel=RM, line=3):
    return {"file": rel, "line": line, "form": form, "owner": owner}


@pytest.mark.parametrize("token", ["Completion PR pending", "completion PR pending (Tier 6)"])
def test_canonical_token_is_reported_once_never_also_as_legacy(tmp_path, token):
    assert scan_line(tmp_path, f"- `s1` ({token}).") == [hit("canonical", "s1")]


@pytest.mark.parametrize("form", LEGACY_FORMS)
def test_legacy_forms_are_reported_as_legacy_and_flip_never_rewrites_them(tmp_path, form):
    line = f"- Prose (`s1`; {form})."
    assert scan_line(tmp_path, line) == [hit("legacy", "s1")]
    assert pending_flip.flip(tmp_path, "s1", 214, apply=True) == ([], [])
    assert (tmp_path / RM).read_text(encoding="utf-8").splitlines()[2] == line


def test_numbered_item_legacy_line_is_attributed_to_its_lead_slug(tmp_path):
    assert scan_line(tmp_path / "a", FTP) == [hit("legacy", "s1")]
    assert scan_line(tmp_path / "b", FTP, slug="s2") == []


@pytest.mark.parametrize("rel, line, owner", [(RM, FOLLOW, SLUGS3[0]), (KI, ISSUE, SLUGS3[2])])
def test_real_adjacency_shapes_are_owned_by_the_adjacent_slug_only(tmp_path, rel, line, owner):
    repo(tmp_path, {rel: f"# Doc\n\n{line}\n"}, SLUGS3)
    for slug in SLUGS3:
        want = [hit("legacy", owner, rel)] if slug == owner else []
        assert pending_flip.scan(tmp_path, slug) == want


@pytest.mark.parametrize("line", [
    "- Prose (`s1` with `s2`; Completion PR pending).",
    "- Prose naming `s1` and `s2`; awaiting PR.",
])
def test_unattributable_token_is_reported_with_null_owner_for_each_named_slug(tmp_path, line):
    for slug in SLUGS:
        (r,) = scan_line(tmp_path, line, slug=slug, slugs=("s1", "s2", "s3"))
        assert r["owner"] is None and (r["file"], r["line"]) == (RM, 3)
    assert pending_flip.scan(tmp_path, "s3") == []


def test_a_token_attributed_to_another_slug_is_never_reported(tmp_path):
    line = "- `s2` (Completion PR pending)."
    assert scan_line(tmp_path / "a", line, slug="s1") == []
    assert scan_line(tmp_path / "b", line, slug="s2") == [hit("canonical", "s2")]


@pytest.mark.parametrize("doc", [
    "## Roadmap History\n\n- `s1` merged (Completion PR pending, awaiting PR).\n",
    "```\n- `s1` (Completion PR pending).\n```\n",
    "- `s1` says `Completion PR pending` and `awaiting PR` here.\n",
    '- `s1` says "Completion PR pending" and "PR pending" here.\n',
])
def test_history_fenced_and_quoted_mentions_are_never_reported(tmp_path, doc):
    assert scan_doc(tmp_path, doc) == []


def test_scan_covers_every_living_doc_and_missing_files_are_noops(tmp_path):
    assert pending_flip.scan(tmp_path, "s1") == []
    repo(tmp_path, {
        KI: "# KI\n\n- `s1` (awaiting PR).\n",
        RMA: "# RMA\n\n| s1 | x | design | Completion PR pending | Docs |\n",
    })
    got = sorted((r["file"], r["line"], r["form"], r["owner"]) for r in pending_flip.scan(tmp_path, "s1"))
    assert got == [(KI, 3, "legacy", "s1"), (RMA, 3, "canonical", "s1")]


def run_cli(root, capsys, *args):
    assert main(["reconcile_docs.py", "--repo", str(root), *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_pre_merge_apply_writes_done_pr_number_and_runs_no_other_step(tmp_path, capsys):
    repo(tmp_path, {RM: f"# Doc\n\n{ROW}\n", "skills/foo.py": CITE})
    out = run_cli(tmp_path, capsys, "--slug", "s1", "--pre-merge", "--pr", "7", "--apply", "--json")
    assert set(out) == {"edits", "skipped"} and out["skipped"] == []
    (e,) = out["edits"]
    assert (e["kind"], e["path"], e["line"], e["slug"]) == ("status-flip", RM, 3, "s1")
    text = (tmp_path / RM).read_text(encoding="utf-8")
    assert "Done — PR #7" in text and "merged PR #7" not in text
    assert (tmp_path / "skills/foo.py").read_text(encoding="utf-8") == CITE


def test_pre_merge_without_apply_reports_the_plan_and_writes_nothing(tmp_path, capsys):
    doc = f"# Doc\n\n{ROW}\n"
    repo(tmp_path, {RM: doc})
    out = run_cli(tmp_path, capsys, "--slug", "s1", "--pre-merge", "--json")
    assert [e["kind"] for e in out["edits"]] == ["status-flip"]
    assert (tmp_path / RM).read_text(encoding="utf-8") == doc


@pytest.mark.parametrize("args", [
    ["--pre-merge"],
    ["--pre-merge", "--sweep"],
    ["--slug", "s1", "--pre-merge", "--archive-cites"],
])
def test_pre_merge_mode_errors_exit_zero_with_an_error_payload(tmp_path, capsys, args):
    doc = f"# Doc\n\n{ROW}\n"
    repo(tmp_path, {RM: doc, "skills/foo.py": CITE})
    out = run_cli(tmp_path, capsys, *args, "--apply", "--json")
    assert out["error"] and out["edits"] == [] and out["skipped"] == []
    assert (tmp_path / RM).read_text(encoding="utf-8") == doc
    assert (tmp_path / "skills/foo.py").read_text(encoding="utf-8") == CITE
