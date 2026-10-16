"""Tests for inventory_archive.py — the merged-design Design Inventory row
mover (plan Task 1.4; post-converge fix F1: `/tp-post-merge` owns the move and
selects the row by slug, never by Status text).

Cases, named by tag: a Done row moves under the matching archive sub-heading
(a); a missing archive sub-heading is created with the live table's repeated
header and delimiter (b); a `Completion PR pending (Tier 6)` row moves too (c);
the row moves whatever its Status text says — learn's `Implemented — awaiting
PR`, post-merge's `merged PR #N`, even a Seed — and a slug with no row is a
no-op with a reason naming the slug (d); with no archive file, the archive is
created from ARCHIVE_HEADER and verify_move passes with scaffold_lines (e);
`### Recent completions` keeps the newest four bullets live and rolls the rest,
newest-first, before the archive's older bullets (f); and the CLI `--slug S
[--apply] [--json]` dry-runs by default, applies with --apply, and exits 0 with
a reason when nothing moves (g).

Run with: python -m pytest skills/_shared/test_inventory_archive.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from inventory_archive import move_completed
from living_doc_archive import ARCHIVE_HEADER
import verify_moves

MODULE = Path(__file__).resolve().parent / "inventory_archive.py"

LIVE_REL = "three-pillars-docs/product_roadmap.md"
ARCHIVE_REL = "three-pillars-docs/product_roadmap_archive.md"
INVENTORY_ARCHIVE_HEADING = "## Design Inventory — completed and superseded rows"

HEADER4 = "| # | Name | Type | Status | Track |"
DELM4 = "|---|---|---|---|---|"
HEADER3 = "| Design | What | Status |"
DELM3 = "|---|---|---|"

ROW_CONSUMER = "| consumer-repo-parity | What for consumer-repo-parity. | design | Done — PR #165 — [design](x) | Track |"


def make_repo(tmp_path, live_text, slug_dirs, archive_text=None):
    root = tmp_path / "repo"
    (root / LIVE_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / LIVE_REL).write_text(live_text, encoding="utf-8")
    for slug in slug_dirs:
        (root / "three-pillars-docs" / "tp-designs" / slug).mkdir(parents=True)
    if archive_text is not None:
        path = root / ARCHIVE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(archive_text, encoding="utf-8")
    return root


def live_doc(rows, heading="### Active (canon-reframe arc)",
             header=HEADER4, delim=DELM4, bullets=()):
    parts = [
        "# Product Roadmap", "",
        "## Current Focus — seeds (operator directive 2026-06-02)", "",
    ]
    if bullets:
        parts += ["### Recent completions", *bullets, ""]
    parts += ["## Design Inventory", "", heading, "", header, delim]
    parts += [f"| {slug} | What for {slug}. | design | {status} | Track |"
              for slug, status in rows]
    parts += ["", "## Methodology", "", "- stay live", ""]
    return "\n".join(parts) + "\n"


def archive_doc(subheading):
    return (
        ARCHIVE_HEADER[ARCHIVE_REL]
        + INVENTORY_ARCHIVE_HEADING + "\n\n"
        + subheading + "\n\n"
        + HEADER4 + "\n" + DELM4 + "\n"
        + "| prior-done | A prior row. | design | Done — PR #9 | Distribution |\n"
    )


def read(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def run_cli(root, *argv):
    return subprocess.run(
        [sys.executable, str(MODULE), *argv, "--repo-root", str(root)],
        cwd=str(root), capture_output=True, text=True,
    )


def test_a_done_row_moves_under_matching_subheading(tmp_path):
    live = live_doc([("consumer-repo-parity", "Done — PR #165 — [design](x)"),
                     ("other-slug", "Seed")])
    root = make_repo(tmp_path, live, ["consumer-repo-parity", "other-slug"],
                     archive_doc("### Active (canon-reframe arc)"))
    before_live = read(root, LIVE_REL)
    before_archive = read(root, ARCHIVE_REL)

    result = move_completed(root, "consumer-repo-parity", apply=True)

    assert result.moved == 1
    assert result.reason is None
    after_live = read(root, LIVE_REL)
    after_archive = read(root, ARCHIVE_REL)
    assert ROW_CONSUMER not in after_live
    assert "| other-slug |" in after_live
    assert ROW_CONSUMER in after_archive
    assert verify_moves.verify_move(
        before_live, after_live, before_archive, after_archive,
        scaffold=verify_moves.scaffold_lines(ARCHIVE_REL, after_archive)) == []


def test_b_missing_subheading_created_with_table_header(tmp_path):
    live = live_doc([("shipped-slug", "Done — PR #7")],
                    heading="### Shipped (pre-pivot — historical reference)",
                    header=HEADER3, delim=DELM3)
    live = live.replace(
        "| shipped-slug | What for shipped-slug. | design | Done — PR #7 | Track |",
        "| shipped-slug | A shipped row. | Done — PR #7 |")
    root = make_repo(tmp_path, live, ["shipped-slug"],
                     archive_doc("### Post-mortem promotions (wave1-0605 — 2026-06-06)"))
    before_live = read(root, LIVE_REL)
    before_archive = read(root, ARCHIVE_REL)
    row_line = "| shipped-slug | A shipped row. | Done — PR #7 |"

    result = move_completed(root, "shipped-slug", apply=True)

    assert result.moved == 1
    assert result.reason is None
    after_archive = read(root, ARCHIVE_REL)
    assert row_line not in before_archive
    assert row_line in after_archive
    block = (
        "### Shipped (pre-pivot — historical reference)\n\n"
        + HEADER3 + "\n" + DELM3 + "\n" + row_line + "\n"
    )
    assert block in after_archive
    assert verify_moves.verify_move(
        before_live, read(root, LIVE_REL), before_archive, after_archive,
        scaffold=verify_moves.scaffold_lines(ARCHIVE_REL, after_archive)) == []


def test_c_completion_pr_pending_row_moves(tmp_path):
    live = live_doc([("pending-slug", "Completion PR pending (Tier 6)")])
    root = make_repo(tmp_path, live, ["pending-slug"],
                     archive_doc("### Active (canon-reframe arc)"))

    result = move_completed(root, "pending-slug", apply=True)

    assert result.moved == 1
    assert result.reason is None
    row_line = "| pending-slug | What for pending-slug. | design | Completion PR pending (Tier 6) | Track |"
    assert row_line not in read(root, LIVE_REL)
    assert row_line in read(root, ARCHIVE_REL)


@pytest.mark.parametrize("status", [
    "Implemented — awaiting PR — [design](x)",  # what /tp-design-learn writes
    "merged PR #177",                            # what reconcile_docs flips to
    "Seed",                                      # selection is by slug, not status
])
def test_d_row_moves_whatever_its_status(tmp_path, status):
    slug = "any-slug"
    live = live_doc([(slug, status), ("other-slug", "Seed")])
    root = make_repo(tmp_path, live, [slug, "other-slug"],
                     archive_doc("### Active (canon-reframe arc)"))
    before_live = read(root, LIVE_REL)
    before_archive = read(root, ARCHIVE_REL)
    row_line = f"| {slug} | What for {slug}. | design | {status} | Track |"

    result = move_completed(root, slug, apply=True)

    assert (result.moved, result.reason, result.rows) == (1, None, [row_line])
    after_live, after_archive = read(root, LIVE_REL), read(root, ARCHIVE_REL)
    assert row_line not in after_live and "| other-slug |" in after_live
    assert row_line in after_archive
    assert verify_moves.verify_move(
        before_live, after_live, before_archive, after_archive,
        scaffold=verify_moves.scaffold_lines(ARCHIVE_REL, after_archive)) == []
    again = move_completed(root, slug, apply=True)  # idempotent re-run
    assert again.moved == 0 and slug in again.reason
    assert read(root, ARCHIVE_REL) == after_archive


def test_d_missing_slug_does_nothing(tmp_path):
    live = live_doc([("consumer-repo-parity", "Done — PR #165")])
    root = make_repo(tmp_path, live, ["consumer-repo-parity"],
                     archive_doc("### Active (canon-reframe arc)"))
    before_live = read(root, LIVE_REL)

    result = move_completed(root, "ghost-slug", apply=True)

    assert result.moved == 0
    assert "ghost-slug" in result.reason
    assert read(root, LIVE_REL) == before_live


def test_e_missing_archive_created_from_header(tmp_path):
    live = live_doc([("consumer-repo-parity", "Done — PR #165 — [design](x)")])
    root = make_repo(tmp_path, live, ["consumer-repo-parity"])
    assert not (root / ARCHIVE_REL).exists()
    before_live = read(root, LIVE_REL)

    result = move_completed(root, "consumer-repo-parity", apply=True)

    assert result.moved == 1
    assert result.reason is None
    after_archive = read(root, ARCHIVE_REL)
    assert after_archive.startswith(ARCHIVE_HEADER[ARCHIVE_REL])
    assert INVENTORY_ARCHIVE_HEADING in after_archive
    assert "### Active (canon-reframe arc)" in after_archive
    assert ROW_CONSUMER not in read(root, LIVE_REL)
    assert ROW_CONSUMER in after_archive
    assert verify_moves.verify_move(
        before_live, read(root, LIVE_REL), "", after_archive,
        scaffold=verify_moves.scaffold_lines(ARCHIVE_REL, after_archive)) == []


def _bullets(n):
    return [f"- **`b{i}`** — Implemented, awaiting PR (2026-09-{10 + i})" for i in range(n, 0, -1)]


def test_f_recent_completions_keep_newest_four(tmp_path):
    bullets = _bullets(6)  # newest first: b6 .. b1
    live = live_doc([("consumer-repo-parity", "Done — PR #165 — [design](x)")],
                    bullets=bullets)
    archive = (
        ARCHIVE_HEADER[ARCHIVE_REL]
        + "## Current Focus — historical (moved from the live roadmap)\n\n"
        + "### Recent completions — older entries (the newest four stay in the live roadmap)\n\n"
        + "- **`archived-one`** — Done — archived earlier.\n"
    )
    root = make_repo(tmp_path, live, ["consumer-repo-parity"], archive)
    before_live = read(root, LIVE_REL)
    before_archive = read(root, ARCHIVE_REL)

    result = move_completed(root, "consumer-repo-parity", apply=True)

    assert result.moved == 3
    assert result.rows == [ROW_CONSUMER, bullets[4], bullets[5]]
    after_live, after_archive = read(root, LIVE_REL), read(root, ARCHIVE_REL)
    assert all(b in after_live for b in bullets[:4])
    assert not any(b in after_live for b in bullets[4:])
    order = [after_archive.index(x) for x in (bullets[4], bullets[5], "- **`archived-one`**")]
    assert order == sorted(order)  # rolled newest-first, above the older entries
    assert verify_moves.verify_move(
        before_live, after_live, before_archive, after_archive,
        scaffold=verify_moves.scaffold_lines(ARCHIVE_REL, after_archive)) == []


def test_f_four_or_fewer_bullets_stay_live(tmp_path):
    live = live_doc([], bullets=_bullets(4))
    root = make_repo(tmp_path, live, [], archive_doc("### Active (canon-reframe arc)"))
    before = read(root, LIVE_REL)

    result = move_completed(root, "ghost-slug", apply=True)

    assert result.moved == 0 and "ghost-slug" in result.reason
    assert read(root, LIVE_REL) == before


def test_g_cli_dry_run_apply_and_json(tmp_path):
    live = live_doc([("consumer-repo-parity", "Done — PR #165 — [design](x)"),
                     ("seed-slug", "Seed")])
    root = make_repo(tmp_path, live, ["consumer-repo-parity", "seed-slug"],
                     archive_doc("### Active (canon-reframe arc)"))
    before_live = read(root, LIVE_REL)
    before_archive = read(root, ARCHIVE_REL)

    dry = run_cli(root, "--slug", "consumer-repo-parity")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "consumer-repo-parity" in dry.stdout
    assert read(root, LIVE_REL) == before_live  # dry-run writes nothing
    assert read(root, ARCHIVE_REL) == before_archive

    dry_json = run_cli(root, "--slug", "consumer-repo-parity", "--json")
    assert dry_json.returncode == 0, dry_json.stdout + dry_json.stderr
    payload = json.loads(dry_json.stdout)
    assert payload["moved"] == 1
    assert payload["reason"] is None

    applied = run_cli(root, "--slug", "consumer-repo-parity", "--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert ROW_CONSUMER not in read(root, LIVE_REL)
    assert ROW_CONSUMER in read(root, ARCHIVE_REL)

    nothing = run_cli(root, "--slug", "ghost-slug")
    assert nothing.returncode == 0, nothing.stdout + nothing.stderr
    assert "ghost-slug" in nothing.stdout
    assert "| seed-slug |" in read(root, LIVE_REL)
