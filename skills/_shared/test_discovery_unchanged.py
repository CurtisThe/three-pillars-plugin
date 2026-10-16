"""test_discovery_unchanged.py — closing a design's living-doc state never moves discovery.

design-complete-final-doc-state, Behavior 5 (operator constraint, 2026-10-02): the
session-restore / post-merge / closeout / registry lookups find a design by its dir,
its lock phase and the `.claude/last-design` MRU, never by the roadmap's inventory
row or the status text. One fixture is built in two roadmap variants: A keeps the row
live with `Completion PR pending`; B is A after `final_doc_state.py close` and the
`reconcile_docs.py --pre-merge --pr` writeback (or, at the `closed` stage, `close`
alone). Each code-level lookup must answer the same on A and on B (metamorphic), and
`close` and the writeback may write only the living docs and their archives (property).
A lookup that starts reading the roadmap fails here. Oracles: example (the absolute
answers, so a vacuous A == B cannot pass), metamorphic and property, per
skills/_shared/test-fragility.md. Hermetic: tmp-dir fixture repos, no git, no network.

Run with: python3 -m pytest skills/_shared/test_discovery_unchanged.py -q
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

import detect_unarchived
import final_doc_state
import inflight_registry
import living_doc_archive
import reconcile_docs

SKILLS = Path(__file__).resolve().parents[1]
DOCS, SLUG, OTHER = "three-pillars-docs", "dslug", "other"
RM = f"{DOCS}/product_roadmap.md"
ARCHIVED = f"{DOCS}/completed-tp-designs/{SLUG}"
PENDING, NUMBERLESS, NUMBERED = "Completion PR pending", "Done (completion PR)", "Done — PR #177"
LIVING = {*living_doc_archive.ARCHIVES, *living_doc_archive.ARCHIVES.values()}
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
LOCK = {"owner": "dev@example.com", "branch": f"tp/{SLUG}", "phase": "cleanup-pending",
        "last_touched": "2026-09-30T00:00:00Z"}


def _load(name):
    """Import a skill script by path under a private name (no sys.path or module-cache coupling).

    Found by glob, so this shipped test names no skill outside the free tier; None when
    the script is not in the tree (a tier that does not ship it).
    """
    found = list(SKILLS.glob(f"*/scripts/{name}.py"))
    if len(found) != 1:
        return None
    spec = importlib.util.spec_from_file_location(f"_dc_{name}", found[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


list_worktrees = _load("list_worktrees")
teardown = _load("teardown")
pytestmark = pytest.mark.skipif(None in (list_worktrees, teardown),
                                reason="a lookup script is not shipped in this tier")


def _roadmap():
    row = f"| {SLUG} | Fixture. | design | {PENDING} — [design]({ARCHIVED}/design.md) | Docs |"
    return "\n".join([
        "# Product Roadmap", "", "## Current Focus — seeds", "", "### Recent completions",
        f"- **`{SLUG}`** — {PENDING} (2026-09-28) — [design]({ARCHIVED}/design.md)",
        *[f"- **`old{i}`** — merged (2026-09-0{i})" for i in (4, 3, 2, 1)], "",
        "## Current State", "", f"- Fixture shipped (`{SLUG}`, 2026-09-28; {PENDING}).", "",
        "## Design Inventory", "", "### Active (arc)", "",
        "| Name | What | Type | Status | Track |", "|---|---|---|---|---|",
        f"| {OTHER} | In flight. | design | Seed | Docs |", row, "",
        "## Roadmap History", "", "- **2026-09-01** — seeded the roadmap.", "",
    ])


def _build(root: Path) -> Path:
    files = {
        RM: _roadmap(),
        f"{ARCHIVED}/design.md": "# d\n",
        f"{ARCHIVED}/lock.json": json.dumps(LOCK),
        f"{ARCHIVED}/handoff.md": "> LOCAL ONLY (gitignored)\nresume here\n",
        f"{DOCS}/tp-designs/{OTHER}/design.md": "# o\n",
        f"{DOCS}/tp-designs/{OTHER}/implementation-audit.md": "# audit\n",
        f"{DOCS}/tp-designs/{OTHER}/lock.json": json.dumps({**LOCK, "branch": f"tp/{OTHER}",
                                                            "phase": "implement"}),
        ".claude/last-design": f"{SLUG}\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _close(root: Path, stage: str) -> dict:
    """Variant B: the real `close`, then (stage `numbered`) the real Tier 6 writeback."""
    assert final_doc_state.main(["close", "--slug", SLUG, "--repo-root", str(root)]) == 0
    if stage == "numbered":
        argv = ["reconcile_docs.py", "--repo", str(root), "--slug", SLUG, "--pre-merge",
                "--pr", "177", "--apply", "--json"]
        assert reconcile_docs.main(argv) == 0
    return snapshot(root)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def lookups(root: Path) -> dict:
    """Every code-level discovery lookup, answered for the fixture design and the in-flight one."""
    completed = root / DOCS / "completed-tp-designs"
    pending = sorted(p.parent.name for p in completed.glob("*/lock.json")
                     if json.loads(p.read_text(encoding="utf-8")).get("phase") == "cleanup-pending")
    lock = json.loads((completed / SLUG / "lock.json").read_text(encoding="utf-8"))

    def enriched(design):  # the row the worktree lister shows; the root path is not an answer
        wt = list_worktrees._enrich(list_worktrees.Worktree(path=root, branch=f"tp/{design}", head="abc1234"))
        return dataclasses.replace(wt, path=Path("."))

    return {
        "find_unarchived": detect_unarchived.find_unarchived(root),
        "classify": inflight_registry.classify(SLUG, f"tp/{SLUG}", "abc1234", lock, NOW),
        "read_lock_inflight": list_worktrees._read_lock(root, OTHER),
        "read_lock_archived": list_worktrees._read_lock(root, SLUG),
        "read_last_design": list_worktrees._read_last_design(root),
        "enriched": [enriched(SLUG), enriched(OTHER)],
        "cleanup_pending_walk": pending,
        "mru_holds": teardown._mru_holds(root, SLUG),
    }


def test_lookups_find_the_design_while_its_row_is_live(tmp_path):
    answers = lookups(_build(tmp_path))
    assert answers["find_unarchived"] == [
        detect_unarchived.Finding(OTHER, "implementation-audit.md", "tp-design-learn")]
    assert (answers["classify"].phase, answers["classify"].owner) == ("cleanup-pending", LOCK["owner"])
    assert answers["read_lock_inflight"]["phase"] == "implement"
    assert answers["read_lock_archived"] is None  # archived: its lock lives under completed-tp-designs/
    assert answers["read_last_design"] == SLUG and answers["mru_holds"] is True
    assert answers["cleanup_pending_walk"] == [SLUG]
    assert [w.last_design for w in answers["enriched"]] == [SLUG, SLUG]


@pytest.mark.parametrize("stage", ["closed", "numbered"])
def test_no_lookup_reads_the_row_or_the_status_text(tmp_path, stage):
    before = _build(tmp_path / "a")
    shutil.copytree(before, tmp_path / "b")
    after = tmp_path / "b"
    snap_a, snap_b = snapshot(before), _close(after, stage)

    live_a, live_b = snap_a[RM].decode("utf-8"), snap_b[RM].decode("utf-8")
    assert f"| {SLUG} |" in live_a and f"| {SLUG} |" not in live_b  # the variants really differ
    assert PENDING in live_a and PENDING not in live_b
    assert (NUMBERED in live_b) == (stage == "numbered") and (NUMBERLESS in live_b) == (stage == "closed")
    assert lookups(before) == lookups(after)

    changed = {rel for rel in snap_a.keys() | snap_b.keys() if snap_a.get(rel) != snap_b.get(rel)}
    assert RM in changed and changed <= LIVING  # property: only living docs and archives are written
